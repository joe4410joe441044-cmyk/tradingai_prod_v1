"""WORK AA: AMS pre-selection must reuse the execution MM sizing authority.

These tests are fully isolated: no network, no authenticated exchange calls,
no bot start, no order creation.  They prove the pre-selection eligibility
contract enforces both total and single-symbol exposure through the existing
canonical Money Management sizing primitive.
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.auto_market_selection.market_scanner import (
    MarketScanner,
    ScannerInput,
    ScannerRejectionReason,
    TickerSnapshot,
)
from backend.market.kucoin_futures_public import (
    FuturesContractMetadata,
    FuturesTicker,
    MarketUniverseSnapshot,
)
from backend.money_management.capital_eligibility import (
    build_capital_eligibility_contract,
    evaluate_market_capital_eligibility,
)
from backend.money_management.live_capital_authority import (
    build_live_capital_eligibility,
)
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
from backend.money_management.order_sizing import (
    OrderSizingAuthority,
    SizingRejected,
)
from backend.money_management.paper_capital_authority import (
    build_paper_capital_eligibility,
)


D = Decimal
NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


def meta(
    *, symbol="TESTUSDT", exchange_symbol="TESTUSDTM", multiplier="1",
    step="1", minimum="1", last_price="1", minimum_notional=None,
    tradable_status="Open", evaluated_at=NOW,
):
    return FuturesContractMetadata(
        symbol, exchange_symbol, "TEST", "USDT", "USDT", "FFWCSX",
        tradable_status, D(multiplier), None if step is None else D(step),
        None if minimum is None else D(minimum),
        None if minimum_notional is None else D(minimum_notional),
        D("0.0001"), D("0.0002"), D("0.0006"), D("100"),
        {"initialMargin": D("0.01")}, D(last_price), evaluated_at,
    )


def capital(
    *, equity="1000", available="900", basis="900", risk_budget="4.5",
    max_position_notional="100", total_pct="20", single_pct="10",
    open_exposure="0", position_count=0, pending_order_count=0,
    authority_fresh=True, entry_allowed=True, evaluated_at=NOW,
):
    return build_capital_eligibility_contract(
        equity=D(equity), available_capital=D(available), capital_basis=D(basis),
        risk_budget=None if risk_budget is None else D(risk_budget),
        max_position_notional=(
            None if max_position_notional is None else D(max_position_notional)
        ),
        total_exposure_percent=None if total_pct is None else D(total_pct),
        single_symbol_exposure_percent=None if single_pct is None else D(single_pct),
        open_exposure=D(open_exposure),
        position_count=position_count, pending_order_count=pending_order_count,
        mm_regime="NORMAL", policy_version="test/v1", evaluated_at=evaluated_at,
        authority_fresh=authority_fresh, execution_entry_allowed=entry_allowed,
    )


def evaluate(market, authority, **changes):
    values = dict(
        stop_loss_percent=D("10"), effective_cost_percent=D("0.1"),
        risk_percent=D("0.5"), evaluated_at=market.metadata_evaluated_at,
    )
    values.update(changes)
    return evaluate_market_capital_eligibility(market, authority, **values)


# A. Valid under total exposure, invalid under single-symbol exposure.
def test_candidate_valid_under_total_but_invalid_under_single_symbol():
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct="20", single_pct="0.05",
    )
    assert authority.max_total_exposure == D("200")
    assert authority.max_single_symbol_exposure == D("0.5")

    result = evaluate(meta(last_price="1"), authority)

    assert result.execution_quantity_valid is False
    assert result.preselection_eligible is False
    assert "MINIMUM_ORDER_NOT_FEASIBLE" in result.reason_codes
    assert result.approved_quantity_preview == D("0")
    assert result.capital_authority_ready is True
    assert result.market_data_ready is True


# B. Valid under both exposure limits.
def test_candidate_valid_under_both_exposure_limits_is_execution_valid():
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct="20", single_pct="10",
    )
    result = evaluate(meta(last_price="1"), authority)

    assert result.execution_quantity_valid is True
    assert result.preselection_eligible is True
    assert result.eligible is True
    assert result.approved_quantity_preview == D("49")
    assert D(result.approved_position_notional) <= authority.max_single_symbol_exposure
    assert D(result.approved_position_notional) <= authority.max_total_exposure


# C. Minimum exchange contract exceeds single-symbol cap.
def test_exchange_minimum_notional_exceeding_single_symbol_cap_is_invalid():
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct="20", single_pct="0.05",
    )
    market = meta(last_price="1", minimum="2")
    minimum_notional = market.minimum_quantity * market.contract_multiplier * market.last_price
    assert minimum_notional > authority.max_single_symbol_exposure

    result = evaluate(market, authority)

    assert result.execution_quantity_valid is False
    assert result.preselection_eligible is False


# D. Missing contract metadata.
def test_missing_contract_metadata_fails_closed_without_quantity():
    result = evaluate(meta(last_price="1", step=None), capital())

    assert result.market_data_ready is False
    assert result.execution_quantity_valid is False
    assert result.approved_quantity_preview is None
    assert "MARKET_METADATA_INCOMPLETE" in result.reason_codes


# E. Stale capital authority.
def test_stale_capital_authority_is_not_execution_valid():
    result = evaluate(meta(), capital(authority_fresh=False))

    assert result.capital_authority_ready is False
    assert result.execution_quantity_valid is False
    assert "CAPITAL_AUTHORITY_STALE" in result.reason_codes


# F. Missing MM policy inputs.
def test_missing_mm_policy_inputs_fail_closed():
    missing_capital = evaluate(meta(), capital(risk_budget=None))
    assert missing_capital.capital_authority_ready is False
    assert "CAPITAL_AUTHORITY_INCOMPLETE" in missing_capital.reason_codes

    invalid_leverage = evaluate(
        meta(), capital(), effective_leverage=D("0")
    )
    assert invalid_leverage.mm_policy_eligible is False
    assert invalid_leverage.execution_quantity_valid is False
    assert invalid_leverage.reason_codes == ("LEVERAGE_AUTHORITY_INVALID",)


# G. Zero or invalid quantity.
def test_zero_quantity_is_never_execution_valid():
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="0",
        max_position_notional="1000", total_pct="20", single_pct="10",
    )
    result = evaluate(meta(last_price="1"), authority)

    assert result.execution_quantity_valid is False
    assert result.preselection_eligible is False
    assert "POSITION_SIZE_ZERO" in result.reason_codes


def _scanner_input(authority, markets, evaluated_at=NOW):
    contracts = tuple(markets)
    tickers = tuple(
        FuturesTicker(
            item.exchange_symbol, D("1"), D("0.99"), D("1.01"),
            D("10"), D("10"), None, 1,
        )
        for item in contracts
    )
    eligibility = {
        item.canonical_symbol: evaluate(item, authority) for item in contracts
    }
    return ScannerInput(
        MarketUniverseSnapshot(contracts, evaluated_at, "FRESH"),
        TickerSnapshot(tickers, evaluated_at, "FRESH"),
        authority, eligibility, evaluated_at, evaluated_at,
    )


# H. AUTO ranking with mixed valid/invalid candidates.
def test_auto_ranking_excludes_execution_invalid_candidates():
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct="20", single_pct="10",
    )
    valid = meta(
        symbol="AAAUSDT", exchange_symbol="AAAUSDTM", last_price="1",
    )
    invalid = meta(
        symbol="BBBUSDT", exchange_symbol="BBBUSDTM", last_price="10000",
    )
    result = MarketScanner().scan(_scanner_input(authority, (valid, invalid)))

    eligible_symbols = {item.symbol for item in result.candidates}
    rejected = {item.symbol: item for item in result.rejections}
    assert eligible_symbols == {"AAAUSDT"}
    assert "BBBUSDT" in rejected
    assert ScannerRejectionReason.CAPITAL_INELIGIBLE in rejected["BBBUSDT"].rejection_reasons


# I. Entry authority disabled must not invalidate quantity feasibility.
def test_entry_authority_disabled_keeps_execution_quantity_valid():
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct="20", single_pct="10",
        entry_allowed=False,
    )
    result = evaluate(meta(last_price="1"), authority)

    assert result.entry_authority_enabled is False
    assert result.execution_quantity_valid is True
    assert result.approved_quantity_preview == D("49")
    assert result.preselection_eligible is False
    assert result.eligible is False
    assert "MM_ENTRY_LOCKED" in result.reason_codes


# J. PAPER mode regression.
def test_paper_capital_authority_enforces_single_symbol_exposure():
    config = build_default_money_management_config()
    paper_state = {
        "equity": "1000", "availableBalance": "1000", "positionState": "FLAT",
        "pendingOrder": False, "updatedAt": NOW.timestamp(),
    }
    authority = build_paper_capital_eligibility(
        paper_state, config=config, policy_version="test/v1", mm_evaluated_at=NOW,
    )
    assert authority.capital_source == "PAPER_ACCOUNT"
    assert authority.max_single_symbol_exposure == D("100")

    result = evaluate(meta(last_price="1"), authority)
    assert result.preselection_eligible is True
    assert D(result.approved_position_notional) <= authority.max_single_symbol_exposure


# K. MANUAL mode regression.
def test_manual_live_capital_authority_enforces_single_symbol_exposure():
    config = build_default_money_management_config()
    snapshot = SimpleNamespace(
        source_authority="REAL_LIVE_ACCOUNT", authority_fresh=True,
        open_position_state="FLAT", pending_order_state="NONE",
        available_capital=D("1000"), equity=D("1000"), evaluated_at=NOW,
    )
    authority = build_live_capital_eligibility(
        snapshot, config=config, policy_version="test/v1",
    )
    assert authority.mm_mode == "MANUAL"
    assert authority.max_single_symbol_exposure == D("100")

    result = evaluate(meta(last_price="1"), authority)
    assert result.preselection_eligible is True


# L. Small Account Mode remains unchanged.
def test_small_account_mode_remains_disabled_and_untouched():
    config = build_default_money_management_config()
    assert config.small_account_minimum_contract_mode is False
    assert config.small_account_max_contracts == D("1")

    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct="20", single_pct="10",
    )
    assert authority.single_symbol_exposure_percent == D("10")
    assert authority.max_single_symbol_exposure == D("100")


def _order_sizing_authority(authority, market, *, risk_percent, sl, cost, leverage="1"):
    return OrderSizingAuthority(
        symbol=market.exchange_symbol, price=market.last_price, equity=authority.equity,
        available=D("100000"), risk_percent=D(risk_percent), sl_percent=D(sl),
        leverage=D(leverage), fixed_notional=D("0"),
        position_cap=authority.max_position_notional,
        symbol_capacity=authority.max_single_symbol_exposure,
        total_capacity=authority.max_total_exposure,
        multiplier=market.contract_multiplier, minimum=market.minimum_quantity,
        step=market.quantity_step, maximum=D("1000000"), cost_percent=D(cost),
    )


# M. Canonical sizing and AMS classification stay consistent.
@pytest.mark.parametrize("scenario", [
    {"single_pct": "10", "total_pct": "20", "step": "1", "minimum": "1",
     "expected": True},
    {"single_pct": "0.05", "total_pct": "20", "step": "1", "minimum": "1",
     "expected": False},
    {"single_pct": "2", "total_pct": "0.5", "step": "1", "minimum": "10",
     "expected": False},
    {"single_pct": "10", "total_pct": "20", "step": "1000", "minimum": "1",
     "expected": False},
])
def test_canonical_sizing_and_ams_classification_agree(scenario):
    authority = capital(
        equity="1000", available="1000", basis="1000", risk_budget="1000",
        max_position_notional="1000", total_pct=scenario["total_pct"],
        single_pct=scenario["single_pct"],
    )
    market = meta(
        last_price="1", step=scenario["step"], minimum=scenario["minimum"],
    )
    ams = evaluate(market, authority)

    sizing = _order_sizing_authority(authority, market, risk_percent="0.5", sl="10", cost="0.1")
    try:
        sizing.size()
        canonical_valid = True
    except SizingRejected:
        canonical_valid = False

    assert canonical_valid is scenario["expected"]
    assert ams.execution_quantity_valid is canonical_valid
