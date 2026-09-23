"""Canonical risk-per-trade percent authority (WORK AA).

Money Management risk_per_trade_pct is the single authority for risk
percent consumed by START, AMS executability, and STOPPED status display.
This module never invents 0.5 or 1.0 as repair values.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Mapping, Optional


class RiskPercentAuthorityError(ValueError):
    """Fail-closed risk authority error with stable uppercase reason."""


def resolve_risk_percent_authority(
    config: Optional[Mapping[str, Any]],
    mm_config: Any,
) -> float:
    """Return canonical MM risk percent; reject payload mismatch."""
    canonical = (
        getattr(mm_config, "risk_per_trade_pct", None)
        if mm_config is not None
        else None
    )
    if canonical is None:
        raise RiskPercentAuthorityError(
            "MONEY_MANAGEMENT_RISK_PER_TRADE_UNAVAILABLE"
        )
    try:
        canonical_float = float(canonical)
    except (TypeError, ValueError) as exc:
        raise RiskPercentAuthorityError(
            "MONEY_MANAGEMENT_RISK_PER_TRADE_INVALID"
        ) from exc
    if not (canonical_float > 0 and math.isfinite(canonical_float)):
        raise RiskPercentAuthorityError(
            "MONEY_MANAGEMENT_RISK_PER_TRADE_INVALID"
        )
    if config is not None:
        payload_value = config.get("risk_percent")
        if payload_value is not None:
            try:
                payload_float = float(payload_value)
            except (TypeError, ValueError) as exc:
                raise RiskPercentAuthorityError(
                    "RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL"
                ) from exc
            if not math.isclose(
                payload_float,
                canonical_float,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise RiskPercentAuthorityError(
                    "RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL"
                )
    return canonical_float


def resolve_executability_risk_percent(
    *,
    config: Mapping[str, Any],
    mm_config: Any,
    live_runtime: bool,
    legacy_default: str = "0.5",
) -> Decimal:
    """MM-first risk for AMS executability; legacy default only pre-LIVE."""
    mm_risk = (
        getattr(mm_config, "risk_per_trade_pct", None)
        if mm_config is not None
        else None
    )
    if mm_risk is not None:
        try:
            risk_percent = Decimal(str(mm_risk))
        except Exception as exc:
            raise RuntimeError("AUTO_EXECUTABILITY_RISK_PERCENT_INVALID") from exc
        if not risk_percent.is_finite() or risk_percent <= 0:
            raise RuntimeError("AUTO_EXECUTABILITY_RISK_PERCENT_INVALID")
        config_risk = config.get("risk_percent")
        if config_risk is not None and live_runtime:
            try:
                config_decimal = Decimal(str(config_risk))
            except Exception as exc:
                raise RuntimeError(
                    "AUTO_EXECUTABILITY_RISK_PERCENT_INVALID"
                ) from exc
            if config_decimal != risk_percent:
                raise RuntimeError(
                    "AUTO_EXECUTABILITY_RISK_PERCENT_MISMATCH_MM"
                )
        return risk_percent

    value = config.get("risk_percent")
    if value is None:
        if live_runtime:
            raise RuntimeError("AUTO_EXECUTABILITY_RISK_PERCENT_UNAVAILABLE")
        value = legacy_default
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise RuntimeError("AUTO_EXECUTABILITY_RISK_PERCENT_INVALID") from exc
    if not number.is_finite() or number <= 0:
        raise RuntimeError("AUTO_EXECUTABILITY_RISK_PERCENT_INVALID")
    return number


def status_risk_percent_authority(
    *,
    engine_risk_percent: Any,
    mm_config: Any,
    running: bool,
) -> Optional[dict]:
    """STOPPED prefers MM; RUNNING prefers started engine config."""
    mm_risk = (
        getattr(mm_config, "risk_per_trade_pct", None)
        if mm_config is not None
        else None
    )
    if mm_risk is None:
        if engine_risk_percent is None:
            return None
        return {
            "value": engine_risk_percent,
            "source": "ENGINE_OR_LAST_START",
        }
    try:
        mm_float = float(mm_risk)
    except (TypeError, ValueError):
        return None
    if running and engine_risk_percent is not None:
        return {
            "value": engine_risk_percent,
            "source": "RUNTIME_ENGINE",
        }
    return {
        "value": mm_float,
        "source": "MONEY_MANAGEMENT",
    }
