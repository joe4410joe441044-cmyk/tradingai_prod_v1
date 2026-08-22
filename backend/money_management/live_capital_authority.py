"""MM-owned projection of Real Live account input into capital eligibility."""

from datetime import datetime, timezone
from decimal import Decimal

from .capital_eligibility import (
    build_capital_eligibility_contract,
    resolve_compounding_capital_basis,
)
from .models import MoneyManagementConfig
from .position_risk import calculate_risk_budget


def build_live_capital_eligibility(
    snapshot,
    *,
    config,
    policy_version,
    mm_evaluated_at=None,
    mm_fresh=True,
    emergency_safe=True,
):
    """Use existing MM policy/calculations; unknown Live inputs fail closed."""
    if not isinstance(config, MoneyManagementConfig):
        raise RuntimeError("LIVE_MM_CONFIG_UNAVAILABLE")
    if not isinstance(policy_version, str) or not policy_version:
        raise RuntimeError("LIVE_MM_POLICY_UNAVAILABLE")
    evaluated_at = mm_evaluated_at or getattr(snapshot, "evaluated_at", None)
    if (
        not isinstance(evaluated_at, datetime)
        or evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
    ):
        raise RuntimeError("LIVE_MM_EVALUATED_AT_UNAVAILABLE")
    evaluated_at = evaluated_at.astimezone(timezone.utc)

    real_source = getattr(snapshot, "source_authority", None) == "REAL_LIVE_ACCOUNT"
    authority_fresh = bool(
        real_source and getattr(snapshot, "authority_fresh", False) and mm_fresh
    )
    position_state = getattr(snapshot, "open_position_state", "UNKNOWN")
    pending_state = getattr(snapshot, "pending_order_state", "UNKNOWN")

    position_count = 0 if position_state == "FLAT" else 1 if position_state == "OPEN" else None
    pending_count = 0 if pending_state == "NONE" else getattr(
        snapshot, "pending_order_count", None
    ) if pending_state == "EXISTS" else None

    # A validated FLAT snapshot authoritatively proves zero open exposure.
    # OPEN exposure must be supplied by the Live position authority; MM never
    # guesses contract notional from quantity alone.
    open_exposure = (
        Decimal("0") if position_state == "FLAT"
        else getattr(snapshot, "current_exposure", None)
        if position_state == "OPEN" else None
    )
    current_risk = Decimal("0") if position_state == "FLAT" else None
    reserved_risk = Decimal("0") if pending_state == "NONE" else None
    available_capital = getattr(snapshot, "available_capital", None)
    capital_basis = resolve_compounding_capital_basis(
        config, available_capital
    )
    risk = calculate_risk_budget(
        capital_basis,
        config.risk_per_trade_pct,
        current_risk,
        reserved_risk,
    )
    complete = bool(
        authority_fresh
        and open_exposure is not None
        and risk.risk_budget_remaining is not None
        and position_count is not None
        and pending_count is not None
    )
    entry_allowed = bool(
        complete
        and emergency_safe
        and position_state == "FLAT"
        and pending_state == "NONE"
    )
    return build_capital_eligibility_contract(
        equity=getattr(snapshot, "equity", None),
        available_capital=available_capital,
        capital_basis=capital_basis,
        compounding_enabled=config.compounding_enabled,
        risk_budget=risk.risk_budget_remaining,
        max_position_notional=config.maximum_position_notional,
        total_exposure_percent=config.total_exposure_pct,
        open_exposure=open_exposure,
        position_count=position_count,
        pending_order_count=pending_count,
        mm_regime=config.profile.value,
        policy_version=policy_version,
        evaluated_at=evaluated_at,
        authority_fresh=complete,
        execution_entry_allowed=entry_allowed,
        capital_source="REAL_LIVE_ACCOUNT",
        input_authority="REAL_LIVE_ACCOUNT",
    )
