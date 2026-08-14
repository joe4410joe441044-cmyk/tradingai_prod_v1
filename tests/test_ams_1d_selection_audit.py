from dataclasses import replace
from decimal import Decimal
import inspect
import json

import pytest

from backend.auto_market_selection.candidate_ranking import CandidateRankingEngine
from backend.auto_market_selection.market_scanner import MarketScanner
from backend.auto_market_selection.selection_audit import (
    SELECTION_AUDIT_EVENT_TYPE, build_selection_audit_event,
)
from tests.test_ams_1a_market_scanner import eligibility, metadata, scanner_input, ticker


def build(source=None):
    source = source or scanner_input()
    scanner = MarketScanner().scan(source)
    ranking = CandidateRankingEngine().rank(scanner)
    return source, scanner, ranking, build_selection_audit_event(
        source.universe, source.capital, scanner, ranking,
    )


def test_deterministic_identity_serialization_and_snapshot_correlation():
    source, scanner, ranking, first = build()
    second = build_selection_audit_event(source.universe, source.capital, scanner, ranking)
    assert first == second
    assert first.event_id == second.event_id
    assert first.event_type == SELECTION_AUDIT_EVENT_TYPE
    assert first.scanner_cycle_id == scanner.scanner_cycle_id
    assert first.ranking_cycle_id == ranking.ranking_cycle_id
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json()) == first.to_dict()
    assert first.to_dict()["timestamps"] == {
        "universeEvaluatedAt": "2026-08-09T03:00:00Z",
        "tickerEvaluatedAt": "2026-08-09T03:00:00Z",
        "mmEvaluatedAt": "2026-08-09T03:00:00Z",
        "scannerEvaluatedAt": "2026-08-09T03:00:00Z",
        "rankingEvaluatedAt": "2026-08-09T03:00:00Z",
    }


def test_capital_authority_and_decimal_null_evidence_are_preserved():
    source, _, _, event = build()
    snapshot = event.to_dict()["capitalSnapshot"]
    assert snapshot == source.capital.to_dict()
    assert snapshot["capitalAuthority"] == "MONEY_MANAGEMENT"
    assert snapshot["equity"] == "1000" and snapshot["availableCapital"] == "900"
    assert snapshot["riskBudget"] == "4.5"
    candidate = event.to_dict()["candidates"][0]
    assert candidate["rankingScore"] == "1"
    assert candidate["activityMetric"] is None
    assert candidate["effectiveWeights"]["activity"] is None


def test_ranked_and_rejected_order_and_three_reason_domains_are_preserved():
    btc, eth, sol = metadata(), metadata("ETHUSDT", "ETHUSDTM"), metadata("SOLUSDT", "SOLUSDTM")
    authority = scanner_input().capital
    source = scanner_input(
        contracts=[sol, eth, btc],
        tickers=[ticker("SOLUSDTM", best_bid=Decimal("2"), best_ask=Decimal("1")),
                 ticker("ETHUSDTM", best_bid=Decimal("99"), best_ask=Decimal("101"),
                        bid_size=None), ticker()],
        authority=authority,
        eligibility_map={btc.canonical_symbol: eligibility(btc, authority),
                         eth.canonical_symbol: eligibility(eth, authority),
                         sol.canonical_symbol: eligibility(sol, authority, eligible=False,
                                                           reasons=("MM_ENTRY_LOCKED",))},
    )
    _, scanner, ranking, event = build(source)
    assert [item.symbol for item in event.candidates] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert [(item.symbol, item.stage) for item in event.rejected_candidates] == [
        ("ETHUSDT", "RANKING"), ("SOLUSDT", "SCANNER")]
    eth_entry, sol_entry = event.candidates[1:]
    assert eth_entry.ranking_reason_codes == ("RANKING_DATA_INCOMPLETE",)
    assert "INVALID_BID_ASK" in sol_entry.scanner_rejection_reasons
    assert sol_entry.capital_reason_codes == ("MM_ENTRY_LOCKED",)
    assert event.top_candidate == {"symbol": "BTCUSDT", "score": "1", "rank": 1}
    assert event.selection_committed is False


def test_no_eligible_and_no_rankable_are_valid_null_top_states():
    no_eligible = scanner_input(contracts=[], tickers=[], eligibility_map={})
    assert build(no_eligible)[3].top_candidate is None
    malformed = scanner_input(tickers=[ticker(bid_size=None)])
    event = build(malformed)[3]
    assert event.ranking_summary["rankingStatus"] == "NO_RANKABLE_MARKET"
    assert event.top_candidate is None
    assert event.to_dict()["rankingSummary"]["topCandidateScore"] is None


@pytest.mark.parametrize("mutation,message", [
    (lambda s, r: (s, replace(r, scanner_cycle_id="wrong")), "scannerCycleId"),
    (lambda s, r: (s, replace(r, scanner_evaluated_at=r.evaluated_at.replace(hour=4))),
     "scanner evaluatedAt"),
    (lambda s, r: (s, replace(r, top_candidate=None)), "topCandidate"),
    (lambda s, r: (s, replace(r, evaluated_candidates=())), "ranking candidate"),
])
def test_cross_contract_mismatch_fails_closed(mutation, message):
    source, scanner, ranking, _ = build()
    scanner, ranking = mutation(scanner, ranking)
    with pytest.raises(ValueError, match=message):
        build_selection_audit_event(source.universe, source.capital, scanner, ranking)


def test_universe_and_mm_mismatch_fail_closed():
    source, scanner, ranking, _ = build()
    with pytest.raises(ValueError, match="MM authority"):
        build_selection_audit_event(source.universe, replace(source.capital, policy_version="other"),
                                    scanner, ranking)
    other_universe = replace(source.universe, contracts=(metadata("ETHUSDT", "ETHUSDTM"),))
    with pytest.raises(ValueError, match="unexpected scanner candidate"):
        build_selection_audit_event(other_universe, source.capital, scanner, ranking)


def test_builder_has_no_io_selection_execution_or_deep_dependencies():
    from backend.auto_market_selection import selection_audit
    source = inspect.getsource(selection_audit)
    forbidden = ("requests", "WebSocket", "subscribe", "open(", "create_order",
                 "submit_order", "activeSymbol", "Strategy", "backend.ai", "Recorder")
    assert all(term not in source for term in forbidden)
