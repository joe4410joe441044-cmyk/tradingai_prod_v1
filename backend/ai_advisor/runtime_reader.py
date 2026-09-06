import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional, Tuple

from backend import config as backend_config
from backend.bot_manager.bot_manager import get_existing_bot_manager
from backend.runtime.governance_runtime import governance_state


@dataclass(frozen=True)
class MmRuntimeFacts:
    """Read-only, MM-authoritative numeric facts (no duplicated MM math).

    Extracted verbatim from an existing MM status projection (capital and
    metrics), never recalculated here.
    """

    regime: Optional[str] = None
    equity: Optional[float] = None
    available_capital: Optional[float] = None
    exposure: Optional[float] = None
    remaining_exposure: Optional[float] = None
    position_capacity: Optional[int] = None
    remaining_position_capacity: Optional[int] = None
    risk_budget: Optional[float] = None
    drawdown_percent: Optional[float] = None
    ruin_guard_status: Optional[str] = None
    compounding_enabled: Optional[bool] = None
    authority_fresh: Optional[bool] = None
    captured_at: Optional[float] = None


@dataclass(frozen=True)
class RuntimeScalarSnapshot:
    state: str
    mode: Optional[str]
    exchange: Optional[str]
    symbol: Optional[str]
    loop_enabled: bool
    loop_state: str
    auto_trade_enabled: bool
    emergency_locked: bool
    emergency_state: str
    dry_run: bool
    real_order_allowed: bool
    source_updated_at: Optional[float]
    warnings: Tuple[str, ...]
    position_state: str = "UNKNOWN"
    pending_order_state: str = "UNKNOWN"
    market_ready: Optional[bool] = None
    market_symbol: Optional[str] = None
    mm_regime: Optional[str] = None
    mm_equity: Optional[float] = None
    mm_available_capital: Optional[float] = None
    mm_exposure: Optional[float] = None
    mm_remaining_exposure: Optional[float] = None
    mm_position_capacity: Optional[int] = None
    mm_remaining_position_capacity: Optional[int] = None
    mm_risk_budget: Optional[float] = None
    mm_drawdown_percent: Optional[float] = None
    mm_ruin_guard_status: Optional[str] = None
    mm_compounding_enabled: Optional[bool] = None
    mm_authority_fresh: Optional[bool] = None
    mm_captured_at: Optional[float] = None


def _optional_string(value: Any, warning: str, warnings: list[str]) -> Optional[str]:
    if value is None:
        warnings.append(warning)
        return None
    if not isinstance(value, str) or not value.strip():
        warnings.append(warning)
        return None
    return value.strip()


def _strict_bool(value: Any, warning: str, warnings: list[str]) -> bool:
    if not isinstance(value, bool):
        warnings.append(warning)
    return value is True


def _enum_string(
    value: Any,
    allowed: set[str],
    warning: str,
    warnings: list[str],
    fallback: Optional[str],
) -> Optional[str]:
    normalized = _optional_string(value, warning, warnings)
    if normalized is None:
        return fallback
    normalized = normalized.upper()
    if normalized not in allowed:
        warnings.append(warning)
        return fallback
    return normalized


def _source_updated_at(manager: Any, warnings: list[str]) -> Optional[float]:
    state = getattr(manager, "state", None)
    metrics = getattr(state, "runtime_metrics", None)
    if not isinstance(metrics, dict):
        warnings.append("SOURCE_TIMESTAMP_MISSING")
        return None

    value = metrics.get("last_bot_update")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warnings.append("SOURCE_TIMESTAMP_MISSING")
        return None

    return float(value)


def _real_order_allowed(
    manager: Any,
    mode: Optional[str],
    dry_run_value: Any,
    execution_enabled_value: Any,
    emergency_locked_value: Any,
) -> bool:
    gates = (
        mode == "LIVE",
        dry_run_value is False,
        backend_config.ALLOW_LIVE is True,
        backend_config.TRADE_MODE == "live",
        getattr(manager, "exchange_client_ready", None) is True,
        getattr(manager, "exchange_auth_ready", None) is True,
        getattr(manager, "balance_check_ok", None) is True,
        getattr(manager, "position_check_ok", None) is True,
        execution_enabled_value is True,
        emergency_locked_value is False,
    )

    return all(gates)


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(converted):
        return None
    return converted


def _finite_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return int(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    try:
        decimal_value = Decimal(str(value))
    except Exception:
        return None
    if (
        not decimal_value.is_finite()
        or decimal_value != decimal_value.to_integral_value()
    ):
        return None
    return int(decimal_value)


def _epoch_from_datetime(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, datetime):
        return None
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).timestamp()
    except (ValueError, OSError, OverflowError):
        return None


def _read_mm_projection(
    provider: Optional[Callable[[], Any]],
    warnings: list[str],
) -> Any:
    """Resolve the existing MM status projection once (read-only).

    Returns the authoritative ``MoneyManagementStatusResponse`` (or None).
    No MM calculation is performed here.
    """
    if provider is None:
        warnings.append("MM_BOUNDARY_UNAVAILABLE")
        return None
    try:
        boundary = provider()
    except Exception:
        warnings.append("MM_BOUNDARY_READ_FAILED")
        return None
    if boundary is None:
        warnings.append("MM_BOUNDARY_NOT_REGISTERED")
        return None
    status = getattr(boundary, "get_status", None)
    if not callable(status):
        warnings.append("MM_STATUS_PROJECTOR_ABSENT")
        return None
    try:
        projection = status()
    except Exception:
        warnings.append("MM_STATUS_PROJECTION_FAILED")
        return None
    if projection is None:
        warnings.append("MM_STATUS_PROJECTION_EMPTY")
        return None
    return projection


def _mm_runtime_facts(projection: Any, warnings: list[str]) -> MmRuntimeFacts:
    """Reuse the existing MM status projection's capital + metrics verbatim.

    ``capital`` is the authoritative ``CapitalEligibilityContract`` and
    ``metrics`` is the authoritative ``MoneyManagementMetricsResponse`` already
    produced by the MM boundary. No MM math is performed here.
    """
    if projection is None:
        return MmRuntimeFacts()

    capital = getattr(projection, "capital", None)
    metrics = getattr(projection, "metrics", None)

    capital_exposure = _finite_float(getattr(capital, "open_exposure", None))
    metrics_exposure = _finite_float(getattr(metrics, "open_exposure", None))
    metrics_equity = _finite_float(getattr(metrics, "equity", None))
    metrics_available = _finite_float(getattr(metrics, "available_capital", None))
    metrics_risk_budget = _finite_float(
        getattr(metrics, "risk_budget_remaining", None)
    )
    metrics_captured = _epoch_from_datetime(getattr(metrics, "generated_at", None))
    capital_captured = _epoch_from_datetime(getattr(capital, "evaluated_at", None))
    projection_captured = _epoch_from_datetime(
        getattr(projection, "generated_at", None)
    )

    capital_equity = _finite_float(getattr(capital, "equity", None))
    capital_available = _finite_float(getattr(capital, "available_capital", None))
    capital_risk_budget = _finite_float(getattr(capital, "risk_budget", None))

    return MmRuntimeFacts(
        regime=_optional_string(
            getattr(capital, "mm_regime", None),
            "MM_REGIME_UNKNOWN",
            warnings,
        ),
        equity=capital_equity if capital_equity is not None else metrics_equity,
        available_capital=(
            capital_available if capital_available is not None else metrics_available
        ),
        exposure=metrics_exposure if metrics_exposure is not None else capital_exposure,
        remaining_exposure=_finite_float(
            getattr(capital, "remaining_exposure", None)
        ),
        position_capacity=_finite_int(
            getattr(capital, "executable_max_concurrent_positions", None)
        ),
        remaining_position_capacity=_finite_int(
            getattr(capital, "remaining_position_capacity", None)
        ),
        risk_budget=(
            capital_risk_budget
            if capital_risk_budget is not None
            else metrics_risk_budget
        ),
        drawdown_percent=_finite_float(getattr(metrics, "drawdown_percent", None)),
        ruin_guard_status=_optional_string(
            getattr(capital, "ruin_guard_status", None),
            "MM_RUIN_GUARD_UNKNOWN",
            warnings,
        ),
        compounding_enabled=(
            getattr(capital, "compounding_enabled", None)
            if isinstance(getattr(capital, "compounding_enabled", None), bool)
            else None
        ),
        authority_fresh=(
            getattr(capital, "authority_fresh", None)
            if isinstance(getattr(capital, "authority_fresh", None), bool)
            else None
        ),
        captured_at=capital_captured or projection_captured or metrics_captured,
    )


def _position_state(manager: Any, warnings: list[str]) -> str:
    state_obj = getattr(manager, "state", None)
    value = getattr(state_obj, "position_state", None)
    if value in {"FLAT", "OPEN", "remaining", "REMAINING"}:
        return "FLAT" if value == "FLAT" else "OPEN"
    warnings.append("POSITION_STATE_UNKNOWN")
    return "UNKNOWN"


def _pending_order_state(manager: Any, warnings: list[str]) -> str:
    value = getattr(manager, "pending_order", None)
    if value is True:
        return "OPEN"
    if value is False:
        return "NONE"
    warnings.append("PENDING_ORDER_STATE_UNKNOWN")
    return "UNKNOWN"


def read_runtime_scalars(
    mm_boundary_provider: Optional[Callable[[], Any]] = None,
) -> RuntimeScalarSnapshot:
    """Read an existing manager without invoking runtime or refresh methods."""

    manager = get_existing_bot_manager()
    if manager is None:
        return RuntimeScalarSnapshot(
            state="NOT_CONNECTED",
            mode=None,
            exchange=None,
            symbol=None,
            loop_enabled=False,
            loop_state="NOT_CONNECTED",
            auto_trade_enabled=False,
            emergency_locked=False,
            emergency_state="UNKNOWN",
            dry_run=False,
            real_order_allowed=False,
            source_updated_at=None,
            warnings=("MANAGER_NOT_CONNECTED", "SOURCE_TIMESTAMP_MISSING"),
        )

    warnings: list[str] = []
    loop_state = _enum_string(
        getattr(manager, "lifecycle_state", None),
        {"STOPPED", "STARTING", "RUNNING", "STOPPING"},
        "LOOP_STATE_UNKNOWN",
        warnings,
        "UNKNOWN",
    )
    running_value = getattr(manager, "_running", None)
    loop_enabled = (
        _strict_bool(running_value, "LOOP_ENABLED_INVALID", warnings)
        and loop_state == "RUNNING"
    )

    config = getattr(manager, "config", None)
    if not isinstance(config, dict):
        warnings.append("CONFIG_UNAVAILABLE")
        config = {}

    mode = _enum_string(
        config.get("mode"),
        {"PAPER", "LIVE"},
        "MODE_UNKNOWN",
        warnings,
        None,
    )

    dry_run_value = config.get("dry_run")
    dry_run = _strict_bool(dry_run_value, "DRY_RUN_INVALID", warnings)

    execution_enabled_value = governance_state.get("execution_enabled")
    auto_trade_enabled = _strict_bool(
        execution_enabled_value,
        "AUTO_TRADE_ENABLED_INVALID",
        warnings,
    )
    emergency_locked_value = governance_state.get("emergency_stop")
    emergency_locked = _strict_bool(
        emergency_locked_value,
        "EMERGENCY_LOCKED_INVALID",
        warnings,
    )
    emergency_state = _enum_string(
        governance_state.get("emergency_state"),
        {"READY", "PROCESSING", "LOCKED", "ACTION_REQUIRED"},
        "EMERGENCY_STATE_UNKNOWN",
        warnings,
        "UNKNOWN",
    )

    state = (
        "RUNNING"
        if running_value is True
        else "STOPPED" if running_value is False else "UNKNOWN"
    )
    exchange = _optional_string(
        getattr(manager, "exchange_name", None),
        "EXCHANGE_UNKNOWN",
        warnings,
    )
    symbol = _optional_string(
        getattr(manager, "symbol", None),
        "SYMBOL_UNKNOWN",
        warnings,
    )

    mm_projection = _read_mm_projection(mm_boundary_provider, warnings)
    mm_facts = _mm_runtime_facts(mm_projection, warnings)
    position_state = _position_state(manager, warnings)
    pending_order_state = _pending_order_state(manager, warnings)
    market_ready = (
        getattr(manager, "market_ready", None)
        if isinstance(getattr(manager, "market_ready", None), bool)
        else None
    )
    market_symbol = _optional_string(
        getattr(manager, "active_symbol", None),
        "MARKET_SYMBOL_UNKNOWN",
        warnings,
    )

    return RuntimeScalarSnapshot(
        state=state,
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        loop_enabled=loop_enabled,
        loop_state=loop_state,
        auto_trade_enabled=auto_trade_enabled,
        emergency_locked=emergency_locked,
        emergency_state=emergency_state,
        dry_run=dry_run,
        real_order_allowed=_real_order_allowed(
            manager,
            mode,
            dry_run_value,
            execution_enabled_value,
            emergency_locked_value,
        ),
        source_updated_at=_source_updated_at(manager, warnings),
        warnings=tuple(dict.fromkeys(warnings)),
        position_state=position_state,
        pending_order_state=pending_order_state,
        market_ready=market_ready,
        market_symbol=market_symbol,
        mm_regime=mm_facts.regime,
        mm_equity=mm_facts.equity,
        mm_available_capital=mm_facts.available_capital,
        mm_exposure=mm_facts.exposure,
        mm_remaining_exposure=mm_facts.remaining_exposure,
        mm_position_capacity=mm_facts.position_capacity,
        mm_remaining_position_capacity=mm_facts.remaining_position_capacity,
        mm_risk_budget=mm_facts.risk_budget,
        mm_drawdown_percent=mm_facts.drawdown_percent,
        mm_ruin_guard_status=mm_facts.ruin_guard_status,
        mm_compounding_enabled=mm_facts.compounding_enabled,
        mm_authority_fresh=mm_facts.authority_fresh,
        mm_captured_at=mm_facts.captured_at,
    )
