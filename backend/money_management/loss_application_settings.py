"""MM-4G strict settings resolution; no settings are read at import time."""
import os
from pathlib import Path

from .loss_application_models import LossLimitApplicationConfiguration


class LossLimitApplicationSettingsError(ValueError):
    pass


def _value(source, name, default=None):
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _strict_bool(value, name, default):
    if value is None:
        return default
    if type(value) is bool:
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    raise LossLimitApplicationSettingsError(f"{name} must be a strict boolean")


def resolve_loss_limit_application_configuration(
    settings=None, environ=None, repository_root=None
):
    source = settings if settings is not None else (environ if environ is not None else os.environ)
    enabled = _strict_bool(
        _value(source, "MONEY_MANAGEMENT_ENABLED"),
        "MONEY_MANAGEMENT_ENABLED",
        False,
    )
    if not enabled:
        return LossLimitApplicationConfiguration()
    persistence_enabled = _strict_bool(
        _value(source, "MONEY_MANAGEMENT_PERSISTENCE_ENABLED"),
        "MONEY_MANAGEMENT_PERSISTENCE_ENABLED",
        False,
    )
    raw_path = _value(source, "MONEY_MANAGEMENT_PERSISTENCE_PATH")
    if not persistence_enabled or not isinstance(raw_path, str) or not raw_path.strip():
        raise LossLimitApplicationSettingsError("persistence configuration invalid")
    path = Path(raw_path)
    if not path.is_absolute():
        raise LossLimitApplicationSettingsError("persistence path must be absolute")
    root = (
        Path(repository_root)
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    allowed_root = (root / "logs" / "runtime").resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(allowed_root)
    except (OSError, ValueError):
        raise LossLimitApplicationSettingsError("persistence path is outside runtime data")
    return LossLimitApplicationConfiguration(
        enabled=True,
        persistence_enabled=True,
        persistence_path=resolved,
    )
