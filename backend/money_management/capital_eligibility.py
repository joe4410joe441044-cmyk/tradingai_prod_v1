"""MM-owned, read-only capital eligibility contracts consumed by AMS."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Tuple

from backend.market.kucoin_futures_public import FuturesContractMetadata

from .position_risk import PositionSizingInput, calculate_position_size


EXECUTABLE_MAX_CONCURRENT_POSITIONS = 1
METADATA_FUTURE_SKEW_TOLERANCE_SECONDS = 1


def _value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


@dataclass(frozen=True)
class CapitalEligibilityContract:
    capital_authority: str
    equity: Optional[Decimal]
    available_capital: Optional[Decimal]
    mm_mode: str
    mm_regime: str
    risk_budget: Optional[Decimal]
    max_position_notional: Optional[Decimal]
    total_exposure_percent: Optional[Decimal]
    max_total_exposure: Optional[Decimal]
    remaining_exposure: Optional[Decimal]
    theoretical_max_concurrent_positions: Optional[int]
    executable_max_concurrent_positions: int
    remaining_position_capacity: Optional[int]
    ruin_guard_status: str
    compounding_enabled: bool
    policy_version: str
    evaluated_at: datetime
    authority_fresh: bool
    execution_entry_allowed: bool
    capital_source: str = "UNSPECIFIED"
    input_authority: str = "UNSPECIFIED"
    capital_basis: Optional[Decimal] = None

    def to_dict(self):
        return {
            "capitalAuthority": self.capital_authority,
            "capitalSource": self.capital_source,
            "inputAuthority": self.input_authority,
            "equity": _value(self.equity),
            "availableCapital": _value(self.available_capital),
            "capitalBasis": _value(self.capital_basis),
            "mmMode": self.mm_mode,
            "mmRegime": self.mm_regime,
            "riskBudget": _value(self.risk_budget),
            "maxPositionNotional": _value(self.max_position_notional),
            "totalExposurePercent": _value(self.total_exposure_percent),
            "maxTotalExposure": _value(self.max_total_exposure),
            "remainingExposure": _value(self.remaining_exposure),
            "maxTotalExposureAmount": _value(self.max_total_exposure),
            "remainingExposureAmount": _value(self.remaining_exposure),
            "theoreticalMaxConcurrentPositions": self.theoretical_max_concurrent_positions,
            "executableMaxConcurrentPositions": self.executable_max_concurrent_positions,
            "remainingPositionCapacity": self.remaining_position_capacity,
            "ruinGuardStatus": self.ruin_guard_status,
            "compoundingEnabled": self.compounding_enabled,
            "policyVersion": self.policy_version,
            "evaluatedAt": _value(self.evaluated_at),
            "authorityFresh": self.authority_fresh,
            "executionEntryAllowed": self.execution_entry_allowed,
        }


def build_capital_eligibility_contract(
    *, equity, available_capital, risk_budget, max_position_notional,
    total_exposure_percent, open_exposure, position_count, pending_order_count,
    mm_regime, policy_version, evaluated_at, authority_fresh=True,
    execution_entry_allowed=True, capital_source="UNSPECIFIED",
    input_authority="UNSPECIFIED", compounding_enabled=False,
    capital_basis=None,
):
    if type(compounding_enabled) is not bool:
        raise TypeError("compounding_enabled must be bool")
    max_total = (
        equity * total_exposure_percent / Decimal("100")
        if equity is not None and total_exposure_percent is not None else None
    )
    remaining = (
        max(max_total - open_exposure, Decimal("0"))
        if max_total is not None and open_exposure is not None else None
    )
    theoretical = (
        int((max_total / max_position_notional).to_integral_value(rounding=ROUND_DOWN))
        if max_total is not None and max_position_notional is not None
        and max_position_notional > 0 else None
    )
    counts_known = (
        type(position_count) is int and position_count >= 0
        and type(pending_order_count) is int and pending_order_count >= 0
    )
    capacity = (
        max(EXECUTABLE_MAX_CONCURRENT_POSITIONS - position_count - pending_order_count, 0)
        if counts_known and authority_fresh else None
    )
    return CapitalEligibilityContract(
        "MONEY_MANAGEMENT", equity, available_capital, "MANUAL", mm_regime,
        risk_budget, max_position_notional, total_exposure_percent,
        max_total, remaining, theoretical,
        EXECUTABLE_MAX_CONCURRENT_POSITIONS, capacity, "UNAVAILABLE",
        compounding_enabled,
        policy_version, evaluated_at, bool(authority_fresh),
        bool(execution_entry_allowed and authority_fresh),
        capital_source, input_authority, capital_basis,
    )


def resolve_compounding_capital_basis(config, current_capital):
    """Apply the existing simulation rule to authoritative runtime capital."""
    from .models import MoneyManagementConfig
    if not isinstance(config, MoneyManagementConfig):
        return None
    if config.compounding_enabled:
        if (
            not isinstance(current_capital, Decimal)
            or not current_capital.is_finite()
            or current_capital <= 0
        ):
            return None
        return current_capital
    return config.initial_reference_equity


@dataclass(frozen=True)
class PerMarketEligibilityResult:
    symbol: str
    eligible: bool
    calculation_allowed: bool
    position_feasible: bool
    approved_quantity_preview: Optional[Decimal]
    reason_codes: Tuple[str, ...]
    capital_authority: str
    risk_budget: Optional[Decimal]
    remaining_exposure: Optional[Decimal]
    remaining_position_capacity: Optional[int]
    metadata_evaluated_at: datetime
    mm_evaluated_at: datetime

    def to_dict(self):
        return {
            "symbol": self.symbol, "eligible": self.eligible,
            "calculationAllowed": self.calculation_allowed,
            "positionFeasible": self.position_feasible,
            "approvedQuantityPreview": _value(self.approved_quantity_preview),
            "reasonCodes": list(self.reason_codes),
            "capitalAuthority": self.capital_authority,
            "riskBudget": _value(self.risk_budget),
            "remainingExposure": _value(self.remaining_exposure),
            "remainingPositionCapacity": self.remaining_position_capacity,
            "metadataEvaluatedAt": _value(self.metadata_evaluated_at),
            "mmEvaluatedAt": _value(self.mm_evaluated_at),
            "orderCreated": False,
            "sizingStage": "PRE_SELECTION_ELIGIBILITY",
        }


def evaluate_market_capital_eligibility(
    metadata, capital, *, stop_loss_percent, effective_cost_percent,
    risk_percent, evaluated_at, maximum_metadata_age_seconds=900,
):
    if not isinstance(metadata, FuturesContractMetadata):
        raise TypeError("FuturesContractMetadata required")
    if not isinstance(capital, CapitalEligibilityContract):
        raise TypeError("CapitalEligibilityContract required")
    if (
        not isinstance(evaluated_at, datetime)
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        raise TypeError("evaluated_at must be timezone-aware")
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    reasons = []
    metadata_age = evaluated_at - metadata.metadata_evaluated_at
    if (
        maximum_metadata_age_seconds <= 0
        or metadata_age.total_seconds()
        < -METADATA_FUTURE_SKEW_TOLERANCE_SECONDS
        or metadata_age.total_seconds() > maximum_metadata_age_seconds
    ):
        reasons.append("MARKET_METADATA_STALE")
    required_metadata = (
        metadata.contract_multiplier, metadata.quantity_step, metadata.minimum_quantity,
        metadata.last_price,
    )
    if not metadata.is_tradable:
        reasons.append("MARKET_NOT_TRADABLE")
    if any(value is None for value in required_metadata):
        reasons.append("MARKET_METADATA_INCOMPLETE")
    required_capital = (
        capital.available_capital, capital.capital_basis, capital.risk_budget,
        capital.max_position_notional, capital.remaining_exposure,
        capital.remaining_position_capacity,
    )
    if not capital.authority_fresh:
        reasons.append("CAPITAL_AUTHORITY_STALE")
    if not capital.execution_entry_allowed:
        reasons.append("MM_ENTRY_LOCKED")
    if any(value is None for value in required_capital):
        reasons.append("CAPITAL_AUTHORITY_INCOMPLETE")
    elif capital.remaining_position_capacity <= 0:
        reasons.append("POSITION_CAPACITY_EXHAUSTED")
    if reasons:
        return PerMarketEligibilityResult(
            metadata.canonical_symbol, False, False, False, None, tuple(reasons),
            capital.capital_authority, capital.risk_budget, capital.remaining_exposure,
            capital.remaining_position_capacity, metadata.metadata_evaluated_at,
            capital.evaluated_at,
        )
    result = calculate_position_size(PositionSizingInput(
        entry_price=metadata.last_price,
        stop_loss_percent=stop_loss_percent,
        effective_cost_percent=effective_cost_percent,
        risk_percent=risk_percent,
        risk_base_capital=capital.capital_basis,
        maximum_position_notional=capital.max_position_notional,
        total_exposure_remaining=capital.remaining_exposure,
        available_capital=capital.available_capital,
        quantity_step=metadata.quantity_step,
        contract_multiplier=metadata.contract_multiplier,
        risk_budget_remaining=capital.risk_budget,
    ))
    feasible = bool(
        result.calculation_allowed
        and result.position_quantity >= metadata.minimum_quantity
        and (metadata.minimum_notional is None or result.final_position_notional >= metadata.minimum_notional)
    )
    result_reasons = list(result.reasons)
    if not feasible:
        result_reasons.append("MINIMUM_ORDER_NOT_FEASIBLE")
    return PerMarketEligibilityResult(
        metadata.canonical_symbol, feasible, result.calculation_allowed, feasible,
        result.position_quantity, tuple(result_reasons), capital.capital_authority,
        capital.risk_budget, capital.remaining_exposure,
        capital.remaining_position_capacity, metadata.metadata_evaluated_at,
        capital.evaluated_at,
    )
