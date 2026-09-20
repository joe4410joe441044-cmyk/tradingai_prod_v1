"""Authoritative backend runtime configuration."""

import os


def _allow_live_from_environment() -> bool:
    """Enable the LIVE runtime only for the explicit value ``true``."""

    return os.getenv("ALLOW_LIVE", "").strip().lower() == "true"


def _trade_mode_from_environment() -> str:
    """Return a supported trade mode, failing closed to PAPER."""

    value = os.getenv("TRADE_MODE", "paper").strip().lower()
    return value if value in {"paper", "live"} else "paper"


def paper_manual_exit_grace_ms() -> int:
    """Acceptance-only PAPER manual-entry automatic-exit grace, in ms.

    Default ``0`` disables the grace entirely.  A positive value defers ONLY
    the strategy/microstructure automatic exit for MANUAL-origin PAPER
    positions while the position age is below the configured bound.  Unknown,
    missing or malformed values fail closed to ``0`` and LIVE is never
    affected.
    """

    raw = os.getenv("PAPER_MANUAL_EXIT_GRACE_MS", "0").strip()
    if not raw:
        return 0
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


ALLOW_LIVE = _allow_live_from_environment()
TRADE_MODE = _trade_mode_from_environment()
