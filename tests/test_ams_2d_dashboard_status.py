from dataclasses import replace

from backend.auto_market_selection import (
    CandidateRankingEngine, MarketScanner, build_auto_market_selection_status,
    build_selection_audit_event, build_selection_proposal,
)
from tests.test_ams_1a_market_scanner import scanner_input


def contracts():
    source = scanner_input()
    scanner = MarketScanner().scan(source)
    ranking = CandidateRankingEngine().rank(scanner)
    audit = build_selection_audit_event(source.universe, source.capital, scanner, ranking)
    proposal = build_selection_proposal(
        ranking, audit,
        active_symbol_authority={"activeSymbol": "ETHUSDT", "selectionMode": "MANUAL"},
        position_state="FLAT", pending_order_state=False,
        mm_authority=source.capital, emergency_safe=True,
    )
    return source, audit, proposal


def test_status_exposes_authoritative_symbol_scanner_ranking_top_and_mm():
    source, audit, proposal = contracts()
    result = build_auto_market_selection_status(
        active_symbol="ETHUSDT", selection_mode="MANUAL",
        requested_symbol="SOLUSDT", audit_event=audit, proposal=proposal,
    )
    assert result["activeSymbol"] == "ETHUSDT"
    assert result["requestedSymbol"] == "SOLUSDT"
    assert result["topCandidate"]["symbol"] == "BTCUSDT"
    assert result["activeSymbol"] != result["topCandidate"]["symbol"]
    assert result["scanner"]["evaluatedCount"] == 1
    assert result["ranking"]["rankedCount"] == 1
    assert result["topCandidate"]["spreadScore"] == "1"
    assert result["capitalEligibility"]["riskBudget"] == str(source.capital.risk_budget)
    assert result["readOnly"] is True


def test_null_mm_values_stay_null_and_stale_is_visible():
    _, audit, _ = contracts()
    capital = dict(audit.capital_snapshot)
    capital.update({"riskBudget": None, "remainingExposure": None,
                    "authorityFresh": False})
    status = build_auto_market_selection_status(
        active_symbol="ETHUSDT",
        audit_event=replace(audit, capital_snapshot=capital),
    )
    assert status["capitalEligibility"]["riskBudget"] is None
    assert status["capitalEligibility"]["remainingExposure"] is None
    assert status["capitalEligibility"]["status"] == "BLOCKED"
    assert status["freshness"]["mm"] == "STALE"


def test_no_audit_is_truthful_unavailable_without_fallback_values():
    status = build_auto_market_selection_status(active_symbol=None)
    assert status["activeSymbol"] is None
    assert status["scanner"]["status"] == "UNAVAILABLE"
    assert status["ranking"]["status"] == "UNAVAILABLE"
    assert status["topCandidate"]["symbol"] is None
    assert status["capitalEligibility"]["status"] == "UNAVAILABLE"


def test_same_cycle_live_scores_are_projected_with_decimal_advantage():
    status = build_auto_market_selection_status(
        active_symbol="ETHUSDT",
        live_observation={
            "rankingCycleId": "rank-1",
            "observationId": "ams-observation-1",
            "rankingEvaluatedAt": "2026-08-09T03:00:00Z",
            "candidateScore": "0.91",
            "activeMarketScore": "0.50",
        },
        live_auto_runtime={"liveAutoEnabled": False, "runtimeState": "STOPPED"},
    )

    assert status["liveAuto"]["candidateScore"] == "0.91"
    assert status["liveAuto"]["activeMarketScore"] == "0.50"
    assert status["liveAuto"]["scoreAdvantage"] == "0.41"
    assert status["liveAuto"]["rankingCycleId"] == "rank-1"
    assert status["liveAuto"]["observationId"] == "ams-observation-1"


def test_failed_switch_and_reasons_are_exposed_without_mutation_actions():
    status = build_auto_market_selection_status(
        active_symbol="BTCUSDT",
        switch_result={"state": "FAILED", "switchTransactionId": "ams-2b-x",
                       "previousSymbol": "ETHUSDT", "proposedSymbol": "BTCUSDT",
                       "committedSymbol": "BTCUSDT", "entryPaused": True,
                       "reasonCodes": ["OLD_FEED_CLEANUP_FAILED"]},
    )
    assert status["switch"]["state"] == "FAILED"
    assert status["switch"]["entryPaused"] is True
    assert status["reasons"] == ["OLD_FEED_CLEANUP_FAILED"]


def test_no_eligible_and_no_rankable_are_normal_status_values():
    for scanner_status, ranking_status in (
        ("NO_ELIGIBLE_MARKET", "NO_RANKABLE_MARKET"),
        ("READY", "NO_RANKABLE_MARKET"),
    ):
        audit = {"scannerSummary": {"scannerStatus": scanner_status},
                 "rankingSummary": {"rankingStatus": ranking_status}}
        status = build_auto_market_selection_status(active_symbol="ETHUSDT", audit_event=audit)
        assert status["scanner"]["status"] == scanner_status
        assert status["ranking"]["status"] == ranking_status
        assert status["topCandidate"]["symbol"] is None


def test_auto_runtime_cycle_is_exposed_read_only():
    status = build_auto_market_selection_status(
        active_symbol="BTCUSDT",
        cycle={"autoSelectionCycleId": "ams-4a-cycle", "mode": "AUTO_PAPER",
               "status": "COMPLETED", "currentActiveSymbol": "ETHUSDT",
               "topCandidateSymbol": "BTCUSDT", "proposedSymbol": "BTCUSDT",
               "finalActiveSymbol": "BTCUSDT", "evaluatedAt": "2026-08-09T03:00:00Z",
               "reasonCodes": []},
    )
    assert status["autoRuntime"] == {
        "mode": "AUTO_PAPER", "runtimeState": "STOPPED",
        "cycleId": "ams-4a-cycle", "status": "COMPLETED",
        "currentActiveSymbol": "ETHUSDT", "topCandidateSymbol": "BTCUSDT",
        "proposedSymbol": "BTCUSDT", "finalActiveSymbol": "BTCUSDT",
        "evaluatedAt": "2026-08-09T03:00:00Z", "reasonCodes": [],
        "lastCycleId": None, "lastCycleStatus": None,
    }


def test_lifecycle_state_and_failure_are_visible_on_dashboard():
    status = build_auto_market_selection_status(
        active_symbol="BTCUSDT",
        lifecycle={"amsMode": "AUTO_PAPER", "amsRuntimeState": "FAILED",
                   "lastCycleId": "ams-4b-x", "lastCycleStatus": "FAILED",
                   "reasonCodes": ["AUTO_RUNTIME_CYCLE_FAILED"]},
    )
    assert status["autoRuntime"]["mode"] == "AUTO_PAPER"
    assert status["autoRuntime"]["runtimeState"] == "FAILED"
    assert status["autoRuntime"]["lastCycleId"] == "ams-4b-x"
    assert status["autoRuntime"]["reasonCodes"] == ["AUTO_RUNTIME_CYCLE_FAILED"]
