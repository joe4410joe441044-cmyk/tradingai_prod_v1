"""Authoritative backend runtime configuration."""

import os


def _allow_live_from_environment() -> bool:
    """Enable the LIVE runtime only for the explicit value ``true``."""

    return os.getenv("ALLOW_LIVE", "").strip().lower() == "true"


def _trade_mode_from_environment() -> str:
    """Return a supported trade mode, failing closed to PAPER."""

    value = os.getenv("TRADE_MODE", "paper").strip().lower()
    return value if value in {"paper", "live"} else "paper"


ALLOW_LIVE = _allow_live_from_environment()
TRADE_MODE = _trade_mode_from_environment()
