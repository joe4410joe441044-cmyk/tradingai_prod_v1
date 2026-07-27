"""MM-4I read-only normalization of bot runtime metrics."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from .loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetrics,
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
)


_REQUIRED_FIELDS = (
    "equity",
    "balance",
    "availableBalance",
    "realizedPnL",
    "unrealizedPnL",
    "dailyPnL",
    "weeklyPnL",
    "monthlyPnL",
    "peakEquity",
    "drawdown",
    "openExposure",
    "positionCount",
    "tradeCount",
    "tradeCountDaily",
    "tradeCountWeekly",
    "tradeCountMonthly",
    "runtimeInstanceId",
    "sessionId",
    "metricsRevision",
    "observationValid",
)


class LossRuntimeMetricsSource(ABC):
    @abstractmethod
    def read_metrics(self, request):
        """Return a typed, safe result without exposing a runtime object."""


def _failed(status, reason, metrics=None):
    return LossRuntimeMetricsReadResult(status, metrics, (reason,))


def _decimal(raw, name, *, nonnegative=False):
    value = raw.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{name} invalid")
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} invalid") from exc
    if not normalized.is_finite() or (nonnegative and normalized < 0):
        raise ValueError(f"{name} invalid")
    return normalized


def _count(raw, name):
    value = raw.get(name)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} invalid")
    return value


def _normalize(raw):
    if not isinstance(raw, Mapping):
        raise TypeError("runtime metrics snapshot invalid")
    captured_at = raw.get("capturedAt")
    source_revision = raw.get("sourceRevision")
    source_state = raw.get("sourceState")
    if (
        raw.get("available") is not True
        or captured_at is None
        or source_revision is None
        or source_state is None
    ):
        return None, LossRuntimeMetricsReadStatus.UNAVAILABLE, "runtime metrics unavailable"
    if raw.get("observationValid") is not True:
        return (
            None,
            LossRuntimeMetricsReadStatus.INCONSISTENT,
            "runtime metrics invalid",
        )
    missing = tuple(name for name in _REQUIRED_FIELDS if raw.get(name) is None)
    quality = (
        LossRuntimeDataQuality.PARTIAL
        if missing
        else LossRuntimeDataQuality.COMPLETE
    )
    metrics = LossRuntimeMetrics(
        captured_at=captured_at,
        source_revision=source_revision,
        equity=_decimal(raw, "equity", nonnegative=True),
        balance=_decimal(raw, "balance", nonnegative=True),
        available_balance=_decimal(raw, "availableBalance", nonnegative=True),
        realized_pnl=_decimal(raw, "realizedPnL"),
        unrealized_pnl=_decimal(raw, "unrealizedPnL"),
        daily_pnl=_decimal(raw, "dailyPnL"),
        weekly_pnl=_decimal(raw, "weeklyPnL"),
        monthly_pnl=_decimal(raw, "monthlyPnL"),
        peak_equity=_decimal(raw, "peakEquity", nonnegative=True),
        drawdown=_decimal(raw, "drawdown", nonnegative=True),
        open_exposure=_decimal(raw, "openExposure", nonnegative=True),
        position_count=_count(raw, "positionCount"),
        trade_count=_count(raw, "tradeCount"),
        source_state=source_state,
        pending_order_count=_count(raw, "pendingOrderCount"),
        margin_used=_decimal(raw, "marginUsed", nonnegative=True),
        cash_flow_state=raw.get("cashFlowState"),
        trade_count_daily=_count(raw, "tradeCountDaily"),
        trade_count_weekly=_count(raw, "tradeCountWeekly"),
        trade_count_monthly=_count(raw, "tradeCountMonthly"),
        runtime_instance_id=raw.get("runtimeInstanceId"),
        session_id=_count(raw, "sessionId"),
        metrics_revision=_count(raw, "metricsRevision"),
        data_quality=quality,
    )
    if missing:
        return metrics, LossRuntimeMetricsReadStatus.PARTIAL, "required runtime metrics missing"
    return metrics, LossRuntimeMetricsReadStatus.AVAILABLE, None


def _inconsistency(metrics):
    if metrics.available_balance > metrics.balance:
        return "runtime metrics inconsistent"
    if metrics.peak_equity < metrics.equity:
        return "runtime metrics inconsistent"
    if metrics.peak_equity <= 0:
        return "runtime metrics inconsistent"
    if metrics.position_count == 0 and metrics.open_exposure != 0:
        return "runtime metrics inconsistent"
    if (
        metrics.trade_count != metrics.trade_count_daily
        or metrics.trade_count_daily > metrics.trade_count_weekly
        or metrics.trade_count_daily > metrics.trade_count_monthly
    ):
        return "runtime metrics inconsistent"
    expected_drawdown = (
        (metrics.peak_equity - metrics.equity)
        / metrics.peak_equity
        * Decimal("100")
    )
    if abs(metrics.drawdown - expected_drawdown) > Decimal("0.000001"):
        return "runtime metrics inconsistent"
    # Equity feeds can settle asynchronously. Use a bounded materiality test
    # rather than rejecting harmless sub-cent timing differences.
    expected_equity = metrics.balance + metrics.unrealized_pnl
    if abs(metrics.equity - expected_equity) > Decimal("0.01"):
        return "runtime metrics inconsistent"
    return None


class BotManagerLossRuntimeMetricsSource(LossRuntimeMetricsSource):
    """Consumes only BotManager's public, scalar-only read snapshot."""

    def __init__(self, bot_manager):
        reader = getattr(
            bot_manager, "get_runtime_metrics_snapshot", None
        )
        if not callable(reader):
            raise TypeError("bot runtime metrics reader required")
        self._reader = reader

    def read_metrics(self, request):
        if not isinstance(request, LossRuntimeMetricsReadRequest):
            return _failed(
                LossRuntimeMetricsReadStatus.FAILED,
                "runtime metrics request invalid",
            )
        try:
            raw = self._reader()
            metrics, status, reason = _normalize(raw)
            if status is LossRuntimeMetricsReadStatus.UNAVAILABLE:
                return _failed(status, reason)
            if status is LossRuntimeMetricsReadStatus.INCONSISTENT:
                return _failed(status, reason)
            if metrics.captured_at > request.requested_at:
                return LossRuntimeMetricsReadResult(
                    LossRuntimeMetricsReadStatus.INCONSISTENT,
                    LossRuntimeMetrics(
                        **{
                            **metrics.__dict__,
                            "data_quality": LossRuntimeDataQuality.INCONSISTENT,
                        }
                    ),
                    ("runtime metrics timestamp inconsistent",),
                )
            if request.requested_at - metrics.captured_at > request.maximum_age:
                return LossRuntimeMetricsReadResult(
                    LossRuntimeMetricsReadStatus.STALE,
                    LossRuntimeMetrics(
                        **{
                            **metrics.__dict__,
                            "data_quality": LossRuntimeDataQuality.STALE,
                        }
                    ),
                    ("runtime metrics stale",),
                )
            if status is LossRuntimeMetricsReadStatus.PARTIAL:
                return LossRuntimeMetricsReadResult(status, metrics, (reason,))
            inconsistency = _inconsistency(metrics)
            if inconsistency:
                inconsistent = LossRuntimeMetrics(
                    **{
                        **metrics.__dict__,
                        "data_quality": LossRuntimeDataQuality.INCONSISTENT,
                    }
                )
                return LossRuntimeMetricsReadResult(
                    LossRuntimeMetricsReadStatus.INCONSISTENT,
                    inconsistent,
                    (inconsistency,),
                )
            return LossRuntimeMetricsReadResult(status, metrics, ())
        except (TypeError, ValueError, ArithmeticError):
            return _failed(
                LossRuntimeMetricsReadStatus.INCONSISTENT,
                "runtime metrics invalid",
            )
        except Exception:
            return _failed(
                LossRuntimeMetricsReadStatus.FAILED,
                "runtime metrics read failed",
            )
