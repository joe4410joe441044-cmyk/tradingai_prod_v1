"""MM-owned projection of the canonical PAPER account into capital eligibility."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .capital_eligibility import (
    build_capital_eligibility_contract,
    resolve_compounding_capital_basis,
)
from .models import MoneyManagementConfig
from .position_risk import calculate_risk_budget


def _decimal(value, *, nonnegative=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not result.is_finite() or (nonnegative and result < 0):
        return None
    return result


def _timestamp(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def build_paper_capital_eligibility(
    paper_state,
    *,
    config,
    policy_version,
    mm_evaluated_at=None,
    emergency_safe=True,
):
    """Use existing MM policy/calculations; unknown PAPER inputs fail closed.

    The canonical PAPER account (written by SET PAPER CAPITAL) is the sole
    source.  An unavailable PAPER balance never falls back to a live account.
    """
    if not isinstance(config, MoneyManagementConfig):
        raise RuntimeError("PAPER_MM_CONFIG_UNAVAILABLE")
    if not isinstance(policy_version, str) or not policy_version:
        raise RuntimeError("PAPER_MM_POLICY_UNAVAILABLE")
    if not isinstance(paper_state, dict) or paper_state.get("restoreReason"):
        raise RuntimeError("PAPER_ACCOUNT_UNAVAILABLE")

    equity = _decimal(paper_state.get("equity"), nonnegative=True)
    available_capital = _decimal(
        paper_state.get("availableBalance"), nonnegative=True
    )
    if equity is None or available_capital is None:
        raise RuntimeError("PAPER_ACCOUNT_CAPITAL_UNAVAILABLE")

    position_state = str(
        paper_state.get("positionState") or "UNKNOWN"
    ).strip().upper()
    pending_order = paper_state.get("pendingOrder") is True

    position_count = (
        0 if position_state == "FLAT"
        else 1 if position_state == "OPEN" else None
    )
    pending_count = 0 if not pending_order else None
    open_exposure = Decimal("0") if position_state == "FLAT" else None
    current_risk = Decimal("0") if position_state == "FLAT" else None
    reserved_risk = Decimal("0") if not pending_order else None

    capital_basis = resolve_compounding_capital_basis(config, available_capital)
    risk = calculate_risk_budget(
        capital_basis,
        config.risk_per_trade_pct,
        current_risk,
        reserved_risk,
    )
    updated_at = _timestamp(paper_state.get("updatedAt"))
    evaluated_at = mm_evaluated_at or updated_at or datetime.now(timezone.utc)
    authority_fresh = bool(
        updated_at is not None
        and equity is not None
        and available_capital is not None
        and open_exposure is not None
        and risk.risk_budget_remaining is not None
        and position_count is not None
        and pending_count is not None
    )
    entry_allowed = bool(
        authority_fresh
        and emergency_safe
        and position_state == "FLAT"
        and not pending_order
    )
    return build_capital_eligibility_contract(
        equity=equity,
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
        authority_fresh=authority_fresh,
        execution_entry_allowed=entry_allowed,
        capital_source="PAPER_ACCOUNT",
        input_authority="PAPER_ACCOUNT",
    )
