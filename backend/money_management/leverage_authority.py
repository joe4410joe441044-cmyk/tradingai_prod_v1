"""Pure authoritative leverage resolution for the Operation START boundary.

Deterministic and side-effect-free: given the user-requested leverage and the
active Money Management maximum leverage, resolve the effective leverage that
Execution may consume.

Contract matches the MM sizing authority (`sizing.evaluate_sizing`): an
over-limit or invalid request is BLOCKED, not clamped.  If the authority is
unavailable or malformed, the resolution fails closed (requested leverage is
never used as its own authority).
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from .enums import RiskBlockReason


@dataclass(frozen=True)
class LeverageAuthorityResult:
    allowed: bool
    effective_leverage: Optional[Decimal]
    maximum_leverage: Optional[Decimal]
    block_reason: RiskBlockReason = RiskBlockReason.NONE

    def to_dict(self):
        return {
            "allowed": self.allowed,
            "effectiveLeverage": (
                format(self.effective_leverage, "f")
                if self.effective_leverage is not None
                else None
            ),
            "maximumLeverage": (
                format(self.maximum_leverage, "f")
                if self.maximum_leverage is not None
                else None
            ),
            "blockReason": self.block_reason.value,
        }


def _finite_decimal(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a Decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} invalid") from None
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    return number


def resolve_effective_leverage(requested_leverage, maximum_leverage):
    """Return the authoritative leverage an execution may use.

    - requested_leverage <= 0 or > maximum_leverage  -> BLOCK MAXIMUM_LEVERAGE
    - maximum_leverage unavailable / malformed        -> fail closed
    - otherwise                                        -> effective = requested
    """
    try:
        maximum = _finite_decimal(maximum_leverage, "maximum_leverage")
    except Exception:
        return LeverageAuthorityResult(
            False, None, None, RiskBlockReason.INSUFFICIENT_DATA
        )
    if maximum <= 0:
        return LeverageAuthorityResult(
            False, None, None, RiskBlockReason.INSUFFICIENT_DATA
        )
    try:
        requested = _finite_decimal(requested_leverage, "requested_leverage")
    except Exception:
        return LeverageAuthorityResult(
            False, None, maximum, RiskBlockReason.MAXIMUM_LEVERAGE
        )
    if requested <= 0:
        return LeverageAuthorityResult(
            False, None, maximum, RiskBlockReason.MAXIMUM_LEVERAGE
        )
    if requested > maximum:
        return LeverageAuthorityResult(
            False, None, maximum, RiskBlockReason.MAXIMUM_LEVERAGE
        )
    return LeverageAuthorityResult(True, requested, maximum, RiskBlockReason.NONE)
