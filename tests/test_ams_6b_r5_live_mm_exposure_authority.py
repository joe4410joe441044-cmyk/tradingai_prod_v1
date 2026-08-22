from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import ExistingKucoinLiveAccountAuthority
from backend.money_management.live_capital_authority import build_live_capital_eligibility
from backend.money_management.capital_eligibility import evaluate_market_capital_eligibility
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from tests.test_ams_1a_market_scanner import metadata
from tests.test_ams_6b_r2_r1_live_account_hardening import Exchange, authority


NOW = datetime(2026, 8, 9, 6, tzinfo=timezone.utc)
CONFIG = build_default_money_management_config()


def live_contract(exchange=None, **changes):
    adapter = authority(exchange or Exchange(), **changes)
    snapshot = adapter.read()
    return snapshot, build_live_capital_eligibility(
        snapshot, config=CONFIG, policy_version="money-management-config/v1"
    )


def test_flat_none_uses_existing_mm_policy_and_primitives():
    snapshot, contract = live_contract()
    assert snapshot.source_authority == "REAL_LIVE_ACCOUNT"
    assert contract.capital_authority == "MONEY_MANAGEMENT"
    assert contract.capital_source == "REAL_LIVE_ACCOUNT"
    assert contract.input_authority == "REAL_LIVE_ACCOUNT"
    assert contract.compounding_enabled is False
    assert contract.capital_basis == Decimal("1000")
    assert contract.risk_budget == Decimal("5.00")
    assert contract.max_position_notional == Decimal("100")
    assert contract.total_exposure_percent == Decimal("20")
    assert contract.max_total_exposure == Decimal("200")
    assert contract.remaining_exposure == Decimal("200")
    assert contract.executable_max_concurrent_positions == 1
    assert contract.remaining_position_capacity == 1
    assert contract.ruin_guard_status == "UNAVAILABLE"
    assert contract.compounding_enabled is False
    assert contract.authority_fresh and contract.execution_entry_allowed


@pytest.mark.parametrize("exchange", [
    Exchange(positions={"qty": 1}),
    Exchange(positions=None),
    Exchange(orders={"success": True, "count": 1, "orders": [{}]}),
    Exchange(orders={"success": True, "orders": []}),
])
def test_open_pending_or_unknown_fail_closed(exchange):
    _, contract = live_contract(exchange)
    assert not contract.execution_entry_allowed
    if contract.authority_fresh:
        assert contract.remaining_position_capacity == 0
    else:
        assert contract.remaining_position_capacity is None


@pytest.mark.parametrize("changes", [
    {"mm_fresh": False},
    {"emergency_safe": False},
])
def test_mm_stale_or_emergency_unsafe_blocks(changes):
    snapshot = authority().read()
    contract = build_live_capital_eligibility(
        snapshot, config=CONFIG, policy_version="money-management-config/v1", **changes
    )
    assert not contract.execution_entry_allowed


def test_missing_config_and_policy_fail_closed():
    snapshot = authority().read()
    with pytest.raises(RuntimeError, match="LIVE_MM_CONFIG_UNAVAILABLE"):
        build_live_capital_eligibility(snapshot, config=None, policy_version="v1")
    with pytest.raises(RuntimeError, match="LIVE_MM_POLICY_UNAVAILABLE"):
        build_live_capital_eligibility(snapshot, config=CONFIG, policy_version="")


def test_existing_adapter_accepts_formal_mm_config():
    adapter = authority()
    contract = adapter.build_capital_eligibility(adapter.read(), policy=CONFIG)
    assert contract.capital_authority == "MONEY_MANAGEMENT"
    assert contract.execution_entry_allowed


def test_per_market_preview_reuses_existing_mm_position_sizing():
    _, capital = live_contract()
    market = metadata(metadata_evaluated_at=capital.evaluated_at)
    result = evaluate_market_capital_eligibility(
        market,
        capital,
        stop_loss_percent=Decimal("1"),
        effective_cost_percent=Decimal("0.1"),
        risk_percent=Decimal("0.5"),
    )
    assert result.calculation_allowed
    assert result.position_feasible
    assert result.approved_quantity_preview is not None
