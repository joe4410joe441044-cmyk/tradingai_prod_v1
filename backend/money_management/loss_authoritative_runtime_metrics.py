"""MM-5A1B authoritative, in-memory runtime metrics state.

The accumulator consumes confirmed runtime observations only.  It performs no
I/O and never calls execution, governance, or persistence.
"""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from threading import RLock
from typing import Optional

from .loss_persistence_models import PersistedLossState
from .loss_runtime_integration_models import StateSource
from .period_aggregation import period_for
from .period_models import PeriodType


def _utc(name, value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(name, value, *, optional=False, nonnegative=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _count(name, value, *, optional=False):
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _runtime_decimal(value, *, nonnegative=False):
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (Decimal, int, float)):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or (nonnegative and result < 0):
        return None
    return result


def _serialize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


@dataclass(frozen=True)
class AuthoritativeLossRuntimeMetrics:
    current_equity: Optional[Decimal]
    balance: Optional[Decimal]
    available_balance: Optional[Decimal]
    realized_pnl: Optional[Decimal]
    unrealized_pnl: Optional[Decimal]
    peak_equity: Optional[Decimal]
    current_drawdown_amount: Optional[Decimal]
    current_drawdown_pct: Optional[Decimal]
    daily_realized_pnl: Optional[Decimal]
    weekly_realized_pnl: Optional[Decimal]
    monthly_realized_pnl: Optional[Decimal]
    open_exposure: Optional[Decimal]
    position_count: Optional[int]
    trade_count_daily: Optional[int]
    trade_count_weekly: Optional[int]
    trade_count_monthly: Optional[int]
    as_of: datetime
    runtime_instance_id: str
    session_id: Optional[int]
    revision: int
    source_state: str
    available: bool
    observation_valid: bool

    def __post_init__(self):
        for name in (
            "current_equity",
            "balance",
            "available_balance",
            "peak_equity",
            "current_drawdown_amount",
            "open_exposure",
        ):
            _decimal(name, getattr(self, name), optional=True, nonnegative=True)
        for name in (
            "realized_pnl",
            "unrealized_pnl",
            "daily_realized_pnl",
            "weekly_realized_pnl",
            "monthly_realized_pnl",
        ):
            _decimal(name, getattr(self, name), optional=True)
        value = _decimal(
            "current_drawdown_pct",
            self.current_drawdown_pct,
            optional=True,
            nonnegative=True,
        )
        if value is not None and value > Decimal("100"):
            raise ValueError("current_drawdown_pct exceeds 100")
        for name in (
            "position_count",
            "trade_count_daily",
            "trade_count_weekly",
            "trade_count_monthly",
        ):
            _count(name, getattr(self, name), optional=True)
        object.__setattr__(self, "as_of", _utc("as_of", self.as_of))
        if not isinstance(self.runtime_instance_id, str) or not self.runtime_instance_id:
            raise ValueError("runtime_instance_id required")
        if self.session_id is not None:
            _count("session_id", self.session_id)
        _count("revision", self.revision)
        if not isinstance(self.source_state, str) or not self.source_state:
            raise ValueError("source_state required")
        if type(self.available) is not bool or type(self.observation_valid) is not bool:
            raise TypeError("availability flags must be bool")

    def to_dict(self):
        return {
            field.name: _serialize(getattr(self, field.name))
            for field in fields(self)
        }

    @property
    def is_complete(self):
        required = (
            self.current_equity,
            self.balance,
            self.available_balance,
            self.realized_pnl,
            self.unrealized_pnl,
            self.peak_equity,
            self.current_drawdown_amount,
            self.current_drawdown_pct,
            self.daily_realized_pnl,
            self.weekly_realized_pnl,
            self.monthly_realized_pnl,
            self.open_exposure,
            self.position_count,
            self.trade_count_daily,
            self.trade_count_weekly,
            self.trade_count_monthly,
        )
        return (
            self.available
            and self.observation_valid
            and all(value is not None for value in required)
        )

    def to_runtime_mapping(self, pending_order_count=None):
        _count("pending_order_count", pending_order_count, optional=True)
        return {
            "capturedAt": self.as_of,
            "sourceRevision": (
                f"{self.runtime_instance_id}:{self.session_id}:"
                f"{self.revision}"
            ),
            "equity": self.current_equity,
            "balance": self.balance,
            "availableBalance": self.available_balance,
            "realizedPnL": self.realized_pnl,
            "unrealizedPnL": self.unrealized_pnl,
            "dailyPnL": self.daily_realized_pnl,
            "weeklyPnL": self.weekly_realized_pnl,
            "monthlyPnL": self.monthly_realized_pnl,
            "peakEquity": self.peak_equity,
            "drawdown": self.current_drawdown_pct,
            "drawdownAmount": self.current_drawdown_amount,
            "openExposure": self.open_exposure,
            "positionCount": self.position_count,
            # Existing MM-4I contract consumes the daily close-execution count.
            "tradeCount": self.trade_count_daily,
            "tradeCountDaily": self.trade_count_daily,
            "tradeCountWeekly": self.trade_count_weekly,
            "tradeCountMonthly": self.trade_count_monthly,
            "pendingOrderCount": pending_order_count,
            "marginUsed": None,
            "cashFlowState": None,
            "runtimeInstanceId": self.runtime_instance_id,
            "sessionId": self.session_id,
            "metricsRevision": self.revision,
            "sourceState": self.source_state,
            "available": self.available,
            "observationValid": self.observation_valid,
        }


class AuthoritativeLossRuntimeMetricsState:
    """RLock-protected accumulator for confirmed account and close events."""

    def __init__(self, runtime_instance_id):
        if not isinstance(runtime_instance_id, str) or not runtime_instance_id:
            raise ValueError("runtime_instance_id required")
        self._lock = RLock()
        self._initialized = False
        self._observed = False
        self._observation_valid = False
        self._runtime_instance_id = runtime_instance_id
        self._session_id = None
        self._revision = 0
        self._as_of = datetime.now(timezone.utc)
        self._source_state = "NOT_INITIALIZED"
        self._balance = None
        self._equity = None
        self._available_balance = None
        self._realized_pnl = None
        self._unrealized_pnl = None
        self._peak_equity = None
        self._daily_pnl = None
        self._weekly_pnl = None
        self._monthly_pnl = None
        self._trade_count_daily = None
        self._trade_count_weekly = None
        self._trade_count_monthly = None
        self._daily_key = None
        self._weekly_key = None
        self._monthly_key = None
        self._open_exposure = None
        self._position_count = None
        self._seen_close_events = set()

    @staticmethod
    def _period_keys(at):
        return (
            period_for(at, PeriodType.DAILY).period_key,
            period_for(at, PeriodType.WEEKLY).period_key,
            period_for(at, PeriodType.MONTHLY).period_key,
        )

    def restore(self, state, state_source, as_of):
        if not isinstance(state, PersistedLossState):
            raise TypeError("persisted loss state required")
        source = StateSource(state_source)
        at = _utc("as_of", as_of)
        daily_key, weekly_key, monthly_key = self._period_keys(at)
        with self._lock:
            if self._initialized:
                return self._snapshot_locked()
            if (
                state.daily_state.period_id != daily_key
                or state.weekly_state.period_id != weekly_key
                or state.monthly_state.period_id != monthly_key
            ):
                raise ValueError("persisted period boundary mismatch")
            self._daily_key = daily_key
            self._weekly_key = weekly_key
            self._monthly_key = monthly_key
            self._daily_pnl = state.daily_state.net_realized_pnl
            self._weekly_pnl = state.weekly_state.net_realized_pnl
            self._monthly_pnl = state.monthly_state.net_realized_pnl
            self._peak_equity = state.drawdown_state.high_water_mark
            # Only an explicitly supplied initial state proves zero prior
            # close executions. Existing persistence v1 stores PnL, not counts.
            counts_known = source is StateSource.INITIAL_STATE
            self._trade_count_daily = 0 if counts_known else None
            self._trade_count_weekly = 0 if counts_known else None
            self._trade_count_monthly = 0 if counts_known else None
            self._as_of = at
            self._source_state = f"RESTORED_{source.value}"
            self._initialized = True
            self._revision += 1
            return self._snapshot_locked()

    def _roll_periods_locked(self, at):
        daily_key, weekly_key, monthly_key = self._period_keys(at)
        if self._monthly_key is not None and monthly_key != self._monthly_key:
            self._monthly_pnl = (
                Decimal("0") if self._monthly_pnl is not None else None
            )
            self._trade_count_monthly = (
                0 if self._trade_count_monthly is not None else None
            )
            self._seen_close_events.clear()
        if self._weekly_key is not None and weekly_key != self._weekly_key:
            self._weekly_pnl = (
                Decimal("0") if self._weekly_pnl is not None else None
            )
            self._trade_count_weekly = (
                0 if self._trade_count_weekly is not None else None
            )
        if self._daily_key is not None and daily_key != self._daily_key:
            self._daily_pnl = (
                Decimal("0") if self._daily_pnl is not None else None
            )
            self._trade_count_daily = (
                0 if self._trade_count_daily is not None else None
            )
        self._daily_key = daily_key
        self._weekly_key = weekly_key
        self._monthly_key = monthly_key

    @staticmethod
    def _position_metrics(position, mark_price):
        if position is None:
            return Decimal("0"), 0
        positions = position if isinstance(position, (list, tuple)) else (position,)
        if not positions or any(not isinstance(item, dict) for item in positions):
            return None, None
        total = Decimal("0")
        for item in positions:
            item_mark = (
                mark_price
                if len(positions) == 1
                else item.get("mark_price", item.get("markPrice"))
            )
            mark = _runtime_decimal(item_mark, nonnegative=True)
            if mark is None or mark <= 0:
                return None, len(positions)
            quantity = _runtime_decimal(item.get("coin_qty"))
            if quantity is None:
                contracts = _runtime_decimal(item.get("qty"))
                multiplier = _runtime_decimal(
                    item.get("multiplier"), nonnegative=True
                )
                if contracts is None or multiplier is None:
                    return None, len(positions)
                quantity = contracts * multiplier
            total += abs(quantity * mark)
        return total, len(positions)

    def observe(
        self,
        *,
        as_of,
        session_id,
        balance,
        equity,
        available_balance,
        realized_pnl,
        unrealized_pnl,
        position,
        mark_price,
        engine_peak_equity=None,
        close_event_id=None,
        realized_pnl_before=None,
        source_state="RUNNING",
    ):
        at = _utc("as_of", as_of)
        if type(session_id) is not int or session_id < 0:
            raise ValueError("session_id invalid")
        if not isinstance(source_state, str) or not source_state:
            raise ValueError("source_state invalid")
        with self._lock:
            self._initialized = True
            self._observed = True
            self._roll_periods_locked(at)
            self._session_id = session_id
            normalized_balance = _runtime_decimal(balance, nonnegative=True)
            normalized_equity = _runtime_decimal(equity, nonnegative=True)
            normalized_available = _runtime_decimal(
                available_balance, nonnegative=True
            )
            normalized_realized = _runtime_decimal(realized_pnl)
            normalized_unrealized = _runtime_decimal(unrealized_pnl)
            self._observation_valid = all(
                raw is None or normalized is not None
                for raw, normalized in (
                    (balance, normalized_balance),
                    (equity, normalized_equity),
                    (available_balance, normalized_available),
                    (realized_pnl, normalized_realized),
                    (unrealized_pnl, normalized_unrealized),
                )
            )
            self._balance = normalized_balance
            self._equity = normalized_equity
            self._available_balance = normalized_available
            self._realized_pnl = normalized_realized
            self._unrealized_pnl = normalized_unrealized
            self._open_exposure, self._position_count = self._position_metrics(
                position, mark_price
            )
            engine_peak = _runtime_decimal(
                engine_peak_equity, nonnegative=True
            )
            if engine_peak_equity is not None and engine_peak is None:
                self._observation_valid = False
            candidates = tuple(
                item
                for item in (self._peak_equity, engine_peak, self._equity)
                if item is not None
            )
            self._peak_equity = max(candidates) if candidates else None

            if close_event_id is not None:
                if not isinstance(close_event_id, str) or not close_event_id:
                    raise ValueError("close_event_id invalid")
                if close_event_id not in self._seen_close_events:
                    self._seen_close_events.add(close_event_id)
                    before = _runtime_decimal(realized_pnl_before)
                    if realized_pnl_before is not None and before is None:
                        self._observation_valid = False
                    after = self._realized_pnl
                    delta = (
                        after - before
                        if before is not None and after is not None
                        else None
                    )
                    if delta is None:
                        self._daily_pnl = None
                        self._weekly_pnl = None
                        self._monthly_pnl = None
                        self._trade_count_daily = None
                        self._trade_count_weekly = None
                        self._trade_count_monthly = None
                    else:
                        for name in ("_daily_pnl", "_weekly_pnl", "_monthly_pnl"):
                            current = getattr(self, name)
                            setattr(
                                self,
                                name,
                                current + delta if current is not None else None,
                            )
                        for name in (
                            "_trade_count_daily",
                            "_trade_count_weekly",
                            "_trade_count_monthly",
                        ):
                            current = getattr(self, name)
                            setattr(
                                self,
                                name,
                                current + 1 if current is not None else None,
                            )

            self._as_of = at
            self._source_state = source_state
            self._revision += 1
            return self._snapshot_locked()

    def _snapshot_locked(self):
        drawdown_amount = None
        drawdown_pct = None
        if self._peak_equity is not None and self._equity is not None:
            drawdown_amount = max(
                self._peak_equity - self._equity, Decimal("0")
            )
            if self._peak_equity > 0:
                drawdown_pct = (
                    drawdown_amount / self._peak_equity * Decimal("100")
                )
        return AuthoritativeLossRuntimeMetrics(
            self._equity,
            self._balance,
            self._available_balance,
            self._realized_pnl,
            self._unrealized_pnl,
            self._peak_equity,
            drawdown_amount,
            drawdown_pct,
            self._daily_pnl,
            self._weekly_pnl,
            self._monthly_pnl,
            self._open_exposure,
            self._position_count,
            self._trade_count_daily,
            self._trade_count_weekly,
            self._trade_count_monthly,
            self._as_of,
            self._runtime_instance_id,
            self._session_id,
            self._revision,
            self._source_state,
            self._source_state == "RUNNING" and self._observed,
            self._observation_valid,
        )

    def snapshot(self):
        with self._lock:
            return self._snapshot_locked()
