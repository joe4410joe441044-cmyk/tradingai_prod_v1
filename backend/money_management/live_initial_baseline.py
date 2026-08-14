"""One-time, fail-closed Live Money Management baseline bootstrap."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import os
from pathlib import Path

from .enums import RiskState
from .loss_persistence_adapter import LoadStatus, SaveStatus, load_loss_state, save_loss_state
from .loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION, FreshnessStatus, PeriodCode,
    PersistedCashFlowState, PersistedDrawdownState, PersistedLossPeriodState,
    PersistedLossState,
)
from .loss_reason_models import LossMetric, LossReasonContract, PeriodCode as ReasonPeriodCode, ReasonCode, RecommendedAction
from .period_aggregation import period_for
from .period_models import PeriodType


APPROVAL_SOURCE = "EXPLICIT_OPERATOR_APPROVAL"
BASELINE_SOURCE = "REAL_LIVE_ACCOUNT"


class BaselineBootstrapStatus(str, Enum):
    CREATED = "CREATED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class LiveBaselineApproval:
    source: str
    approved_at: datetime

    def __post_init__(self):
        if self.source != APPROVAL_SOURCE:
            raise ValueError("explicit operator approval required")
        if not isinstance(self.approved_at, datetime) or self.approved_at.tzinfo is None:
            raise TypeError("approval time must be timezone-aware")
        object.__setattr__(self, "approved_at", self.approved_at.astimezone(timezone.utc))


@dataclass(frozen=True)
class LiveBaselineBootstrapResult:
    status: BaselineBootstrapStatus
    reason: str
    state: PersistedLossState | None = None
    approval_source: str | None = None
    approval_time: datetime | None = None
    baseline_source: str | None = None


def _period(code, kind, equity, captured_at):
    period = period_for(captured_at, kind)
    zero = Decimal("0")
    return PersistedLossPeriodState(
        code, period.period_key, period.start_at, period.end_at, equity,
        zero, zero, zero, zero, captured_at,
    )


def build_live_initial_loss_state(snapshot, approval, *, captured_at=None):
    """Build v1 state; zeroes mean accumulation since this boundary, never history."""
    if not isinstance(approval, LiveBaselineApproval):
        raise TypeError("typed approval required")
    at = captured_at or approval.approved_at
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise TypeError("captured_at must be timezone-aware")
    at = at.astimezone(timezone.utc)
    equity = getattr(snapshot, "equity", None)
    available = getattr(snapshot, "available_capital", None)
    if any(isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite()
           for value in (equity, available)) or equity <= 0 or available < 0:
        raise ValueError("LIVE_CAPITAL_INVALID")
    if getattr(snapshot, "source_authority", None) != BASELINE_SOURCE:
        raise ValueError("LIVE_BASELINE_AUTHORITY_INVALID")
    if not getattr(snapshot, "authority_fresh", False):
        raise ValueError("LIVE_ACCOUNT_STALE")
    if getattr(snapshot, "open_position_state", None) != "FLAT":
        raise ValueError("LIVE_POSITION_NOT_FLAT")
    if getattr(snapshot, "pending_order_state", None) != "NONE":
        raise ValueError("LIVE_PENDING_ORDERS_NOT_CLEAR")
    if not getattr(snapshot, "snapshot_consistent", False):
        raise ValueError("LIVE_ACCOUNT_SNAPSHOT_INCONSISTENT")
    evaluated_at = getattr(snapshot, "evaluated_at", None)
    if not isinstance(evaluated_at, datetime) or evaluated_at.tzinfo is None or abs(at - evaluated_at.astimezone(timezone.utc)) > timedelta(seconds=30):
        raise ValueError("LIVE_ACCOUNT_NOT_FRESH_AT_INITIALIZATION")
    zero = Decimal("0")
    reason = LossReasonContract(
        "money-management-loss-reason/v1", at, RiskState.NORMAL,
        RecommendedAction.CONTINUE, ReasonCode.NONE, (), (), (), (), (),
        tuple(LossMetric(code, zero, zero) for code in (
            ReasonPeriodCode.DAILY, ReasonPeriodCode.WEEKLY, ReasonPeriodCode.MONTHLY
        )), False,
    )
    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION, "primary", "USDT",
        _period(PeriodCode.DAILY, PeriodType.DAILY, equity, at),
        _period(PeriodCode.WEEKLY, PeriodType.WEEKLY, equity, at),
        _period(PeriodCode.MONTHLY, PeriodType.MONTHLY, equity, at),
        PersistedDrawdownState(equity, equity, zero, zero, at),
        PersistedCashFlowState(False, (), zero, None), reason, at,
        freshness=FreshnessStatus.VALID,
    )


def bootstrap_live_initial_baseline(snapshot, approval, *, persistence_directory, safety_state, captured_at=None):
    """Persist exactly once after all non-trading safety gates pass."""
    base = Path(persistence_directory)
    lock = base / ".loss_limit_baseline.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
    except OSError:
        return LiveBaselineBootstrapResult(BaselineBootstrapStatus.BLOCKED, "BASELINE_INITIALIZATION_IN_PROGRESS")
    try:
        existing = load_loss_state(base)
        if existing.status is not LoadStatus.MISSING:
            reason = "AUTHORITATIVE_STATE_ALREADY_EXISTS" if existing.status is LoadStatus.VALID else "AUTHORITATIVE_STATE_UNSAFE"
            return LiveBaselineBootstrapResult(BaselineBootstrapStatus.BLOCKED, reason)
        required = {
            "botStopped": True, "autoTradeOff": True, "loopStopped": True,
            "realOrderAllowed": False, "liveAutoOff": True, "emergencyReady": True,
        }
        if not isinstance(safety_state, dict) or any(safety_state.get(k) is not v for k, v in required.items()):
            return LiveBaselineBootstrapResult(BaselineBootstrapStatus.BLOCKED, "LIVE_BASELINE_SAFETY_PREFLIGHT_BLOCKED")
        try:
            state = build_live_initial_loss_state(snapshot, approval, captured_at=captured_at)
        except (TypeError, ValueError) as exc:
            return LiveBaselineBootstrapResult(BaselineBootstrapStatus.BLOCKED, str(exc))
        saved = save_loss_state(state, base)
        if saved.status is not SaveStatus.SAVED:
            return LiveBaselineBootstrapResult(BaselineBootstrapStatus.BLOCKED, saved.failure_code.value)
        reread = load_loss_state(base)
        if reread.status is not LoadStatus.VALID or reread.state != state:
            return LiveBaselineBootstrapResult(BaselineBootstrapStatus.BLOCKED, "PERSISTENCE_REREAD_FAILED")
        return LiveBaselineBootstrapResult(
            BaselineBootstrapStatus.CREATED, "INITIAL_BASELINE_CREATED", state,
            approval.source, approval.approved_at, BASELINE_SOURCE,
        )
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
