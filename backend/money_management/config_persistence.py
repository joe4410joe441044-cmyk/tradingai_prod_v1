"""Durable, opt-in Money Management configuration persistence.

Persistence is never implicit. Ordinary boundary construction omits the store
and keeps the existing in-memory behaviour. Production wiring injects an
explicit :class:`MoneyManagementConfigStore` so that the approved Small Account
profile and the HTTP configuration revision survive a process restart.
"""
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from .enums import MoneyManagementProfile, TradingMode
from .models import MoneyManagementConfig

CONFIG_PERSISTENCE_SCHEMA_VERSION = 1
DEFAULT_CONFIG_RELATIVE_PATH = ("logs", "runtime", "money_management_config.json")
CONFIG_PATH_ENVIRONMENT_VARIABLE = "TRADINGAI_MONEY_MANAGEMENT_CONFIG_PATH"

APPROVED_SMALL_ACCOUNT_SYMBOL = "XRPUSDTM"
APPROVED_SMALL_ACCOUNT_MAX_CONTRACTS = Decimal("1")
APPROVED_SMALL_ACCOUNT_MAX_RISK_PERCENT = Decimal("2.0")
APPROVED_SMALL_ACCOUNT_MAX_ABSOLUTE_RISK_USDT = Decimal("0.158")
APPROVED_SMALL_ACCOUNT_MAX_LEVERAGE = Decimal("3")

_ABSENT_SYMBOL_VALUES = frozenset(
    (
        "",
        "NONE",
        "NULL",
        "UNKNOWN",
        "NOT AVAILABLE",
        "NOT_AVAILABLE",
        "N/A",
        "NA",
    )
)

_REQUIRED_DECIMAL_FIELDS = frozenset(
    (
        "initial_reference_equity",
        "risk_per_trade_pct",
        "maximum_position_notional",
        "maximum_drawdown_pct",
        "total_exposure_pct",
        "single_symbol_exposure_pct",
        "maximum_leverage",
        "daily_loss_warning_pct",
        "daily_loss_block_pct",
        "weekly_loss_warning_pct",
        "weekly_loss_block_pct",
        "monthly_loss_warning_pct",
        "monthly_loss_block_pct",
        "profit_lock_start_pct",
        "initial_cooldown_minutes",
        "extended_cooldown_hours",
        "recovery_25_multiplier",
        "recovery_50_multiplier",
        "small_account_max_contracts",
        "small_account_max_risk_percent",
        "small_account_max_leverage",
    )
)
_OPTIONAL_DECIMAL_FIELDS = frozenset(("small_account_max_absolute_risk_usdt",))
_BOOLEAN_FIELDS = frozenset(
    (
        "multi_bot_enabled",
        "compounding_enabled",
        "small_account_minimum_contract_mode",
        "small_account_require_isolated",
        "small_account_require_flat_before_entry",
        "small_account_require_no_pending",
        "small_account_require_manual_selection",
    )
)
_ENUM_FIELDS = {
    "profile": MoneyManagementProfile,
    "mode": TradingMode,
}
_STRING_FIELDS = frozenset(("small_account_allowed_symbol",))

_ALL_CONFIG_FIELDS = frozenset(
    (
        *_ENUM_FIELDS,
        *_BOOLEAN_FIELDS,
        *_REQUIRED_DECIMAL_FIELDS,
        *_OPTIONAL_DECIMAL_FIELDS,
        *_STRING_FIELDS,
    )
)


class MoneyManagementConfigPersistenceError(RuntimeError):
    """Safe persistence failure without leaking secret-bearing content."""


class MoneyManagementConfigCorruptError(MoneyManagementConfigPersistenceError):
    """Persisted configuration is unreadable, unsafe, or structurally invalid."""


def _utc(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _format_timestamp(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise MoneyManagementConfigCorruptError("updatedAt is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise MoneyManagementConfigCorruptError("updatedAt is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MoneyManagementConfigCorruptError("updatedAt must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def normalize_small_account_symbol(value):
    """Normalize to the canonical KuCoin futures symbol; reject absence."""
    if value is None:
        raise ValueError("small_account_allowed_symbol is required")
    if not isinstance(value, str):
        raise TypeError("small_account_allowed_symbol must be a string")
    candidate = value.strip()
    if not candidate or candidate.upper() in _ABSENT_SYMBOL_VALUES:
        raise ValueError("small_account_allowed_symbol is not available")
    from backend.market.kucoin_futures_public import to_kucoin_futures_symbol

    normalized = to_kucoin_futures_symbol(candidate)
    if not isinstance(normalized, str):
        raise ValueError("small_account_allowed_symbol could not be normalized")
    normalized = normalized.strip().upper()
    if not normalized or normalized in _ABSENT_SYMBOL_VALUES:
        raise ValueError("small_account_allowed_symbol could not be normalized")
    return normalized


def validate_small_account_profile(config):
    """Fail closed unless the merged candidate matches the approved profile."""
    if not isinstance(config, MoneyManagementConfig):
        raise TypeError("MoneyManagementConfig required")
    if not config.small_account_minimum_contract_mode:
        return
    if (
        normalize_small_account_symbol(config.small_account_allowed_symbol)
        != APPROVED_SMALL_ACCOUNT_SYMBOL
    ):
        raise ValueError("small-account allowed symbol must resolve to XRPUSDTM")
    if config.small_account_max_contracts != APPROVED_SMALL_ACCOUNT_MAX_CONTRACTS:
        raise ValueError("small-account maximum contracts must equal 1")
    if (
        config.small_account_max_risk_percent
        > APPROVED_SMALL_ACCOUNT_MAX_RISK_PERCENT
    ):
        raise ValueError("small-account risk percent exceeds the approved profile")
    cap = config.small_account_max_absolute_risk_usdt
    if cap is None:
        raise ValueError("small-account absolute risk cap is required when enabled")
    if cap > APPROVED_SMALL_ACCOUNT_MAX_ABSOLUTE_RISK_USDT:
        raise ValueError("small-account absolute risk cap exceeds the approved profile")
    if config.small_account_max_leverage > APPROVED_SMALL_ACCOUNT_MAX_LEVERAGE:
        raise ValueError("small-account leverage exceeds the approved profile")
    for name in (
        "small_account_require_isolated",
        "small_account_require_flat_before_entry",
        "small_account_require_no_pending",
        "small_account_require_manual_selection",
    ):
        if getattr(config, name) is not True:
            raise ValueError(f"{name} must remain enabled for the approved profile")


def resolve_default_config_path():
    override = os.environ.get(CONFIG_PATH_ENVIRONMENT_VARIABLE)
    if override and override.strip():
        return Path(override.strip())
    return Path(__file__).resolve().parents[2].joinpath(*DEFAULT_CONFIG_RELATIVE_PATH)


@dataclass(frozen=True)
class MoneyManagementConfigState:
    config: MoneyManagementConfig
    config_revision: int
    updated_at: datetime

    def __post_init__(self):
        if not isinstance(self.config, MoneyManagementConfig):
            raise TypeError("config must be MoneyManagementConfig")
        if type(self.config_revision) is not int or self.config_revision < 1:
            raise ValueError("config_revision must be a positive integer")
        object.__setattr__(self, "updated_at", _utc(self.updated_at))


def _parse_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MoneyManagementConfigCorruptError(f"{name} must be a decimal string")
    if isinstance(value, str) and not value.strip():
        raise MoneyManagementConfigCorruptError(f"{name} must be a decimal string")
    try:
        result = Decimal(str(value).strip()) if isinstance(value, str) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise MoneyManagementConfigCorruptError(f"{name} is not a valid decimal") from exc
    if not result.is_finite():
        raise MoneyManagementConfigCorruptError(f"{name} must be finite")
    return result


def _parse_optional_decimal(name, value):
    if value is None:
        return None
    return _parse_decimal(name, value)


def _parse_boolean(name, value):
    if type(value) is not bool:
        raise MoneyManagementConfigCorruptError(f"{name} must be boolean")
    return value


def _parse_enum(name, enum_type, value):
    if not isinstance(value, str):
        raise MoneyManagementConfigCorruptError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise MoneyManagementConfigCorruptError(f"{name} is not a valid value") from exc


def _parse_symbol(name, value):
    try:
        return normalize_small_account_symbol(value)
    except (TypeError, ValueError) as exc:
        raise MoneyManagementConfigCorruptError(f"{name} is invalid") from exc


def _config_from_mapping(mapping):
    if not isinstance(mapping, dict):
        raise MoneyManagementConfigCorruptError("persisted config must be an object")
    keys = set(mapping)
    unknown = keys - _ALL_CONFIG_FIELDS
    if unknown:
        raise MoneyManagementConfigCorruptError("persisted config contains unknown fields")
    missing = _ALL_CONFIG_FIELDS - keys
    if missing:
        raise MoneyManagementConfigCorruptError("persisted config is missing required fields")
    values = {}
    for name, enum_type in _ENUM_FIELDS.items():
        values[name] = _parse_enum(name, enum_type, mapping[name])
    for name in _BOOLEAN_FIELDS:
        values[name] = _parse_boolean(name, mapping[name])
    for name in _REQUIRED_DECIMAL_FIELDS:
        values[name] = _parse_decimal(name, mapping[name])
    for name in _OPTIONAL_DECIMAL_FIELDS:
        values[name] = _parse_optional_decimal(name, mapping[name])
    for name in _STRING_FIELDS:
        values[name] = _parse_symbol(name, mapping[name])
    try:
        return MoneyManagementConfig(**values)
    except (TypeError, ValueError) as exc:
        raise MoneyManagementConfigCorruptError(
            "persisted configuration is invalid"
        ) from exc


def build_envelope(config, config_revision, updated_at):
    if not isinstance(config, MoneyManagementConfig):
        raise TypeError("MoneyManagementConfig required")
    if type(config_revision) is not int or config_revision < 1:
        raise ValueError("config_revision must be a positive integer")
    return {
        "schemaVersion": CONFIG_PERSISTENCE_SCHEMA_VERSION,
        "configRevision": config_revision,
        "updatedAt": _format_timestamp(updated_at),
        "config": config.to_dict(),
    }


def parse_envelope(envelope):
    if not isinstance(envelope, dict):
        raise MoneyManagementConfigCorruptError("persisted envelope must be an object")
    if envelope.get("schemaVersion") != CONFIG_PERSISTENCE_SCHEMA_VERSION:
        raise MoneyManagementConfigCorruptError("unsupported configuration schema version")
    revision = envelope.get("configRevision")
    if type(revision) is not int or revision < 1:
        raise MoneyManagementConfigCorruptError("configRevision must be a positive integer")
    updated_at = _parse_timestamp(envelope.get("updatedAt"))
    config = _config_from_mapping(envelope.get("config"))
    try:
        validate_small_account_profile(config)
    except ValueError as exc:
        raise MoneyManagementConfigCorruptError(
            "persisted small-account configuration is unsafe"
        ) from exc
    return MoneyManagementConfigState(config, revision, updated_at)


def _fsync_directory(directory):
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(str(directory), flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write(path, payload):
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MoneyManagementConfigPersistenceError(
            "configuration directory is unavailable"
        ) from exc
    descriptor = None
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".money-management-config-",
            suffix=".tmp",
            dir=str(directory),
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(path))
        temporary = None
    except OSError as exc:
        raise MoneyManagementConfigPersistenceError(
            "persisted configuration could not be written"
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    _fsync_directory(directory)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class MoneyManagementConfigStore:
    """Atomic, fail-closed durable store for the base MM configuration."""

    __slots__ = ("_path", "_timestamp_source")

    def __init__(self, path=None, timestamp_source=None):
        resolved = path if path is not None else resolve_default_config_path()
        self._path = Path(resolved)
        self._timestamp_source = timestamp_source or (
            lambda: datetime.now(timezone.utc)
        )
        if not callable(self._timestamp_source):
            raise TypeError("timestamp source must be callable")

    @property
    def path(self):
        return self._path

    def _now(self):
        return _utc(self._timestamp_source())

    def load(self):
        """Return persisted state, ``None`` when absent, or raise when unsafe."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            raise MoneyManagementConfigCorruptError(
                "persisted configuration could not be read"
            ) from exc
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise MoneyManagementConfigCorruptError(
                "persisted configuration is not valid JSON"
            ) from exc
        return parse_envelope(envelope)

    def save(self, config, config_revision):
        if not isinstance(config, MoneyManagementConfig):
            raise TypeError("MoneyManagementConfig required")
        if type(config_revision) is not int or config_revision < 1:
            raise ValueError("config_revision must be a positive integer")
        validate_small_account_profile(config)
        envelope = build_envelope(config, config_revision, self._now())
        payload = json.dumps(
            envelope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _atomic_write(self._path, payload)
        return self._path


def load_or_default_money_management_config(store=None, path=None, logger=None):
    """Load durable configuration, failing closed to canonical defaults."""
    if store is None:
        store = MoneyManagementConfigStore(path=path)
    try:
        state = store.load()
    except MoneyManagementConfigPersistenceError as exc:
        _safe_log(
            logger,
            "warning",
            "Money Management persisted configuration unusable: "
            f"{type(exc).__name__}",
        )
        state = None
    if state is None:
        from .loss_application_registration import build_default_money_management_config

        return build_default_money_management_config()
    return state.config


def _safe_log(logger, level, message):
    if logger is None:
        return
    log_method = getattr(logger, level, None)
    if callable(log_method):
        log_method(message)
