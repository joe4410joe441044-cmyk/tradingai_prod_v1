"""WORK AA final parity: AMS pre-selection margin/leverage must match Execution.

Fully isolated: no network, no authenticated exchange calls, no bot start and
no order creation.  These tests prove the canonical available-margin ceiling
(``available * 0.8 * effective_leverage``) is shared by Execution order sizing
and AMS capital eligibility, that the LIVE read-only authority fails closed on
unknown leverage, and that the calibration harness / mapping-policy contract
supply every required capital input.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import LiveReadOnlyValidation
from backend.market.kucoin_futures_public import (
    FuturesContractMetadata, KucoinFuturesPublicClient,
)
from backend.money_management.capital_eligibility import (
    build_capital_eligibility_contract,
    evaluate_market_capital_eligibility,
)
from backend.money_management.order_sizing import (
    MARGIN_BUFFER_RATIO, OrderSizingAuthority, margin_limited_notional,
)
from scripts.ams_6b_live_calibration import (
    SYNTHETIC_CAPITAL_BASIS, SYNTHETIC_EFFECTIVE_LEVERAGE,
    SYNTHETIC_SINGLE_SYMBOL_EXPOSURE_PERCENT, fixed_market_only_capital,
)
from tests.test_ams_0d_foundation import Session
from tests.test_ams_6b_r2_r1_live_account_hardening import (
    Exchange, POLICY, authority as live_authority,
)


D = Decimal
NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


def meta(
    *, symbol="TESTUSDT", exchange_symbol="TESTUSDTM", multiplier="1",
    step="1", minimum="1", price="1", minimum_notional=None, evaluated_at=NOW,
):
    return FuturesContractMetadata(
        symbol, exchange_symbol, "TEST", "USDT", "USDT", "FFWCSX", "Open",
        D(multiplier), D(step), D(minimum),
        None if minimum_notional is None else D(minimum_notional),
        D("0.1"), D("0.0002"), D("0.0006"), D("100"),
        {"initialMargin": D("0.01")}, D(price), evaluated_at,
    )


def capital(
    *, equity="1000", available="100", basis="1000", risk_budget="100000",
    max_position_notional="100000", total_pct="100", single_pct="100",
    open_exposure="0",
):
    return build_capital_eligibility_contract(
        equity=D(equity), available_capital=D(available), capital_basis=D(basis),
        risk_budget=D(risk_budget), max_position_notional=D(max_position_notional),
        total_exposure_percent=D(total_pct),
        single_symbol_exposure_percent=D(single_pct),
        open_exposure=D(open_exposure), position_count=0, pending_order_count=0,
        mm_regime="NORMAL", policy_version="test/v1", evaluated_at=NOW,
        authority_fresh=True, execution_entry_allowed=True,
    )


def ams(market, authority, *, leverage="1", risk="0.5", sl="1", cost="0.1"):
    return evaluate_market_capital_eligibility(
        market, authority, stop_loss_percent=D(sl),
        effective_cost_percent=D(cost), risk_percent=D(risk),
        effective_leverage=D(leverage),
        evaluated_at=market.metadata_evaluated_at,
    )


# A. Margin ceiling uses the canonical 80% buffer at explicit 1x.
def test_margin_ceiling_uses_canonical_buffer_at_1x():
    assert MARGIN_BUFFER_RATIO == D("0.8")
    assert margin_limited_notional(D("100"), D("1")) == D("80")

    result = ams(meta(), capital(available="100"), leverage="1")

    assert result.execution_quantity_valid is True
    assert D(result.approved_position_notional) == D("80")
    assert D(result.approved_quantity_preview) == D("80")


# B. Leverage scales the same canonical margin ceiling.
def test_margin_ceiling_scales_with_effective_leverage():
    assert margin_limited_notional(D("100"), D("3")) == D("240")

    result = ams(meta(), capital(available="100"), leverage="3")

    assert result.execution_quantity_valid is True
    assert D(result.approved_position_notional) == D("240")
    assert D(result.approved_quantity_preview) == D("240")


# C. A tighter risk cap still wins over the margin ceiling.
def test_risk_cap_tighter_than_margin_wins():
    result = ams(
        meta(), capital(available="100", risk_budget="1"), leverage="3",
    )

    margin_ceiling = margin_limited_notional(D("100"), D("3"))
    assert D(result.approved_position_notional) == D("90")
    assert D(result.approved_position_notional) < margin_ceiling


# D. A tighter single-symbol exposure cap still wins over the margin ceiling.
def test_exposure_cap_tighter_than_margin_wins():
    result = ams(
        meta(), capital(available="100", single_pct="15"), leverage="3",
    )

    margin_ceiling = margin_limited_notional(D("100"), D("3"))
    assert D(result.approved_position_notional) == D("150")
    assert D(result.approved_position_notional) < margin_ceiling


def _public_client():
    return KucoinFuturesPublicClient(session=Session([]), timeout=2)


def _live_validation(**changes):
    values = dict(
        capital_provider=lambda: capital(),
        active_symbol_provider=lambda: None,
        safety_provider=lambda: {
            "realOrderAllowed": False, "dryRun": True,
            "executionRealOrderDisabled": True, "autoTradeDisabled": True,
            "liveAutoSwitchDisabled": True, "emergencyAvailable": True,
            "governanceAvailable": True,
        },
        position_provider=lambda: "FLAT",
        pending_order_provider=lambda: False,
        emergency_provider=lambda: True,
        clock=lambda: NOW,
    )
    values.update(changes)
    return LiveReadOnlyValidation(_public_client(), **values)


# E. LIVE unknown leverage fails closed with an explicit reason.
def test_live_missing_authoritative_leverage_fails_closed():
    with pytest.raises(RuntimeError, match="LEVERAGE_AUTHORITY_UNAVAILABLE"):
        _live_validation()
    with pytest.raises(RuntimeError, match="LEVERAGE_AUTHORITY_UNAVAILABLE"):
        _live_validation(effective_leverage=None)


@pytest.mark.parametrize("value", [D("0"), D("-1"), D("NaN"), 1, "1"])
def test_live_invalid_authoritative_leverage_fails_closed(value):
    with pytest.raises(RuntimeError, match="LEVERAGE_AUTHORITY_UNAVAILABLE"):
        _live_validation(effective_leverage=value)


# F. An explicit authoritative 1x is a valid calculation.
def test_live_explicit_1x_is_valid():
    validation = _live_validation(effective_leverage=D("1"))
    assert validation.effective_leverage == D("1")


# G. UNKNOWN leverage and EXPLICIT 1x are distinct states.
def test_unknown_leverage_is_not_explicit_1x():
    with pytest.raises(RuntimeError, match="LEVERAGE_AUTHORITY_UNAVAILABLE"):
        _live_validation()
    assert _live_validation(effective_leverage=D("1")).effective_leverage == D("1")


# H. Effective leverage is used verbatim; the default 10x is never substituted.
def test_effective_leverage_not_replaced_by_legacy_default():
    assert margin_limited_notional(D("100"), D("3")) == D("240")
    assert margin_limited_notional(D("100"), D("3")) != margin_limited_notional(
        D("100"), D("10")
    )

    result = ams(meta(), capital(available="100"), leverage="3")
    assert D(result.approved_position_notional) == D("240")


# I. AMS pre-selection and canonical Execution sizing agree under identical inputs.
def test_ams_and_canonical_execution_sizing_agree_under_margin_binding():
    authority = capital(available="100")
    market = meta()
    result = ams(market, authority, leverage="3")
    canonical = OrderSizingAuthority(
        symbol=market.exchange_symbol, price=market.last_price,
        equity=authority.equity, available=D("100"), risk_percent=D("0.5"),
        sl_percent=D("1"), leverage=D("3"), fixed_notional=D("0"),
        position_cap=authority.max_position_notional,
        symbol_capacity=authority.max_single_symbol_exposure,
        total_capacity=authority.max_total_exposure,
        multiplier=market.contract_multiplier, minimum=market.minimum_quantity,
        step=market.quantity_step, maximum=D("1000000"), cost_percent=D("0.1"),
    )
    sized = canonical.size()

    assert result.execution_quantity_valid is True
    assert D(result.approved_quantity_preview) == D(sized["contracts"])
    assert D(result.approved_position_notional) == D(sized["position_size"])


# J. Quantity step is preserved.
def test_quantity_step_preserved_under_margin_ceiling():
    result = ams(meta(step="7"), capital(available="100"), leverage="3")

    assert D(result.approved_quantity_preview) == D("238")
    assert D(result.approved_quantity_preview) % D("7") == 0


# K. Minimum contract quantity is preserved and never rounded up past margin.
def test_minimum_contract_quantity_preserved():
    feasible = ams(
        meta(minimum="10", step="1"), capital(available="100"), leverage="3",
    )
    assert D(feasible.approved_quantity_preview) >= D("10")

    infeasible = ams(
        meta(minimum="10", step="1"), capital(available="1"), leverage="1",
    )
    assert infeasible.execution_quantity_valid is False
    assert "MINIMUM_ORDER_NOT_FEASIBLE" in infeasible.reason_codes


# L. Maximum position notional is preserved.
def test_maximum_position_notional_preserved():
    result = ams(
        meta(), capital(available="100", max_position_notional="50"),
        leverage="3",
    )

    assert D(result.approved_position_notional) == D("50")


# B-FIX: calibration harness supplies every required capital input.
def test_calibration_capital_supplies_required_fields():
    authority = fixed_market_only_capital(NOW)

    assert authority.capital_basis == SYNTHETIC_CAPITAL_BASIS
    assert (
        authority.single_symbol_exposure_percent
        == SYNTHETIC_SINGLE_SYMBOL_EXPOSURE_PERCENT
    )
    assert authority.max_single_symbol_exposure == D("100")
    for required in (
        authority.available_capital, authority.risk_budget,
        authority.max_position_notional, authority.remaining_exposure,
        authority.remaining_position_capacity, authority.capital_basis,
        authority.max_single_symbol_exposure,
    ):
        assert required is not None


def test_calibration_candidate_not_rejected_for_missing_capital_fields():
    authority = fixed_market_only_capital(NOW)
    result = ams(meta(), authority, leverage=str(SYNTHETIC_EFFECTIVE_LEVERAGE))

    assert result.capital_authority_ready is True
    assert "CAPITAL_AUTHORITY_INCOMPLETE" not in result.reason_codes
    assert result.execution_quantity_valid is True


def test_calibration_fail_closed_when_required_field_genuinely_absent():
    authority = build_capital_eligibility_contract(
        equity=D("1000"), available_capital=D("900"), capital_basis=None,
        risk_budget=D("4.5"), max_position_notional=D("100"),
        total_exposure_percent=D("20"),
        single_symbol_exposure_percent=D("10"), open_exposure=D("0"),
        position_count=0, pending_order_count=0, mm_regime="CALIBRATION_ONLY",
        policy_version="test", evaluated_at=NOW,
    )
    result = ams(meta(), authority)

    assert result.capital_authority_ready is False
    assert "CAPITAL_AUTHORITY_INCOMPLETE" in result.reason_codes


# C-FIX: mapping policy contract requires singleSymbolExposurePercent.
def test_mapping_policy_complete_includes_single_symbol_cap():
    adapter = live_authority(Exchange())
    contract = adapter.build_capital_eligibility(
        adapter.read(), policy=dict(POLICY),
    )

    assert contract.single_symbol_exposure_percent == D("10")
    assert contract.max_single_symbol_exposure == D("100")


def test_mapping_policy_missing_single_symbol_percent_fails_loud():
    adapter = live_authority(Exchange())
    snapshot = adapter.read()
    policy = dict(POLICY)
    policy.pop("singleSymbolExposurePercent")

    with pytest.raises(RuntimeError, match="LIVE_MM_POLICY_UNAVAILABLE"):
        adapter.build_capital_eligibility(snapshot, policy=policy)


@pytest.mark.parametrize("value", [None, "abc", "0", "-1", True, "NaN", "Infinity"])
def test_mapping_policy_invalid_single_symbol_percent_fails_loud(value):
    adapter = live_authority(Exchange())
    snapshot = adapter.read()
    policy = {**POLICY, "singleSymbolExposurePercent": value}

    with pytest.raises(RuntimeError, match="LIVE_MM_POLICY_UNAVAILABLE"):
        adapter.build_capital_eligibility(snapshot, policy=policy)
