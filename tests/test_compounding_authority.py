from dataclasses import replace
from decimal import Decimal

import pytest

from backend.money_management.capital_eligibility import (
    build_capital_eligibility_contract,
    evaluate_market_capital_eligibility,
    resolve_compounding_capital_basis,
)
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.money_management.position_risk import calculate_risk_budget
from tests.test_ams_1a_market_scanner import NOW, metadata


D = Decimal


def config(enabled=False):
    return replace(
        build_default_money_management_config(),
        compounding_enabled=enabled,
    )


def authority(cfg, current):
    basis = resolve_compounding_capital_basis(cfg, current)
    budget = calculate_risk_budget(
        basis, cfg.risk_per_trade_pct, D("0"), D("0")
    )
    return build_capital_eligibility_contract(
        equity=current,
        available_capital=current,
        capital_basis=basis,
        risk_budget=budget.risk_budget_remaining,
        max_position_notional=D("1000"),
        total_exposure_percent=D("100"),
        open_exposure=D("0"),
        position_count=0,
        pending_order_count=0,
        mm_regime="NORMAL",
        policy_version="compounding/v1",
        evaluated_at=NOW,
        compounding_enabled=cfg.compounding_enabled,
    )


def test_default_off_uses_immutable_initial_reference_capital():
    cfg = config(False)
    assert cfg.compounding_enabled is False
    assert resolve_compounding_capital_basis(cfg, D("1200")) == D("1000")
    assert resolve_compounding_capital_basis(cfg, D("800")) == D("1000")


@pytest.mark.parametrize(
    ("current", "expected"),
    [("1200", "1200"), ("800", "800"), ("1000", "1000")],
)
def test_on_uses_current_capital_after_positive_negative_or_zero_result(
    current, expected
):
    assert resolve_compounding_capital_basis(
        config(True), D(current)
    ) == D(expected)


@pytest.mark.parametrize("invalid", [None, D("0"), D("-1"), D("NaN")])
def test_on_invalid_current_capital_fails_closed(invalid):
    assert resolve_compounding_capital_basis(config(True), invalid) is None


def test_capital_basis_changes_risk_budget_and_next_trade_quantity():
    off = authority(config(False), D("1200"))
    on = authority(config(True), D("1200"))
    assert off.capital_basis == D("1000")
    assert on.capital_basis == D("1200")
    assert off.risk_budget == D("5")
    assert on.risk_budget == D("6")

    item = metadata(
        last_price=D("1"),
        contract_multiplier=D("1"),
        quantity_step=D("0.01"),
        minimum_quantity=D("0.01"),
        minimum_notional=None,
    )
    off_size = evaluate_market_capital_eligibility(
        item, off, stop_loss_percent=D("10"),
        effective_cost_percent=D("0.1"), risk_percent=D("0.5"),
    )
    on_size = evaluate_market_capital_eligibility(
        item, on, stop_loss_percent=D("10"),
        effective_cost_percent=D("0.1"), risk_percent=D("0.5"),
    )
    assert off_size.approved_quantity_preview == D("49.50")
    assert on_size.approved_quantity_preview == D("59.40")


def test_finalized_result_only_changes_the_next_authorization():
    first_authority = authority(config(True), D("1000"))
    first = evaluate_market_capital_eligibility(
        metadata(last_price=D("1"), contract_multiplier=D("1"),
                 quantity_step=D("0.01"), minimum_quantity=D("0.01"),
                 minimum_notional=None),
        first_authority, stop_loss_percent=D("10"),
        effective_cost_percent=D("0.1"), risk_percent=D("0.5"),
    )
    authorized_quantity = first.approved_quantity_preview
    second_authority = authority(config(True), D("1100"))
    second = evaluate_market_capital_eligibility(
        metadata(last_price=D("1"), contract_multiplier=D("1"),
                 quantity_step=D("0.01"), minimum_quantity=D("0.01"),
                 minimum_notional=None),
        second_authority, stop_loss_percent=D("10"),
        effective_cost_percent=D("0.1"), risk_percent=D("0.5"),
    )
    assert first.approved_quantity_preview == authorized_quantity
    assert second.approved_quantity_preview > authorized_quantity


def test_compounding_policy_does_not_contain_real_order_authority():
    off = authority(config(False), D("1000")).to_dict()
    on = authority(config(True), D("1000")).to_dict()
    assert "realOrderAllowed" not in off
    assert "realOrderAllowed" not in on
