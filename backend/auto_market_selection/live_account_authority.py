"""Fail-closed projection of an existing exchange's Live read-only authority."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional

from backend.money_management.capital_eligibility import build_capital_eligibility_contract
from backend.money_management.live_capital_authority import (
    build_live_capital_eligibility,
)
from backend.money_management.models import MoneyManagementConfig


# CALIBRATION_REQUIRED: this validation-only ceiling is deliberately conservative;
# production tuning requires AMS-6B-R4 read-only observations.
MAXIMUM_LIVE_SNAPSHOT_SKEW = timedelta(seconds=5)


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _quantity(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _response_timestamp(value, completed_at):
    if isinstance(value, Mapping):
        for key in ("evaluatedAt", "timestamp", "lastSync"):
            if key in value:
                return _timestamp(value.get(key))
    return completed_at


def _position_state(value):
    """Validate the normalized existing-client shape without truthiness."""
    if isinstance(value, Mapping):
        entries = [value]
    elif isinstance(value, list):
        entries = value
    else:
        return "UNKNOWN"
    if not entries:
        return "UNKNOWN"
    state = "FLAT"
    for entry in entries:
        if not isinstance(entry, Mapping) or not entry or "qty" not in entry:
            return "UNKNOWN"
        quantity = _quantity(entry.get("qty"))
        if quantity is None:
            return "UNKNOWN"
        if quantity != 0:
            state = "OPEN"
    return state


def _pending_order_state(value):
    if not isinstance(value, Mapping) or value.get("success") is not True:
        return "UNKNOWN"
    count = value.get("count")
    orders = value.get("orders")
    if type(count) is not int or count < 0 or not isinstance(orders, list):
        return "UNKNOWN"
    if len(orders) != count:
        return "UNKNOWN"
    return "NONE" if count == 0 else "EXISTS"


def _fresh(evaluated_at, now, maximum_age):
    return bool(
        evaluated_at
        and timedelta(0) <= now - evaluated_at <= maximum_age
    )


def _failure_reason(error):
    """Classify failures without ever serializing exception or credential text."""
    status = getattr(error, "status_code", getattr(error, "status", None))
    name = type(error).__name__.lower()
    message = str(error).lower()
    if status in (401, 403) or isinstance(error, PermissionError) or "auth" in name:
        return "AUTHENTICATION_FAILED"
    if isinstance(error, TimeoutError) or "timeout" in name or "timed out" in message:
        return "REQUEST_TIMEOUT"
    if status is not None or "http" in name or "http" in message:
        return "HTTP_ERROR"
    return "LIVE_ACCOUNT_UNAVAILABLE"


@dataclass(frozen=True)
class LiveAccountAuthoritySnapshot:
    capital_authority: str
    equity: Optional[Decimal]
    available_capital: Optional[Decimal]
    open_position_state: str
    pending_order_state: str
    current_exposure: Optional[Decimal]
    remaining_exposure: Optional[Decimal]
    evaluated_at: datetime
    authority_fresh: bool
    reason_codes: tuple
    account_evaluated_at: Optional[datetime] = None
    position_evaluated_at: Optional[datetime] = None
    pending_orders_evaluated_at: Optional[datetime] = None
    account_fresh: bool = False
    position_fresh: bool = False
    pending_orders_fresh: bool = False
    snapshot_skew: Optional[timedelta] = None
    snapshot_consistent: bool = False
    capital_source: str = "UNAVAILABLE"
    source_authority: str = "UNAVAILABLE"

    @property
    def ready(self):
        return not self.reason_codes and self.authority_fresh

    def to_dict(self):
        def value(item):
            if isinstance(item, Decimal):
                return format(item, "f")
            if isinstance(item, datetime):
                return item.isoformat().replace("+00:00", "Z")
            if isinstance(item, timedelta):
                return item.total_seconds()
            return item
        return {
            "capitalAuthority": self.capital_authority,
            "capitalSource": self.capital_source,
            "sourceAuthority": self.source_authority,
            "equity": value(self.equity),
            "availableCapital": value(self.available_capital),
            "openPositionState": self.open_position_state,
            "pendingOrderState": self.pending_order_state,
            "currentExposure": value(self.current_exposure),
            "remainingExposure": value(self.remaining_exposure),
            "evaluatedAt": value(self.evaluated_at),
            "authorityEvaluatedAt": value(self.evaluated_at),
            "accountEvaluatedAt": value(self.account_evaluated_at),
            "positionEvaluatedAt": value(self.position_evaluated_at),
            "pendingOrdersEvaluatedAt": value(self.pending_orders_evaluated_at),
            "accountFresh": self.account_fresh,
            "positionFresh": self.position_fresh,
            "pendingOrdersFresh": self.pending_orders_fresh,
            "authorityFresh": self.authority_fresh,
            "snapshotSkewSeconds": value(self.snapshot_skew),
            "snapshotConsistent": self.snapshot_consistent,
            "reasonCodes": list(self.reason_codes),
        }


class ExistingKucoinLiveAccountAuthority:
    """Uses only existing GET-backed exchange methods; never owns credentials."""

    def __init__(self, exchange, *, safety_provider, exposure_provider=None,
                 clock=None, maximum_age=timedelta(seconds=30),
                 maximum_snapshot_skew=MAXIMUM_LIVE_SNAPSHOT_SKEW):
        if any(not callable(method) for method in (
            getattr(exchange, "get_account_overview", None),
            getattr(exchange, "get_positions", None),
            getattr(exchange, "get_open_orders", None), safety_provider,
        )):
            raise TypeError("existing Live read-only exchange authority required")
        if maximum_snapshot_skew is not None and not isinstance(
            maximum_snapshot_skew, timedelta
        ):
            raise TypeError("maximum_snapshot_skew must be timedelta or None")
        self.exchange, self.safety_provider = exchange, safety_provider
        self.exposure_provider = exposure_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.maximum_age = maximum_age
        self.maximum_snapshot_skew = (
            MAXIMUM_LIVE_SNAPSHOT_SKEW
            if maximum_snapshot_skew is None else maximum_snapshot_skew
        )

    def read(self):
        self._preflight()
        reasons = []

        try:
            overview = self.exchange.get_account_overview()
            account_completed_at = self.clock().astimezone(timezone.utc)
        except Exception as error:
            overview = None
            account_completed_at = self.clock().astimezone(timezone.utc)
            reasons.extend(("LIVE_ACCOUNT_UNAVAILABLE", _failure_reason(error)))

        try:
            authority_read = getattr(
                self.exchange, "get_position_authority_snapshot", None
            )
            positions = (
                authority_read() if callable(authority_read)
                else self.exchange.get_positions()
            )
            position_completed_at = self.clock().astimezone(timezone.utc)
            position_state = _position_state(positions)
        except Exception as error:
            positions = None
            position_completed_at = self.clock().astimezone(timezone.utc)
            position_state = "UNKNOWN"
            reasons.extend(("LIVE_POSITION_UNKNOWN", _failure_reason(error)))

        try:
            orders = self.exchange.get_open_orders()
            orders_completed_at = self.clock().astimezone(timezone.utc)
            pending_state = _pending_order_state(orders)
        except Exception as error:
            orders = None
            orders_completed_at = self.clock().astimezone(timezone.utc)
            pending_state = "UNKNOWN"
            reasons.extend(("LIVE_PENDING_ORDER_UNKNOWN", _failure_reason(error)))

        now = self.clock().astimezone(timezone.utc)
        account_at = (
            _timestamp(overview.get("lastSync"))
            if isinstance(overview, Mapping) else None
        )
        position_at = _response_timestamp(positions, position_completed_at)
        orders_at = _response_timestamp(orders, orders_completed_at)
        equity = _decimal(overview.get("equity")) if isinstance(overview, Mapping) else None
        available = (
            _decimal(overview.get("availableBalance"))
            if isinstance(overview, Mapping) else None
        )
        source = overview.get("source") if isinstance(overview, Mapping) else None

        account_valid = bool(
            source == "KUCOIN_FUTURES_READ_ONLY"
            and equity is not None and available is not None and account_at
        )
        if not account_valid:
            reasons.append("LIVE_ACCOUNT_MALFORMED" if overview is not None else "LIVE_ACCOUNT_UNAVAILABLE")
        if source != "KUCOIN_FUTURES_READ_ONLY":
            reasons.append("LIVE_CAPITAL_SOURCE_INVALID")
        if equity is None:
            reasons.append("LIVE_EQUITY_UNAVAILABLE")
        if available is None:
            reasons.append("LIVE_AVAILABLE_CAPITAL_UNAVAILABLE")

        if position_state == "OPEN":
            reasons.append("LIVE_POSITION_OPEN")
        elif position_state == "UNKNOWN":
            reasons.extend(("LIVE_POSITION_UNKNOWN", "LIVE_POSITION_MALFORMED",
                            "LIVE_POSITION_AUTHORITY_UNKNOWN"))
        if pending_state == "EXISTS":
            reasons.append("LIVE_PENDING_ORDER_EXISTS")
        elif pending_state == "UNKNOWN":
            reasons.extend(("LIVE_PENDING_ORDER_UNKNOWN", "LIVE_PENDING_ORDER_MALFORMED",
                            "LIVE_PENDING_ORDER_AUTHORITY_UNKNOWN"))

        account_fresh = account_valid and _fresh(account_at, now, self.maximum_age)
        position_fresh = position_state != "UNKNOWN" and _fresh(
            position_at, now, self.maximum_age
        )
        orders_fresh = pending_state != "UNKNOWN" and _fresh(
            orders_at, now, self.maximum_age
        )
        if not account_fresh:
            reasons.extend(("LIVE_ACCOUNT_STALE", "LIVE_MM_AUTHORITY_NOT_READY"))
        if not position_fresh:
            reasons.append("LIVE_POSITION_STALE")
        if not orders_fresh:
            reasons.append("LIVE_PENDING_ORDER_STALE")

        timestamps = (account_at, position_at, orders_at)
        snapshot_skew = (
            max(timestamps) - min(timestamps) if all(timestamps) else None
        )
        snapshot_consistent = bool(all(timestamps))
        if (
            snapshot_consistent
            and self.maximum_snapshot_skew is not None
            and snapshot_skew > self.maximum_snapshot_skew
        ):
            snapshot_consistent = False
        if not snapshot_consistent:
            reasons.extend(("LIVE_SNAPSHOT_MISMATCH", "LIVE_ACCOUNT_SNAPSHOT_INCONSISTENT"))

        exposure = remaining = None
        if callable(self.exposure_provider) and position_state != "UNKNOWN":
            try:
                values = self.exposure_provider(positions, overview)
                if isinstance(values, Mapping):
                    exposure = _decimal(values.get("currentExposure"))
                    remaining = _decimal(values.get("remainingExposure"))
            except Exception:
                pass
        if (
            position_state == "FLAT"
            and account_fresh and position_fresh and orders_fresh
            and snapshot_consistent
        ):
            exposure = Decimal("0")
        elif exposure is None or remaining is None:
            reasons.append("LIVE_EXPOSURE_AUTHORITY_UNAVAILABLE")

        authority_fresh = bool(
            account_fresh and position_fresh and orders_fresh
            and snapshot_consistent
        )
        evaluated_at = max(timestamps) if all(timestamps) else now
        return LiveAccountAuthoritySnapshot(
            capital_authority=(
                "REAL_LIVE_ACCOUNT"
                if source == "KUCOIN_FUTURES_READ_ONLY" else "UNAVAILABLE"
            ),
            capital_source=(
                "LIVE_ACCOUNT"
                if source == "KUCOIN_FUTURES_READ_ONLY" else "UNAVAILABLE"
            ),
            equity=equity,
            available_capital=available,
            open_position_state=position_state,
            pending_order_state=pending_state,
            current_exposure=exposure,
            remaining_exposure=remaining,
            evaluated_at=evaluated_at,
            authority_fresh=authority_fresh,
            reason_codes=tuple(dict.fromkeys(reasons)),
            account_evaluated_at=account_at,
            position_evaluated_at=position_at,
            pending_orders_evaluated_at=orders_at,
            account_fresh=account_fresh,
            position_fresh=position_fresh,
            pending_orders_fresh=orders_fresh,
            snapshot_skew=snapshot_skew,
            snapshot_consistent=snapshot_consistent,
            source_authority=(
                "REAL_LIVE_ACCOUNT"
                if source == "KUCOIN_FUTURES_READ_ONLY" else "UNAVAILABLE"
            ),
        )

    def build_capital_eligibility(self, snapshot, *, policy):
        if not isinstance(snapshot, LiveAccountAuthoritySnapshot):
            raise RuntimeError("LIVE_MM_AUTHORITY_NOT_READY")
        if isinstance(policy, MoneyManagementConfig):
            return build_live_capital_eligibility(
                snapshot,
                config=policy,
                policy_version="money-management-config/v1",
            )
        required = ("riskBudget", "maxPositionNotional", "totalExposurePercent",
                    "positionCount", "pendingOrderCount", "mmRegime", "policyVersion")
        if not isinstance(policy, Mapping) or any(key not in policy for key in required):
            raise RuntimeError("LIVE_MM_POLICY_UNAVAILABLE")
        safe = bool(
            snapshot.ready
            and snapshot.open_position_state == "FLAT"
            and snapshot.pending_order_state == "NONE"
        )
        return build_capital_eligibility_contract(
            equity=snapshot.equity, available_capital=snapshot.available_capital,
            risk_budget=_decimal(policy["riskBudget"]),
            max_position_notional=_decimal(policy["maxPositionNotional"]),
            total_exposure_percent=_decimal(policy["totalExposurePercent"]),
            open_exposure=snapshot.current_exposure,
            position_count=policy["positionCount"] if safe else None,
            pending_order_count=policy["pendingOrderCount"] if safe else None,
            mm_regime=policy["mmRegime"], policy_version=policy["policyVersion"],
            evaluated_at=snapshot.evaluated_at,
            authority_fresh=snapshot.authority_fresh,
            execution_entry_allowed=safe,
            capital_source="LIVE_ACCOUNT",
            input_authority=snapshot.source_authority,
        )

    def _preflight(self):
        state = self.safety_provider()
        firewall = isinstance(state, Mapping) and all((
            state.get("realOrderAllowed") is False,
            state.get("executionRealOrderDisabled") is True,
            state.get("autoTradeDisabled") is True,
            state.get("emergencyAvailable") is True,
            state.get("governanceAvailable") is True,
        ))
        legacy_read_only = firewall and all((
            state.get("dryRun") is True,
            state.get("liveAutoSwitchDisabled") is True,
        ))
        selection_only = firewall and all((
            state.get("dryRun") is False,
            state.get("liveSelectionOnly") is True,
        ))
        stopped_live_monitoring = firewall and all((
            state.get("dryRun") is False,
            state.get("stoppedLiveMonitoring") is True,
            state.get("liveAutoSwitchDisabled") is True,
        ))
        if not (legacy_read_only or selection_only or stopped_live_monitoring):
            raise RuntimeError("LIVE_ACCOUNT_READ_PREFLIGHT_BLOCKED")
