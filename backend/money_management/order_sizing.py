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


# The single canonical available-margin buffer. Execution order sizing and AMS
# pre-selection eligibility both bound a candidate by this ratio so the two
# authorities can never diverge on affordability.
MARGIN_BUFFER_RATIO = Decimal("0.8")


def margin_limited_notional(available, leverage):
    """Canonical notional ceiling implied by available margin and leverage.

    ``available_capital * MARGIN_BUFFER_RATIO * effective_leverage``. This is
    the exact calculation Execution applies in ``OrderSizingAuthority`` and the
    same primitive AMS capital eligibility must reuse (no second margin policy).
    """
    return (
        number(available, zero=True)
        * MARGIN_BUFFER_RATIO
        * number(leverage)
    )


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
    small_account_mode: bool = False
    small_account_allowed_symbol: str = ""
    small_account_max_contracts: Decimal = Decimal("1")
    small_account_max_risk_percent: Decimal = Decimal("2")
    small_account_max_absolute_risk_usdt: Decimal = Decimal("0")
    small_account_max_leverage: Decimal = Decimal("3")
    live: bool = False
    entry_authority: str = ""
    configured_symbol: str = ""
    loop_enabled: bool = False
    position_flat: bool = False
    pending_known: bool = False
    pending: bool = True
    margin_mode_known: bool = False
    margin_mode: str = "UNKNOWN"
    margin_mode_compatible: bool = False
    leverage_explicit: bool = False

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol:
            raise SizingRejected("SIZING_SYMBOL_UNAVAILABLE")
        for name in self.__dataclass_fields__:
            if name in {"price","equity","available","risk_percent","sl_percent","leverage","fixed_notional","position_cap","symbol_capacity","total_capacity","multiplier","minimum","step","maximum","cost_percent","small_account_max_contracts","small_account_max_risk_percent","small_account_max_absolute_risk_usdt","small_account_max_leverage"}:
                object.__setattr__(self, name, number(getattr(self, name), zero=name in {
                    "available", "fixed_notional", "symbol_capacity", "total_capacity", "cost_percent", "small_account_max_absolute_risk_usdt"
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
                   margin_limited_notional(self.available, self.leverage))

    def validate(self, contracts, *, approved_base=None, sizing_policy_mode="NORMAL_MM"):
        contracts = number(contracts)
        if contracts < self.minimum or contracts > self.maximum or contracts % self.step:
            raise SizingRejected("NO_VALID_QUANTITY_FOR_EXCHANGE_CONSTRAINTS")
        base = contracts * self.multiplier
        if approved_base is not None and base > number(approved_base):
            raise SizingRejected("NORMALIZED_QUANTITY_EXCEEDS_APPROVAL")
        notional = base * self.price
        if sizing_policy_mode not in {"NORMAL_MM", "SMALL_ACCOUNT_MINIMUM_CONTRACT"}:
            raise SizingRejected("SIZING_POLICY_MODE_UNKNOWN")
        if sizing_policy_mode == "SMALL_ACCOUNT_MINIMUM_CONTRACT":
            self._validate_small_account_candidate(contracts, notional)
            return base, notional
        if notional * self.risk_fraction > self.risk_budget:
            raise SizingRejected("NO_VALID_QUANTITY_FOR_RISK_POLICY")
        if notional > min(self.position_cap, self.symbol_capacity, self.total_capacity):
            raise SizingRejected("NO_VALID_QUANTITY_FOR_MM_EXPOSURE")
        if notional > margin_limited_notional(self.available, self.leverage):
            raise SizingRejected("NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN")
        if self.fixed_notional and notional > self.fixed_notional:
            raise SizingRejected("NORMALIZED_QUANTITY_EXCEEDS_FIXED_SIZE")
        return base, notional

    def _normal_size(self):
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
            if minimum_notional > margin_limited_notional(self.available, self.leverage):
                raise SizingRejected("NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN")
            raise SizingRejected("NO_VALID_QUANTITY_FOR_EXCHANGE_CONSTRAINTS")
        base, notional = self.validate(contracts)
        return {"valid": True, "qty": float(base), "contracts": str(contracts),
                "position_size": float(notional), "required_margin": float(notional / self.leverage),
                "configured_position_size": float(self.fixed_notional),
                "risk_budget": float(self.risk_budget), "sl_risk": float(notional * self.sl_percent / 100),
                "sizing_mode": "fixed_position_size" if self.fixed_notional else "risk_percent",
                "sizingPolicyMode": "NORMAL_MM", "smallAccountExceptionApplied": False,
                "normalExposureGateResult": "PASS", "smallAccountFloorDecision": "NOT_EVALUATED"}

    def _validate_small_account_candidate(self, contracts, notional):
        checks = (
            (self.small_account_mode, "SMALL_ACCOUNT_MODE_OFF"),
            (self.live, "SMALL_ACCOUNT_REQUIRES_LIVE"),
            (self.entry_authority == "MANUAL", "SMALL_ACCOUNT_REQUIRES_MANUAL"),
            (not self.loop_enabled, "SMALL_ACCOUNT_LOOP_BLOCKED"),
            (self.symbol == self.small_account_allowed_symbol == self.configured_symbol, "SMALL_ACCOUNT_SYMBOL_MISMATCH"),
            (contracts == self.minimum, "SMALL_ACCOUNT_REQUIRES_EXCHANGE_MINIMUM"),
            (contracts <= self.small_account_max_contracts, "SMALL_ACCOUNT_HARD_CAP_EXCEEDED"),
            (self.position_flat, "SMALL_ACCOUNT_REQUIRES_FLAT"),
            (self.pending_known and not self.pending, "SMALL_ACCOUNT_PENDING_UNSAFE"),
            (self.margin_mode_known and self.margin_mode == "ISOLATED" and self.margin_mode_compatible, "SMALL_ACCOUNT_REQUIRES_ISOLATED"),
            (self.leverage_explicit, "SMALL_ACCOUNT_LEVERAGE_UNKNOWN"),
            (self.leverage <= self.small_account_max_leverage, "SMALL_ACCOUNT_LEVERAGE_EXCEEDED"),
        )
        for allowed, reason in checks:
            if not allowed:
                raise SizingRejected(reason)
        risk = notional * self.risk_fraction
        if risk > self.equity * self.small_account_max_risk_percent / 100:
            raise SizingRejected("SMALL_ACCOUNT_RISK_PERCENT_EXCEEDED")
        if self.small_account_max_absolute_risk_usdt <= 0 or risk > self.small_account_max_absolute_risk_usdt:
            raise SizingRejected("SMALL_ACCOUNT_ABSOLUTE_RISK_EXCEEDED")
        if notional > margin_limited_notional(self.available, self.leverage):
            raise SizingRejected("NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN")

    def size(self):
        try:
            return self._normal_size()
        except SizingRejected as normal_error:
            normal_reason = str(normal_error)
            if not self.small_account_mode:
                raise
        contracts = self.minimum
        notional = contracts * self.multiplier * self.price
        self._validate_small_account_candidate(contracts, notional)
        base = contracts * self.multiplier
        risk = notional * self.risk_fraction
        return {"valid": True, "qty": float(base), "contracts": str(contracts),
                "position_size": float(notional), "required_margin": float(notional / self.leverage),
                "configured_position_size": float(self.fixed_notional), "risk_budget": float(self.risk_budget),
                "sl_risk": float(notional * self.sl_percent / 100), "sizing_mode": "minimum_contract_floor",
                "sizingPolicyMode": "SMALL_ACCOUNT_MINIMUM_CONTRACT", "smallAccountExceptionApplied": True,
                "smallAccountReason": "NORMAL_MM_BELOW_EXCHANGE_MINIMUM", "normalSizingResult": normal_reason,
                "normalExposureGateResult": normal_reason, "smallAccountFloorDecision": "ALLOW",
                "candidateContracts": str(contracts), "candidateBaseQuantity": float(base),
                "candidateNotionalUsdt": float(notional), "candidateRiskUsdt": float(risk),
                "candidateRiskPercent": float(risk / self.equity * 100), "effectiveLeverage": float(self.leverage)}
