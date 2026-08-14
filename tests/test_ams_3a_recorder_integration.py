import json

from backend.auto_market_selection import (
    AMS_RANKING, AMS_SCAN, AMS_SELECTION_AUDIT, AMS_SELECTION_PROPOSAL,
    AMS_SYMBOL_SWITCH, AMSRecorderIntegration, CandidateRankingEngine,
    MarketScanner, SafeSymbolSwitch, build_selection_audit_event,
    build_selection_proposal, ranking_event, scanner_event,
    selection_audit_event, selection_proposal_event, symbol_switch_event,
)
from tests.test_ams_1a_market_scanner import scanner_input
from tests.test_ams_2b_safe_switch import NOW, Runtime


def completed_contracts():
    source = scanner_input()
    scanner = MarketScanner().scan(source)
    ranking = CandidateRankingEngine().rank(scanner)
    audit = build_selection_audit_event(source.universe, source.capital, scanner, ranking)
    proposal = build_selection_proposal(
        ranking, audit,
        active_symbol_authority={"activeSymbol": "ETHUSDT", "selectionMode": "MANUAL"},
        position_state="FLAT", pending_order_state=False,
        mm_authority=source.capital, emergency_safe=True, proposed_at=NOW,
    )
    return source, scanner, ranking, audit, proposal


def test_all_completed_contracts_project_to_replay_ready_envelopes():
    source, scanner, ranking, audit, proposal = completed_contracts()
    events = [
        scanner_event(scanner, active_symbol="ETHUSDT", runtime_id="runtime-1"),
        ranking_event(ranking, active_symbol="ETHUSDT", runtime_id="runtime-1"),
        selection_audit_event(audit, active_symbol="ETHUSDT", runtime_id="runtime-1"),
        selection_proposal_event(proposal, runtime_id="runtime-1"),
    ]
    assert [event["eventType"] for event in events] == [
        AMS_SCAN, AMS_RANKING, AMS_SELECTION_AUDIT, AMS_SELECTION_PROPOSAL,
    ]
    assert all(list(event) == [
        "eventId", "eventType", "timestamp", "activeSymbol", "runtimeId",
        "scannerCycleId", "rankingCycleId", "auditEventId",
        "selectionProposalId", "switchTransactionId", "payloadVersion", "payload",
    ] for event in events)
    assert events[0]["scannerCycleId"] == scanner.scanner_cycle_id
    assert events[1]["rankingCycleId"] == ranking.ranking_cycle_id
    assert events[2]["auditEventId"] == audit.event_id
    assert events[3]["selectionProposalId"] == proposal.selection_proposal_id
    assert all(event["activeSymbol"] == "ETHUSDT" for event in events)
    assert all(event["runtimeId"] == "runtime-1" for event in events)
    assert all(event["payloadVersion"] == "1" for event in events)
    json.dumps(events)


def test_source_serializations_and_reason_domains_are_preserved_without_recalculation():
    source, scanner, ranking, audit, proposal = completed_contracts()
    scan = scanner_event(scanner)
    ranked = ranking_event(ranking)
    audited = selection_audit_event(audit)
    proposed = selection_proposal_event(proposal)
    assert scan["payload"] == scanner.to_dict()
    assert ranked["payload"] == ranking.to_dict()
    assert audited["payload"] == audit.to_dict()
    assert proposed["payload"] == proposal.to_dict()
    assert scan["payload"]["capitalEligibilityContract"] == source.capital.to_dict()
    assert scan["payload"]["rejections"] == []
    candidate = ranked["payload"]["rankedCandidates"][0]
    assert candidate["rankingScore"] == "1"
    assert candidate["rankingFeatures"]["rawActivityMetric"] is None
    assert candidate["rankingFeatures"]["effectiveWeights"]["activity"] is None
    assert audited["payload"]["capitalSnapshot"]["authorityFresh"] is True
    assert proposed["payload"]["reasonCodes"] == []


def test_same_source_contract_has_same_event_identity_and_nulls_stay_null():
    _, scanner, ranking, audit, proposal = completed_contracts()
    assert scanner_event(scanner)["eventId"] == scanner_event(scanner)["eventId"]
    assert ranking_event(ranking)["eventId"] == ranking_event(ranking)["eventId"]
    assert selection_audit_event(audit)["eventId"] == selection_audit_event(audit)["eventId"]
    assert selection_proposal_event(proposal)["eventId"] == selection_proposal_event(proposal)["eventId"]
    event = scanner_event(scanner)
    assert event["rankingCycleId"] is None
    assert event["runtimeId"] is None


def test_success_and_each_failure_phase_are_recordable_with_symbol_evidence():
    _, _, _, _, proposal = completed_contracts()
    cases = [(None, True), ("subscribe", False), ("cleanup", False), ("resume", False)]
    for failure, success in cases:
        runtime = Runtime()
        runtime.fail = failure
        result = SafeSymbolSwitch(runtime).execute(proposal, started_at=NOW)
        event = symbol_switch_event(
            result, active_symbol=runtime.active, runtime_id="runtime-switch",
        )
        assert event["eventType"] == AMS_SYMBOL_SWITCH
        assert event["switchTransactionId"] == result.switch_transaction_id
        assert event["payload"] == result.to_dict()
        assert event["payload"]["previousSymbol"] == "ETHUSDT"
        assert event["payload"]["proposedSymbol"] == "BTCUSDT"
        assert event["payload"]["committedSymbol"] == result.committed_symbol
        assert event["payload"]["success"] is success


def test_recorder_failure_is_observational_and_sink_is_existing_authority():
    _, scanner, _, _, _ = completed_contracts()

    class FailingSink:
        def record_event(self, event):
            self.event = event
            raise OSError("unavailable")

    sink = FailingSink()
    integration = AMSRecorderIntegration(sink)
    active = "ETHUSDT"
    result = integration.record_scanner(
        scanner, active_symbol=active, runtime_id="runtime-1",
    )
    assert not result.recorded and result.error_code == "RECORDER_WRITE_FAILED"
    assert active == "ETHUSDT"
    assert sink.event["payload"] == scanner.to_dict()


def test_sensitive_credentials_are_rejected_before_sink_write():
    calls = []

    class Sink:
        def record_event(self, event):
            calls.append(event)

    integration = AMSRecorderIntegration(Sink())
    event = {
        "eventId": "unsafe", "payload": {"apiKey": "must-not-record"},
    }
    try:
        integration.record(event)
    except ValueError as error:
        assert "credentials" in str(error)
    else:
        raise AssertionError("credential payload accepted")
    assert calls == []
