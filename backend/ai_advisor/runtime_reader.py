from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

import time

from backend import config as backend_config
from backend.bot_manager.bot_manager import get_existing_bot_manager
from backend.runtime.governance_runtime import governance_state


def _execution_entry_state(value: Any) -> str:
    """Project a permission into the explicit tri-state vocabulary.

    A permission that could not be read must never collapse into ``BLOCKED``.
    """
    if value is True:
        return "ALLOWED"
    if value is False:
        return "BLOCKED"
    return "UNKNOWN"


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
    selection_mode: Optional[str] = None
    market_ready: bool = False
    market_stale: bool = False
    live_order_entry_state: str = "UNAVAILABLE"
    mm_state: Optional[str] = None
    mm_risk_state: Optional[str] = None
    mm_recommended_action: Optional[str] = None
    mm_execution_entry_state: str = "UNAVAILABLE"
    final_execution_entry_state: str = "UNKNOWN"
    health_state: str = "UNKNOWN"


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


def _market_staleness(
    manager: Any,
    running_value: Any,
    warnings: list[str],
) -> bool:
    if running_value is not True:
        return True
    last_update = getattr(manager, "last_update_time", None)
    if (
        isinstance(last_update, bool)
        or not isinstance(last_update, (int, float))
        or last_update is None
    ):
        warnings.append("MARKET_STALE_NO_BASELINE")
        return True
    if time.time() - float(last_update) > 5:
        return True
    return False


def _read_money_management(
    provider: Callable[[], Any],
    warnings: list[str],
) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    if provider is None:
        warnings.append("MM_BOUNDARY_UNAVAILABLE")
        return None, None, None, "UNAVAILABLE"
    try:
        boundary = provider()
    except Exception:
        warnings.append("MM_BOUNDARY_READ_FAILED")
        return None, None, None, "UNAVAILABLE"
    if boundary is None:
        warnings.append("MM_BOUNDARY_NOT_REGISTERED")
        return None, None, None, "UNAVAILABLE"
    status = getattr(boundary, "get_status", None)
    if not callable(status):
        warnings.append("MM_STATUS_PROJECTOR_ABSENT")
        return None, None, None, "UNAVAILABLE"
    try:
        projection = status()
    except Exception:
        warnings.append("MM_STATUS_PROJECTION_FAILED")
        return None, None, None, "UNAVAILABLE"
    if projection is None:
        warnings.append("MM_STATUS_PROJECTION_EMPTY")
        return None, None, None, "UNAVAILABLE"

    state = _optional_string(
        getattr(projection, "lifecycle_state", None),
        "MM_STATE_UNKNOWN",
        warnings,
    )
    risk_state = _optional_string(
        getattr(projection, "risk_state", None),
        "MM_RISK_STATE_UNKNOWN",
        warnings,
    )
    recommended_action = _optional_string(
        getattr(projection, "recommended_action", None),
        "MM_RECOMMENDED_ACTION_UNKNOWN",
        warnings,
    )
    entry_state = _execution_entry_state(
        getattr(projection, "execution_entry_allowed", None)
    )
    return state, risk_state, recommended_action, entry_state


def _health_state(
    manager_state: str,
    market_ready: bool,
    market_stale: bool,
) -> str:
    if manager_state in ("STOPPED", "NOT_CONNECTED"):
        return "STOPPED"
    if manager_state == "UNKNOWN":
        return "UNKNOWN"
    if manager_state == "RUNNING" and market_ready and not market_stale:
        return "HEALTHY"
    return "DEGRADED"


def read_runtime_scalars(
    mm_boundary_provider: Callable[[], Any] = None,
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
            warnings=(
                "MANAGER_NOT_CONNECTED",
                "SOURCE_TIMESTAMP_MISSING",
                "MM_BOUNDARY_UNAVAILABLE",
            ),
            selection_mode=None,
            market_ready=False,
            market_stale=True,
            live_order_entry_state="UNAVAILABLE",
            mm_state=None,
            mm_risk_state=None,
            mm_recommended_action=None,
            mm_execution_entry_state="UNAVAILABLE",
            final_execution_entry_state="UNKNOWN",
            health_state="STOPPED",
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

    selection_mode = _enum_string(
        getattr(manager, "selection_mode", None),
        {"MANUAL", "AUTO"},
        "SELECTION_MODE_UNKNOWN",
        warnings,
        None,
    )
    market_ready = _strict_bool(
        getattr(manager, "market_ready", None),
        "MARKET_READY_INVALID",
        warnings,
    )
    market_stale = _market_staleness(manager, running_value, warnings)

    live_order_entry_allowed = config.get("liveOrderEntryAllowed") is True
    live_order_entry_state = (
        "ALLOWED" if live_order_entry_allowed else "BLOCKED"
    )
    if not isinstance(config, dict):
        live_order_entry_state = "UNAVAILABLE"

    mm_state, mm_risk_state, mm_recommended_action, mm_execution_entry_state = (
        _read_money_management(mm_boundary_provider, warnings)
    )

    real_order_allowed = _real_order_allowed(
        manager,
        mode,
        dry_run_value,
        execution_enabled_value,
        emergency_locked_value,
    )

    gates_determinable = (
        mm_execution_entry_state in ("ALLOWED", "BLOCKED")
        and loop_enabled is not None
        and auto_trade_enabled is not None
        and market_ready is not None
        and market_stale is not None
        and emergency_locked is not None
    )
    if not gates_determinable:
        final_execution_entry_state = "UNKNOWN"
    else:
        final_allowed = (
            mm_execution_entry_state == "ALLOWED"
            and loop_enabled
            and auto_trade_enabled
            and market_ready
            and not market_stale
            and not emergency_locked
            and (mode == "PAPER" or real_order_allowed)
        )
        final_execution_entry_state = (
            "ALLOWED" if final_allowed else "BLOCKED"
        )

    health_state = _health_state(state, market_ready, market_stale)

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
        real_order_allowed=real_order_allowed,
        source_updated_at=_source_updated_at(manager, warnings),
        warnings=tuple(dict.fromkeys(warnings)),
        selection_mode=selection_mode,
        market_ready=market_ready,
        market_stale=market_stale,
        live_order_entry_state=live_order_entry_state,
        mm_state=mm_state,
        mm_risk_state=mm_risk_state,
        mm_recommended_action=mm_recommended_action,
        mm_execution_entry_state=mm_execution_entry_state,
        final_execution_entry_state=final_execution_entry_state,
        health_state=health_state,
    )
