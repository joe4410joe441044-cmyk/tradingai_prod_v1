"""WORK I P0 focused tests: canonical cycle-evidence capture orchestrator.

All persistence uses ``tmp_path``.  No production path, runtime store, DB or
trading authority is touched.
"""

import json

import pytest

from backend.runtime.cycle_evidence_capture import (
    CAPTURE_SOURCE,
    REASON_CONFLICT,
    REASON_EVIDENCE_TYPE_MISMATCH,
    REASON_FINALIZED,
    REASON_INVALID_TRANSITION,
    REASON_OUT_OF_ORDER,
    REASON_STAGE_MISMATCH,
    REASON_STAGE_UNKNOWN,
    CaptureLifecycleState,
    CaptureOutcome,
    CycleEvidenceCapture,
    capture_cycle_evidence,
)
from backend.runtime.cycle_evidence_store import AppendOutcome, AppendResult, CycleEvidenceStore

CYCLE = "cycle-0001"
TRACE = "trading-e2e-0001"

FULL_CYCLE_ITEMS = [
    {"stage": 0, "evidence_type": "PARAMETER_CONTEXT", "status": "COMPLETED",
     "payload": {"configuredRevision": 7, "effectiveRevision": 7}},
    {"stage": 1, "evidence_type": "AUTO_CANDIDATE_SELECTION", "status": "COMPLETED",
     "payload": {"selected": "MOVEUSDT"}},
    {"stage": 2, "evidence_type": "MARKET_CONTEXT", "status": "COMPLETED",
     "payload": {"bestBid": 0.1}},
    {"stage": 3, "evidence_type": "FEATURE_EVIDENCE", "status": "COMPLETED",
     "payload": {"featureCount": 4}},
    {"stage": 4, "evidence_type": "STRATEGY_SIGNAL", "status": "COMPLETED",
     "payload": {"decision": "BUY"}},
    {"stage": 5, "evidence_type": "AI_DECISION", "status": "COMPLETED",
     "payload": {"decision": "BUY"}},
    {"stage": 6, "evidence_type": "MONEY_MANAGEMENT_DECISION", "status": "COMPLETED",
     "payload": {"riskPercent": 0.5, "riskPercentSource": "MM_CONFIG"}},
    {"stage": 7, "evidence_type": "GOVERNANCE_DECISION", "status": "COMPLETED",
     "payload": {"allowed": True}},
    {"stage": 8, "evidence_type": "EXCHANGE_REQUEST", "status": "COMPLETED",
     "payload": {"orderType": "LIMIT"}},
    {"stage": 9, "evidence_type": "POSITION", "status": "COMPLETED",
     "payload": {"open": True}},
    {"stage": 10, "evidence_type": "EXIT_DECISION", "status": "COMPLETED",
     "payload": {"exitReason": "TAKE_PROFIT"}},
    {"stage": 11, "evidence_type": "CLOSE_FILL", "status": "COMPLETED",
     "payload": {"price": 0.1125}},
    {"stage": 12, "evidence_type": "FINAL_EXCHANGE_STATE", "status": "COMPLETED",
     "payload": {"flat": True}},
    {"stage": 13, "evidence_type": "TRADE_PERFORMANCE", "status": "COMPLETED",
     "payload": {"realizedPnl": 1.25}},
    {"stage": 14, "evidence_type": "CYCLE_READINESS", "status": "COMPLETED",
     "payload": {"ready": True}},
]


def make_session(tmp_path, *, mode="PAPER", cycle_id=CYCLE, **kwargs):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    session = CycleEvidenceCapture(
        store,
        cycle_id=cycle_id,
        mode=mode,
        correlation_id=TRACE,
        trade_id="trade-1",
        symbol="MOVEUSDT",
        parameter_revision_id=7,
        configuration_revision_id=7,
        strategy_revision=3,
        task_id="TRADINGAI-WORK-I-01",
        acceptance_id="ACC-1",
        commit_sha="deadbeef",
        **kwargs,
    )
    return store, session


# -- full 15-stage cycle ----------------------------------------------------


def test_full_cycle_in_canonical_order(tmp_path):
    store, session = make_session(tmp_path)
    results = session.capture_many(FULL_CYCLE_ITEMS)
    assert len(results) == 15
    assert all(result.outcome is CaptureOutcome.ACCEPTED for result in results)
    assert [result.stage for result in results] == list(range(15))
    assert session.is_cycle_complete() is True
    assert session.captured_stages() == list(range(15))
    assert session.next_expected_stage() is None
    assert len(store.load()) == 15


def test_capture_many_sorts_canonical_order(tmp_path):
    _, session = make_session(tmp_path)
    results = session.capture_many(list(reversed(FULL_CYCLE_ITEMS)))
    assert [result.stage for result in results] == list(range(15))


def test_capture_cycle_evidence_convenience(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    results = capture_cycle_evidence(
        store, cycle_id=CYCLE, mode="LIVE", items=FULL_CYCLE_ITEMS, symbol="MOVEUSDT"
    )
    assert len(results) == 15
    assert all(result.ok for result in results)
    assert {record["mode"] for record in store.load()} == {"LIVE"}


# -- stage resolution / validation -----------------------------------------


def test_stage_number_name_mismatch_rejected(tmp_path):
    _, session = make_session(tmp_path)
    result = session.capture_stage(
        5, stage_name="EXECUTION", evidence_type="AI_DECISION", status="COMPLETED"
    )
    assert result.outcome is CaptureOutcome.REJECTED
    assert result.reason == REASON_STAGE_MISMATCH


def test_unknown_stage_rejected(tmp_path):
    _, session = make_session(tmp_path)
    result = session.capture_stage(99, evidence_type="AI_DECISION", status="COMPLETED")
    assert result.outcome is CaptureOutcome.REJECTED
    assert result.reason == REASON_STAGE_UNKNOWN


def test_evidence_type_not_allowed_for_stage_rejected(tmp_path):
    store, session = make_session(tmp_path)
    result = session.capture_stage(
        2, evidence_type="AI_DECISION", status="COMPLETED"
    )
    assert result.outcome is CaptureOutcome.REJECTED
    assert result.reason == REASON_EVIDENCE_TYPE_MISMATCH
    assert store.load() == []


def test_invalid_status_rejected(tmp_path):
    store, session = make_session(tmp_path)
    result = session.capture_stage(
        0, evidence_type="PARAMETER_CONTEXT", status="DONE"
    )
    assert result.outcome is CaptureOutcome.REJECTED
    assert store.load() == []


# -- identity preservation --------------------------------------------------


def test_identity_is_preserved_in_persisted_envelope(tmp_path):
    store, session = make_session(tmp_path)
    session.capture_stage(
        13,
        evidence_type="TRADE_PERFORMANCE",
        status="COMPLETED",
        payload={"realizedPnl": 1.25},
        source_record_id="stage13-record-1",
    )
    record = store.query(cycle_id=CYCLE)["records"][0]
    assert record["cycle_id"] == CYCLE
    assert record["correlation_id"] == TRACE
    assert record["trade_id"] == "trade-1"
    assert record["symbol"] == "MOVEUSDT"
    assert record["mode"] == "PAPER"
    assert record["lifecycle_stage"] == 13
    assert record["parameter_revision_id"] == "7"
    assert record["configuration_revision_id"] == "7"
    assert record["source_record_id"] == "stage13-record-1"
    assert record["task_id"] == "TRADINGAI-WORK-I-01"
    assert record["acceptance_id"] == "ACC-1"
    assert record["commit_sha"] == "deadbeef"
    assert record["payload"]["stageNumber"] == 13
    assert record["payload"]["stageName"] == "TRADE_PARAMETER_PERFORMANCE"
    assert record["payload"]["captureStatus"] == "COMPLETED"
    assert record["payload"]["sourceAuthority"] == "RECORDING_AUTHORITY"
    assert record["payload"]["strategyRevision"] == "3"
    assert record["recorded_at"]


def test_missing_identifiers_are_explicit_not_guessed(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    session = CycleEvidenceCapture(store, cycle_id="cycle-x", mode="PAPER")
    session.capture_stage(2, evidence_type="MARKET_CONTEXT", status="COMPLETED")
    record = store.query(cycle_id="cycle-x")["records"][0]
    assert record["trade_id"] is None
    assert record["parameter_revision_id"] is None
    assert record["symbol"] is None
    assert record["availability"]["trade_id"] == "NOT_CAPTURED"
    assert record["availability"]["parameter_revision_id"] == "NOT_CAPTURED"
    assert record["availability"]["symbol"] == "NOT_CAPTURED"
    assert record["availability"]["timeframe"] == "NOT_APPLICABLE"
    assert record["availability"]["cycle_id"] == "VALUE_PRESENT"
    assert "parameterRevision" not in record["payload"]


def test_caller_supplied_availability_is_preserved(tmp_path):
    store, session = make_session(tmp_path)
    session.capture_stage(
        5,
        evidence_type="AI_DECISION",
        status="COMPLETED",
        availability={
            "parent_event_id": {"state": "CAPTURE_FAILED", "detail": "crashed"}
        },
    )
    record = store.query(cycle_id=CYCLE)["records"][0]
    assert record["availability"]["parent_event_id"]["state"] == "CAPTURE_FAILED"
    assert "crashed" in record["availability"]["parent_event_id"]["detail"]


# -- lifecycle --------------------------------------------------------------


def test_lifecycle_started_partial_completed(tmp_path):
    _, session = make_session(tmp_path)
    started = session.capture_stage(5, evidence_type="AI_DECISION", status="STARTED")
    assert started.outcome is CaptureOutcome.ACCEPTED
    assert started.state is CaptureLifecycleState.STARTED
    partial = session.capture_stage(5, evidence_type="AI_DECISION", status="PARTIAL")
    assert partial.outcome is CaptureOutcome.ACCEPTED
    completed = session.capture_stage(5, evidence_type="AI_DECISION", status="COMPLETED")
    assert completed.outcome is CaptureOutcome.ACCEPTED
    assert session.state_of(5) is CaptureLifecycleState.COMPLETED
    assert session.is_stage_finalized(5) is True


@pytest.mark.parametrize("terminal", ["COMPLETED", "BLOCKED", "REJECTED", "FAILED"])
def test_terminal_states_block_overwrite(tmp_path, terminal):
    store, session = make_session(tmp_path)
    first = session.capture_stage(
        7, evidence_type="GOVERNANCE_DECISION", status=terminal, payload={"rule": "R1"}
    )
    assert first.outcome is CaptureOutcome.ACCEPTED
    overwrite = session.capture_stage(
        7, evidence_type="GOVERNANCE_DECISION", status="STARTED", payload={"rule": "R2"}
    )
    assert overwrite.outcome is CaptureOutcome.REJECTED
    assert overwrite.reason == REASON_FINALIZED
    assert session.state_of(7).value == terminal
    assert len(store.load()) == 1


def test_invalid_transition_rejected(tmp_path):
    _, session = make_session(tmp_path)
    session.capture_stage(5, evidence_type="AI_DECISION", status="PARTIAL")
    regression = session.capture_stage(5, evidence_type="AI_DECISION", status="STARTED")
    assert regression.outcome is CaptureOutcome.REJECTED
    assert regression.reason == REASON_INVALID_TRANSITION


def test_enforce_sequential_rejects_out_of_order(tmp_path):
    _, session = make_session(tmp_path, enforce_sequential=True)
    result = session.capture_stage(5, evidence_type="AI_DECISION", status="COMPLETED")
    assert result.outcome is CaptureOutcome.REJECTED
    assert result.reason == REASON_OUT_OF_ORDER
    assert session.capture_stage(
        0, evidence_type="PARAMETER_CONTEXT", status="COMPLETED"
    ).outcome is CaptureOutcome.ACCEPTED


# -- idempotency / duplicate / conflict ------------------------------------


def test_idempotent_retry_returns_duplicate_without_second_write(tmp_path):
    store, session = make_session(tmp_path)
    first = session.capture_stage(
        5, evidence_type="AI_DECISION", status="COMPLETED", payload={"decision": "BUY"}
    )
    retry = session.capture_stage(
        5, evidence_type="AI_DECISION", status="COMPLETED", payload={"decision": "BUY"}
    )
    assert first.outcome is CaptureOutcome.ACCEPTED
    assert retry.outcome is CaptureOutcome.DUPLICATE
    assert retry.evidence_id == first.evidence_id
    assert len(store.load()) == 1


def test_conflicting_content_same_identity_fails_closed(tmp_path):
    store, session = make_session(tmp_path)
    session.capture_stage(
        5, evidence_type="AI_DECISION", status="COMPLETED", payload={"decision": "BUY"}
    )
    conflict = session.capture_stage(
        5, evidence_type="AI_DECISION", status="COMPLETED", payload={"decision": "SELL"}
    )
    assert conflict.outcome is CaptureOutcome.CONFLICT
    assert conflict.reason == REASON_CONFLICT
    assert len(store.load()) == 1


def test_distinct_event_key_produces_distinct_evidence(tmp_path):
    store, session = make_session(tmp_path)
    first = session.capture_stage(
        8, evidence_type="FILL", status="STARTED",
        payload={"fillId": "f1"}, event_key="f1",
    )
    second = session.capture_stage(
        8, evidence_type="FILL", status="STARTED",
        payload={"fillId": "f2"}, event_key="f2",
    )
    assert first.ok and second.ok
    assert first.evidence_id != second.evidence_id
    assert len(store.load()) == 2

    # Once the stage reaches a terminal state no further evidence may be added.
    assert session.capture_stage(
        8, evidence_type="FILL", status="COMPLETED", event_key="final"
    ).ok
    late = session.capture_stage(
        8, evidence_type="FEE", status="COMPLETED", event_key="fee-1"
    )
    assert late.outcome is CaptureOutcome.REJECTED
    assert late.reason == REASON_FINALIZED
    assert len(store.load()) == 3


# -- restart safety ---------------------------------------------------------


def test_restart_resume_and_continue(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    session = CycleEvidenceCapture(store, cycle_id=CYCLE, mode="PAPER", symbol="MOVEUSDT")
    for stage, etype in ((0, "PARAMETER_CONTEXT"), (1, "AUTO_CANDIDATE_SELECTION"),
                         (2, "MARKET_CONTEXT")):
        assert session.capture_stage(stage, evidence_type=etype, status="COMPLETED").ok

    reloaded_store = CycleEvidenceStore(path)
    resumed = CycleEvidenceCapture.resume(reloaded_store, CYCLE)
    assert resumed.state_of(0) is CaptureLifecycleState.COMPLETED
    assert resumed.state_of(2) is CaptureLifecycleState.COMPLETED
    assert resumed.state_of(3) is CaptureLifecycleState.NOT_STARTED
    assert resumed.symbol == "MOVEUSDT"
    assert resumed.mode == "PAPER"
    assert resumed.next_expected_stage() == 3

    continued = resumed.capture_stage(
        3, evidence_type="FEATURE_EVIDENCE", status="COMPLETED"
    )
    assert continued.ok
    assert len(reloaded_store.load()) == 4


def test_restart_duplicate_prevention_across_sessions(tmp_path):
    path = tmp_path / "ce.jsonl"
    first_store = CycleEvidenceStore(path)
    first = CycleEvidenceCapture(first_store, cycle_id=CYCLE, mode="PAPER")
    assert first.capture_stage(
        5, evidence_type="AI_DECISION", status="COMPLETED", payload={"decision": "BUY"}
    ).ok
    assert len(path.read_text().strip().splitlines()) == 1

    second_store = CycleEvidenceStore(path)
    second = CycleEvidenceCapture(second_store, cycle_id=CYCLE, mode="PAPER")
    retry = second.capture_stage(
        5, evidence_type="AI_DECISION", status="COMPLETED", payload={"decision": "BUY"}
    )
    assert retry.outcome is CaptureOutcome.DUPLICATE
    assert len(path.read_text().strip().splitlines()) == 1


# -- store failure structured results --------------------------------------


def test_store_write_failure_returns_structured_error(tmp_path, monkeypatch):
    store, session = make_session(tmp_path)

    def boom(_envelope):
        raise OSError("disk on fire")

    monkeypatch.setattr(store, "append", boom)
    result = session.capture_stage(5, evidence_type="AI_DECISION", status="COMPLETED")
    assert result.outcome is CaptureOutcome.STORE_ERROR
    assert result.reason == "STORE_WRITE_FAILED"
    assert result.error and "disk on fire" in result.error
    assert session.state_of(5) is CaptureLifecycleState.NOT_STARTED


def test_store_rejected_result_is_surfaced(tmp_path, monkeypatch):
    store, session = make_session(tmp_path)

    def rejected(_envelope):
        return AppendResult(AppendOutcome.REJECTED, error="write refused")

    monkeypatch.setattr(store, "append", rejected)
    result = session.capture_stage(5, evidence_type="AI_DECISION", status="COMPLETED")
    assert result.outcome is CaptureOutcome.STORE_ERROR
    assert result.error == "write refused"
    assert session.state_of(5) is CaptureLifecycleState.NOT_STARTED


# -- provenance / integrity / links ----------------------------------------


def test_provenance_integrity_and_links(tmp_path):
    store, session = make_session(tmp_path)
    session.capture_stage(
        8,
        evidence_type="EXCHANGE_ACK",
        status="COMPLETED",
        payload={"latencyMs": 12},
        links={"orderId": "order-1", "exchangeOrderId": "ex-1"},
    )
    record = store.query(cycle_id=CYCLE)["records"][0]
    assert record["provenance"]["captureOrchestrator"] == "cycle_evidence_capture/v1"
    assert record["provenance"]["truthLevel"] == "CURRENT_SOURCE_RUNTIME"
    assert record["integrity"]["algorithm"] == "sha256"
    assert record["integrity"]["digest"]
    assert record["links"]["orderId"] == "order-1"
    assert record["links"]["exchangeOrderId"] == "ex-1"
    assert record["links"]["cycleId"] == CYCLE
    assert record["source"]["subsystem"] == CAPTURE_SOURCE["subsystem"]


# -- security / redaction ---------------------------------------------------


def test_secret_fields_redacted_and_not_persisted(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    session = CycleEvidenceCapture(store, cycle_id=CYCLE, mode="PAPER")
    result = session.capture_stage(
        8,
        evidence_type="EXCHANGE_REQUEST",
        status="COMPLETED",
        payload={"price": 1.0, "apiKey": "SUPER_SECRET_VALUE"},
    )
    assert result.ok
    raw = path.read_text()
    assert "SUPER_SECRET_VALUE" not in raw
    record = store.load()[0]
    assert "apiKey" not in record["payload"]
    assert "payload.apiKey" in record["redaction"]["fields"]


def test_secret_reject_policy_blocks_capture(tmp_path):
    store, session = make_session(tmp_path, secret_policy="REJECT")
    result = session.capture_stage(
        8,
        evidence_type="EXCHANGE_REQUEST",
        status="COMPLETED",
        payload={"token": "abc123"},
    )
    assert result.outcome is CaptureOutcome.REJECTED
    assert store.load() == []


# -- PAPER / LIVE -----------------------------------------------------------


def test_paper_and_live_modes_are_preserved(tmp_path):
    paper_store = CycleEvidenceStore(tmp_path / "paper.jsonl")
    live_store = CycleEvidenceStore(tmp_path / "live.jsonl")
    paper = CycleEvidenceCapture(paper_store, cycle_id="c-p", mode="PAPER", symbol="MOVEUSDT")
    live = CycleEvidenceCapture(live_store, cycle_id="c-l", mode="LIVE", symbol="MOVEUSDT")
    assert paper.capture_stage(9, evidence_type="POSITION", status="COMPLETED").ok
    assert live.capture_stage(9, evidence_type="POSITION", status="COMPLETED").ok
    assert paper_store.load()[0]["mode"] == "PAPER"
    assert live_store.load()[0]["mode"] == "LIVE"


def test_invalid_mode_rejected(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    with pytest.raises(ValueError):
        CycleEvidenceCapture(store, cycle_id="c", mode="SANDBOX")


# -- corruption isolation ---------------------------------------------------


def test_corrupt_existing_line_is_isolated(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    session = CycleEvidenceCapture(store, cycle_id=CYCLE, mode="PAPER")
    assert session.capture_stage(0, evidence_type="PARAMETER_CONTEXT", status="COMPLETED").ok
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{ corrupted line\n")
    assert session.capture_stage(1, evidence_type="AUTO_CANDIDATE_SELECTION", status="COMPLETED").ok

    reloaded_store = CycleEvidenceStore(path)
    rows = reloaded_store.load()
    assert [row["lifecycle_stage"] for row in rows] == [0, 1]
    assert reloaded_store.corruption_report()
    resumed = CycleEvidenceCapture.resume(reloaded_store, CYCLE)
    assert resumed.next_expected_stage() == 2


def test_summary_reports_stage_states(tmp_path):
    _, session = make_session(tmp_path)
    session.capture_stage(0, evidence_type="PARAMETER_CONTEXT", status="COMPLETED")
    session.capture_stage(1, evidence_type="AUTO_CANDIDATE_SELECTION", status="BLOCKED")
    summary = session.summary()
    assert summary["cycleId"] == CYCLE
    assert summary["isComplete"] is False
    stages = {entry["number"]: entry for entry in summary["stages"]}
    assert stages[0]["state"] == "COMPLETED"
    assert stages[1]["state"] == "BLOCKED"
    assert stages[2]["state"] == "NOT_STARTED"
    assert summary["nextExpectedStage"] == 1
