"""Offline closure coverage for the Small Account fee/slippage/tick risk model."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from backend.money_management.config_persistence import (
    MoneyManagementConfigCorruptError,
    build_envelope,
    parse_envelope,
)
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.money_management.models import MoneyManagementConfig
from backend.money_management.order_sizing import OrderSizingAuthority, SizingRejected


def authority(**changes):
    values = dict(
        symbol="XRPUSDTM",
        price="1.18069",
        equity="7.90409697",
        available="7.90409697",
        risk_percent="0.5",
        sl_percent="1",
        leverage="3",
        fixed_notional="0",
        position_cap="100",
        symbol_capacity="0.790409697",
        total_capacity="1.580819394",
        multiplier="10",
        minimum="1",
        step="1",
        maximum="1000000",
        cost_percent="0.12",
        slippage_reserve_percent="0.05",
        tick_size="0.00001",
        small_account_mode=True,
        small_account_allowed_symbol="XRPUSDTM",
        small_account_max_contracts="1",
        small_account_max_risk_percent="2",
        small_account_max_absolute_risk_usdt="0.158",
        small_account_max_leverage="3",
        live=True,
        entry_authority="MANUAL",
        configured_symbol="XRPUSDTM",
        loop_enabled=False,
        position_flat=True,
        pending_known=True,
        pending=False,
        margin_mode_known=True,
        margin_mode="ISOLATED",
        margin_mode_compatible=True,
        leverage_explicit=True,
    )
    values.update(changes)
    return OrderSizingAuthority(**values)


def test_normal_policy_rejects_with_fee_and_slippage_breakdown():
    result = authority().size()
    assert result["sizingPolicyMode"] == "SMALL_ACCOUNT_MINIMUM_CONTRACT"
    assert result["feePercent"] == 0.12
    assert result["slippageReservePercent"] == 0.05
    assert result["slippagePercent"] == 0.1
    assert result["tickSize"] == 0.00001
    assert result["entryFeeUsdt"] == pytest.approx(0.00708414)
    assert result["exitFeeUsdt"] == pytest.approx(0.00708414)
    assert result["feeCostUsdt"] == pytest.approx(0.01416828)
    assert result["stopLossUsdt"] == pytest.approx(0.118069)
    assert result["slippageReserveUsdt"] == pytest.approx(0.0118069)
    assert result["tickRoundingRiskUsdt"] == pytest.approx(0.0001)
    assert result["totalEstimatedLossUsdt"] == pytest.approx(0.14414418)
    assert result["candidateRiskUsdt"] == pytest.approx(0.14414418)
    assert result["candidateRiskUsdt"] <= 0.158

    normal = replace(authority(), small_account_mode=False)
    with pytest.raises(SizingRejected, match="NO_VALID_QUANTITY_FOR_RISK_POLICY"):
        normal.size()


def test_slippage_reserve_is_configurable_and_cap_enforced():
    stress = authority(slippage_reserve_percent="0.10")
    assert stress.size()["candidateRiskUsdt"] == pytest.approx(0.15595108)
    assert stress.size()["candidateRiskUsdt"] <= 0.158

    over = authority(
        equity="8.0", available="8.0", slippage_reserve_percent="0.11"
    )
    with pytest.raises(SizingRejected, match="SMALL_ACCOUNT_ABSOLUTE_RISK_EXCEEDED"):
        over.size()


def test_tick_rounding_risk_is_included_once():
    without_tick = authority(tick_size="0")
    with_tick = authority(tick_size="0.00001")
    assert with_tick.size()["tickRoundingRiskUsdt"] == pytest.approx(0.0001)
    assert (
        with_tick.size()["totalEstimatedLossUsdt"]
        - without_tick.size()["totalEstimatedLossUsdt"]
    ) == pytest.approx(0.0001)


def test_invalid_slippage_reserve_fails_closed():
    with pytest.raises(SizingRejected, match="SIZING_SLIPPAGE_RESERVE_INVALID"):
        authority(slippage_reserve_percent="1.01")


def test_legacy_persisted_config_loads_with_conservative_slippage_default():
    config = build_default_money_management_config()
    envelope = build_envelope(config, 1, datetime.now(timezone.utc))
    legacy = parse_envelope(
        {**envelope, "config": {
            key: value
            for key, value in envelope["config"].items()
            if key != "slippage_reserve_percent"
        }}
    )
    assert legacy.config.slippage_reserve_percent == D("0.05")

    explicit = parse_envelope(
        {**envelope, "config": {
            **envelope["config"], "slippage_reserve_percent": "0"
        }}
    )
    assert explicit.config.slippage_reserve_percent == D("0")


def test_persisted_config_round_trips_slippage_reserve():
    config = replace(build_default_money_management_config(), slippage_reserve_percent=D("0.07"))
    envelope = build_envelope(config, 2, datetime.now(timezone.utc))
    loaded = parse_envelope(envelope)
    assert loaded.config.slippage_reserve_percent == D("0.07")


@pytest.mark.parametrize("value", ["-0.01", "1.01"])
def test_model_rejects_out_of_range_slippage_reserve(value):
    with pytest.raises((TypeError, ValueError)):
        replace(build_default_money_management_config(), slippage_reserve_percent=D(value))


def test_corrupt_slippage_reserve_fails_closed():
    config = build_default_money_management_config()
    envelope = build_envelope(config, 1, datetime.now(timezone.utc))
    with pytest.raises(MoneyManagementConfigCorruptError):
        parse_envelope(
            {**envelope, "config": {
                **envelope["config"], "slippage_reserve_percent": "not-a-number"
            }}
        )


def test_small_account_result_discloses_normal_risk_overrun_explicitly():
    result = authority().size()
    assert result["normalRiskBudgetUsdt"] == pytest.approx(0.03952048485)
    assert result["normalRiskBudgetExceeded"] is True
    assert result["normalRiskBudgetExcessUsdt"] == pytest.approx(0.10462369515)
    assert result["normalRiskBudgetMultiple"] == pytest.approx(
        result["totalEstimatedLossUsdt"] / result["normalRiskBudgetUsdt"]
    )
    assert result["normalRiskBudgetMultiple"] > 3.6
    assert result["normalSizingResult"] == "NO_VALID_QUANTITY_FOR_RISK_POLICY"
    assert result["smallAccountExceptionApplied"] is True
    assert result["smallAccountCapHeadroomUsdt"] == pytest.approx(0.01385582)


def test_normal_result_discloses_budget_is_within_normal_policy():
    result = authority(
        equity="1000", available="1000", position_cap="1000",
        symbol_capacity="1000", total_capacity="1000",
    ).size()
    assert result["sizingPolicyMode"] == "NORMAL_MM"
    assert result["normalRiskBudgetExceeded"] is False
    assert result["normalRiskBudgetExcessUsdt"] == 0


def test_total_estimated_loss_equals_components_without_double_counting():
    result = authority().size()
    components = (
        result["stopLossUsdt"]
        + result["feeCostUsdt"]
        + result["slippageReserveUsdt"]
        + result["tickRoundingRiskUsdt"]
    )
    assert result["totalEstimatedLossUsdt"] == pytest.approx(components, abs=1e-12)
    assert result["feeCostUsdt"] == pytest.approx(
        result["entryFeeUsdt"] + result["exitFeeUsdt"], abs=1e-12
    )
    assert result["entryFeeUsdt"] == pytest.approx(
        result["exitFeeUsdt"], abs=1e-12
    )


def test_explicit_zero_slippage_reserve_is_not_counted():
    result = authority(slippage_reserve_percent="0").size()
    assert result["slippageReserveUsdt"] == 0
    assert result["slippagePercent"] == 0
    assert result["totalEstimatedLossUsdt"] == pytest.approx(0.13233728)


def test_small_account_margin_ceiling_rejects_below_risk_caps():
    # Equity supports the 2% and absolute caps, but available margin cannot
    # fund the exchange-minimum contract. Risk caps must not mask this.
    with pytest.raises(
        SizingRejected, match="NO_VALID_QUANTITY_FOR_AVAILABLE_MARGIN"
    ):
        authority(equity="100", available="1").size()


@pytest.mark.parametrize("change", [
    {"price": "0"},
    {"leverage": "0"},
    {"multiplier": "0"},
    {"minimum": "0"},
    {"step": "0"},
    {"cost_percent": "-0.1"},
])
def test_invalid_sizing_metadata_fails_closed(change):
    with pytest.raises(SizingRejected):
        authority(**change)
