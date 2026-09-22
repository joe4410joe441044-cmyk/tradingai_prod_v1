"""Shared linear-contract entry sizing. No order, lifecycle or persistence I/O.

Position size is requested fixed notional (zero selects risk sizing). MM caps
are independent limits. All quantities are normalized downward in contracts.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


class SizingRejected(ValueError):
    pass


def number(value, *, zero=False):
    if isinstance(value, bool) or value is None:
        raise SizingRejected("SIZING_AUTHORITY_UNAVAILABLE")
    try:
        result = Decimal(str(value))
    except Exception:
        raise SizingRejected("SIZING_AUTHORITY_INVALID") from None
    if not result.is_finite() or result < 0 or (not zero and result == 0):
        raise SizingRejected("SIZING_AUTHORITY_INVALID")
    return result


def floor_contracts(quantity, step):
    quantity, step = number(quantity, zero=True), number(step)
    return (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step


@dataclass(frozen=True)
class OrderSizingAuthority:
    symbol: str
    price: Decimal
    equity: Decimal
    available: Decimal
    risk_percent: Decimal
    sl_percent: Decimal
    leverage: Decimal
    fixed_notional: Decimal
    position_cap: Decimal
    symbol_capacity: Decimal
    total_capacity: Decimal
    multiplier: Decimal
    minimum: Decimal
    step: Decimal
    maximum: Decimal
    cost_percent: Decimal = Decimal("0")

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol:
            raise SizingRejected("SIZING_SYMBOL_UNAVAILABLE")
        for name in self.__dataclass_fields__:
            if name != "symbol":
                object.__setattr__(self, name, number(getattr(self, name), zero=name in {
                    "available", "fixed_notional", "symbol_capacity", "total_capacity", "cost_percent"
                }))
        if self.sl_percent > 100 or self.risk_percent > 100:
            raise SizingRejected("SIZING_AUTHORITY_INVALID")

    @property
    def risk_budget(self):
        return self.equity * self.risk_percent / 100

    @property
    def risk_fraction(self):
        return (self.sl_percent + self.cost_percent) / 100

    @property
    def notional_limit(self):
        return min(self.risk_budget / self.risk_fraction, self.position_cap,
                   self.symbol_capacity, self.total_capacity,
                   self.available * Decimal("0.8") * self.leverage)

    def validate(self, contracts, *, approved_base=None):
        contracts = number(contracts)
        if contracts < self.minimum or contracts > self.maximum or contracts % self.step:
            raise SizingRejected("NO_VALID_QUANTITY_FOR_EXCHANGE_CONSTRAINTS")
        base = contracts * self.multiplier
        if approved_base is not None and base > number(approved_base):
            raise SizingRejected("NORMALIZED_QUANTITY_EXCEEDS_APPROVAL")
        notional = base * self.price
        if notional * self.risk_fraction > self.risk_budget:
            raise SizingRejected("NO_VALID_QUANTITY_FOR_RISK_POLICY")
        if notional > min(self.position_cap, self.symbol_capacity, self.total_capacity):
            raise SizingRejected("NO_VALID_QUANTITY_FOR_MM_EXPOSURE")
        if notional / self.leverage > self.available * Decimal("0.8"):
            raise SizingRejected("NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN")
        if self.fixed_notional and notional > self.fixed_notional:
            raise SizingRejected("NORMALIZED_QUANTITY_EXCEEDS_FIXED_SIZE")
        return base, notional

    def size(self):
        # Fixed mode does not silently resize a request to fit risk/MM/margin.
        requested = self.fixed_notional or self.notional_limit
        if self.fixed_notional and requested / self.price / self.multiplier > self.maximum:
            raise SizingRejected("NO_VALID_QUANTITY_FOR_EXCHANGE_CONSTRAINTS")
        if self.fixed_notional and requested > self.notional_limit:
            if requested * self.risk_fraction > self.risk_budget:
                raise SizingRejected("NO_VALID_QUANTITY_FOR_RISK_POLICY")
            if requested > min(self.position_cap, self.symbol_capacity, self.total_capacity):
                raise SizingRejected("NO_VALID_QUANTITY_FOR_MM_EXPOSURE")
            raise SizingRejected("NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN")
        contracts = floor_contracts(min(requested / self.price / self.multiplier, self.maximum), self.step)
        if contracts < self.minimum:
            minimum_notional = self.minimum * self.multiplier * self.price
            if minimum_notional * self.risk_fraction > self.risk_budget:
                raise SizingRejected("NO_VALID_QUANTITY_FOR_RISK_POLICY")
            if minimum_notional > min(self.position_cap, self.symbol_capacity, self.total_capacity):
                raise SizingRejected("NO_VALID_QUANTITY_FOR_MM_EXPOSURE")
            if minimum_notional / self.leverage > self.available * Decimal("0.8"):
                raise SizingRejected("NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN")
            raise SizingRejected("NO_VALID_QUANTITY_FOR_EXCHANGE_CONSTRAINTS")
        base, notional = self.validate(contracts)
        return {"valid": True, "qty": float(base), "contracts": str(contracts),
                "position_size": float(notional), "required_margin": float(notional / self.leverage),
                "configured_position_size": float(self.fixed_notional),
                "risk_budget": float(self.risk_budget), "sl_risk": float(notional * self.sl_percent / 100),
                "sizing_mode": "fixed_position_size" if self.fixed_notional else "risk_percent"}
