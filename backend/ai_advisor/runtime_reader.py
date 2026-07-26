from dataclasses import dataclass
from typing import Any, Optional, Tuple

from backend import config as backend_config
from backend.bot_manager.bot_manager import get_existing_bot_manager
from backend.runtime.governance_runtime import governance_state


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


def read_runtime_scalars() -> RuntimeScalarSnapshot:
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
    )
