from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from backend.auto_market_selection.market_scanner import (
    MarketScanner, ScannerStatus,
)
from tests.test_ams_1a_market_scanner import (
    NOW, capital, eligibility, reason_values, scanner_input,
)


def scan_with_capital(authority, *, eligible=True, reasons=()):
    source = scanner_input(authority=authority, eligibility_map={})
    item = source.universe.contracts[0]
    per_market = eligibility(item, authority, eligible=eligible, reasons=reasons)
    return MarketScanner().scan(replace(
        source, per_market_eligibility={item.canonical_symbol: per_market},
    ))


def test_fresh_mm_contract_and_eligible_market_is_candidate():
    authority = capital()
    result = scan_with_capital(authority)
    assert result.status is ScannerStatus.CANDIDATES_AVAILABLE
    assert result.candidates[0].capital_eligible
    assert result.capital_eligibility_contract is authority
    serialized = result.to_dict()["capitalEligibilityContract"]
    assert serialized["capitalAuthority"] == "MONEY_MANAGEMENT"
    assert serialized["ruinGuardStatus"] == "UNAVAILABLE"
    assert serialized["compoundingEnabled"] is False


@pytest.mark.parametrize(("authority", "expected"), [
    (None, "MM_UNAVAILABLE"),
    (capital(authority_fresh=False), "MM_STALE"),
    (capital(execution_entry_allowed=False), "MM_LOCKED"),
])
def test_mm_unavailable_stale_or_locked_is_rejected(authority, expected):
    source = scanner_input()
    result = MarketScanner().scan(replace(source, capital=authority))
    assert expected in reason_values(result)


@pytest.mark.parametrize("evaluated_at", [None, NOW + timedelta(seconds=1)])
def test_missing_or_future_mm_evaluated_at_is_stale(evaluated_at):
    authority = replace(capital(), evaluated_at=evaluated_at)
    result = scan_with_capital(authority)
    assert "MM_STALE" in reason_values(result)


@pytest.mark.parametrize(("changes", "expected"), [
    ({"position_count": 1}, "POSITION_CAPACITY_EXHAUSTED"),
    ({"position_count": None}, "CAPITAL_INELIGIBLE"),
    ({"risk_budget": None}, "CAPITAL_INELIGIBLE"),
    ({"equity": None}, "CAPITAL_INELIGIBLE"),
    ({"available_capital": None}, "CAPITAL_INELIGIBLE"),
    ({"open_exposure": None}, "CAPITAL_INELIGIBLE"),
])
def test_unknown_or_exhausted_mm_values_fail_closed_without_guessing(changes, expected):
    authority = capital(**changes)
    result = scan_with_capital(authority, eligible=False,
                               reasons=("CAPITAL_AUTHORITY_INCOMPLETE",))
    assert expected in reason_values(result)
    payload = result.to_dict()["capitalEligibilityContract"]
    if "risk_budget" in changes:
        assert payload["riskBudget"] is None
    if "open_exposure" in changes:
        assert payload["remainingExposureAmount"] is None
    if "position_count" in changes and changes["position_count"] is None:
        assert payload["remainingPositionCapacity"] is None


def test_negative_or_invalid_remaining_capacity_fails_closed():
    for invalid in (-1, Decimal("1")):
        authority = replace(capital(), remaining_position_capacity=invalid)
        result = scan_with_capital(authority)
        assert "CAPITAL_INELIGIBLE" in reason_values(result)


def test_mm_and_metadata_snapshot_mismatch_are_rejected():
    source = scanner_input()
    item, authority = source.universe.contracts[0], source.capital
    base = eligibility(item, authority)
    for mismatch in (
        replace(base, mm_evaluated_at=NOW - timedelta(seconds=1)),
        replace(base, metadata_evaluated_at=NOW - timedelta(seconds=1)),
    ):
        result = MarketScanner().scan(replace(
            source, per_market_eligibility={item.canonical_symbol: mismatch},
        ))
        assert "ELIGIBILITY_SNAPSHOT_MISMATCH" in reason_values(result)


def test_per_market_symbol_mismatch_is_rejected():
    source = scanner_input()
    item, authority = source.universe.contracts[0], source.capital
    mismatched = replace(eligibility(item, authority), symbol="ETHUSDT")
    result = MarketScanner().scan(replace(
        source, per_market_eligibility={item.canonical_symbol: mismatched},
    ))
    assert "ELIGIBILITY_SYMBOL_MISMATCH" in reason_values(result)


def test_calculation_and_feasibility_flags_are_authoritative():
    source = scanner_input()
    item, authority = source.universe.contracts[0], source.capital
    for field in ("calculation_allowed", "position_feasible"):
        value = replace(eligibility(item, authority), **{field: False})
        result = MarketScanner().scan(replace(
            source, per_market_eligibility={item.canonical_symbol: value},
        ))
        assert "CAPITAL_INELIGIBLE" in reason_values(result)


def test_mm_detailed_reasons_are_preserved_verbatim_and_not_coerced():
    details = ("MINIMUM_ORDER_NOT_FEASIBLE", "CAPITAL_AUTHORITY_INCOMPLETE")
    result = scan_with_capital(capital(), eligible=False, reasons=details)
    rejected = result.rejections[0]
    assert rejected.capital_reason_codes == details
    assert "CAPITAL_INELIGIBLE" in reason_values(result)
    assert rejected.to_dict()["capitalReasonCodes"] == list(details)


def test_integration_module_has_no_sizing_execution_or_selection_logic():
    import inspect
    from backend.auto_market_selection import market_scanner

    source = inspect.getsource(market_scanner)
    forbidden = (
        "calculate_position_size", "PositionSizingInput", "create_order",
        "submit_order", "activeSymbol", "weighted_score", "top_candidate",
    )
    assert all(term not in source for term in forbidden)
