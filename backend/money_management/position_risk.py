"""Deterministic Money Management position sizing and risk-budget contracts."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Tuple


def _decimal(name, value, *, positive=False, nonnegative=False, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


@dataclass(frozen=True)
class PositionSizingInput:
    entry_price: Decimal
    stop_loss_percent: Decimal
    effective_cost_percent: Decimal
    risk_percent: Decimal
    risk_base_capital: Decimal
    maximum_position_notional: Decimal
    total_exposure_remaining: Decimal
    available_capital: Decimal
    quantity_step: Decimal
    contract_multiplier: Decimal
    risk_budget_remaining: Optional[Decimal] = None

    def __post_init__(self):
        for name in (
            "entry_price",
            "stop_loss_percent",
            "risk_percent",
            "risk_base_capital",
            "maximum_position_notional",
            "quantity_step",
            "contract_multiplier",
        ):
            _decimal(name, getattr(self, name), positive=True)
        for name in (
            "effective_cost_percent",
            "total_exposure_remaining",
            "available_capital",
        ):
            _decimal(name, getattr(self, name), nonnegative=True)
        _decimal(
            "risk_budget_remaining",
            self.risk_budget_remaining,
            nonnegative=True,
            optional=True,
        )
        if self.stop_loss_percent > 100 or self.risk_percent > 100:
            raise ValueError("percentage must not exceed 100")


@dataclass(frozen=True)
class PositionSizingResult:
    risk_amount: Decimal
    raw_position_notional: Decimal
    final_position_notional: Decimal
    position_quantity: Decimal
    applied_limits: Tuple[str, ...]
    calculation_allowed: bool
    reasons: Tuple[str, ...]

    def to_dict(self):
        return {
            "riskAmount": format(self.risk_amount, "f"),
            "rawPositionNotional": format(self.raw_position_notional, "f"),
            "finalPositionNotional": format(
                self.final_position_notional, "f"
            ),
            "positionQuantity": format(self.position_quantity, "f"),
            "appliedLimits": list(self.applied_limits),
            "calculationAllowed": self.calculation_allowed,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RiskBudgetSnapshot:
    risk_limit_amount: Optional[Decimal]
    current_risk_amount: Optional[Decimal]
    reserved_risk_amount: Optional[Decimal]
    risk_budget_remaining: Optional[Decimal]
    risk_utilization: Optional[Decimal]
    diagnostics: Tuple[str, ...]


def calculate_risk_budget(
    capital,
    risk_percent,
    current_risk_amount,
    reserved_risk_amount,
):
    capital = _decimal("capital", capital, nonnegative=True, optional=True)
    risk_percent = _decimal(
        "risk_percent", risk_percent, positive=True, optional=True
    )
    current = _decimal(
        "current_risk_amount",
        current_risk_amount,
        nonnegative=True,
        optional=True,
    )
    reserved = _decimal(
        "reserved_risk_amount",
        reserved_risk_amount,
        nonnegative=True,
        optional=True,
    )
    limit = (
        capital * risk_percent / Decimal("100")
        if capital is not None and risk_percent is not None
        else None
    )
    diagnostics = []
    if limit is None:
        diagnostics.append("RISK_LIMIT_UNAVAILABLE")
    if current is None:
        diagnostics.append("CURRENT_POSITION_RISK_UNAVAILABLE")
    if reserved is None:
        diagnostics.append("RESERVED_RISK_UNAVAILABLE")
    if limit is None or current is None or reserved is None:
        diagnostics.append("RISK_UTILIZATION_UNAVAILABLE")
        return RiskBudgetSnapshot(
            limit, current, reserved, None, None, tuple(diagnostics)
        )
    used = current + reserved
    remaining = max(limit - used, Decimal("0"))
    utilization = (
        used / limit * Decimal("100") if limit > 0 else None
    )
    if utilization is None:
        diagnostics.append("RISK_UTILIZATION_UNAVAILABLE")
    return RiskBudgetSnapshot(
        limit, current, reserved, remaining, utilization, tuple(diagnostics)
    )


def calculate_position_size(value):
    if not isinstance(value, PositionSizingInput):
        raise TypeError("PositionSizingInput required")
    effective_risk_percent = (
        value.stop_loss_percent + value.effective_cost_percent
    )
    risk_amount = (
        value.risk_base_capital * value.risk_percent / Decimal("100")
    )
    raw_notional = (
        risk_amount / effective_risk_percent * Decimal("100")
    )
    risk_budget_notional = (
        value.risk_budget_remaining
        / effective_risk_percent
        * Decimal("100")
        if value.risk_budget_remaining is not None
        else None
    )
    limits = (
        ("MAXIMUM_POSITION_NOTIONAL", value.maximum_position_notional),
        ("TOTAL_EXPOSURE_REMAINING", value.total_exposure_remaining),
        ("AVAILABLE_CAPITAL", value.available_capital),
    ) + (
        (("RISK_BUDGET_REMAINING", risk_budget_notional),)
        if risk_budget_notional is not None
        else ()
    )
    final_notional = min(raw_notional, *(amount for _, amount in limits))
    applied = tuple(
        name for name, amount in limits if amount == final_notional
        and final_notional < raw_notional
    )
    raw_quantity = (
        final_notional / value.entry_price / value.contract_multiplier
    )
    steps = (raw_quantity / value.quantity_step).to_integral_value(
        rounding=ROUND_DOWN
    )
    quantity = steps * value.quantity_step
    rounded_notional = (
        quantity * value.contract_multiplier * value.entry_price
    )
    if quantity <= 0:
        return PositionSizingResult(
            risk_amount,
            raw_notional,
            Decimal("0"),
            Decimal("0"),
            applied,
            False,
            ("POSITION_SIZE_ZERO",),
        )
    return PositionSizingResult(
        risk_amount,
        raw_notional,
        rounded_notional,
        quantity,
        applied,
        True,
        (),
    )
