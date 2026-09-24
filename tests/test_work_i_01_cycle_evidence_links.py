"""WORK I P0 focused tests: link adapters over existing canonical stores.

Verifies that evidence envelopes preserve links to Stage 13 completed trades,
trading-trace events and parameter revisions without duplicating any existing
authority.  Existing records are treated strictly read-only.
"""

import pytest

from backend.runtime.cycle_evidence_links import (
    completed_trade_evidence,
    parameter_revision_evidence,
    trace_event_evidence,
)
from backend.runtime.cycle_evidence_store import AppendOutcome, CycleEvidenceStore

STAGE13_RECORD = {
    "schemaVersion": 1,
    "recordId": "stage13-record-1",
    "origin": "PRODUCTION",
    "tradeId": "trade-1",
    "traceId": "trading-e2e-1",
    "positionId": "position-1",
    "scope": "PAPER",
    "mode": "paper",
    "symbol": "MOVEUSDT",
    "side": "BUY",
    "controlSource": "BOT",
    "parameterSetId": "strategy-params/PAPER",
    "configuredRevision": 7,
    "effectiveRevision": 7,
    "parameterRevision": 7,
    "realizedPnl": 1.25,
    "realizedPnlAuthoritative": True,
    "entryPrice": 0.1,
    "exitPrice": 0.1125,
    "quantity": 100.0,
    "notional": 11.25,
    "holdingMs": 60000.0,
    "exitReason": "TAKE_PROFIT",
    "entryTimestamp": 1000.0,
    "exitTimestamp": 1060.0,
    "runtimeId": "runtime-1",
    "recordedAt": "2026-01-01T00:00:00.000000Z",
}

TRACE_EVENT = {
    "traceId": "trading-e2e-1",
    "eventId": "trace-event-1",
    "timestamp": "2026-01-01T00:00:01.000000Z",
    "mode": "PAPER",
    "stage": "AI",
    "status": "BUY",
    "symbol": "MOVEUSDT",
    "decisionId": "decision-1",
    "metadata": {"tradeId": "trade-1", "effectiveRevision": 7},
}


class _FakeParameterSet:
    def to_dict(self):
        return {
            "parameterSetId": "strategy-params/PAPER",
            "schemaVersion": 1,
            "scope": "PAPER",
            "status": "ACTIVE",
            "createdAt": "2026-01-01T00:00:00.000000Z",
            "updatedAt": "2026-01-01T00:00:00.000000Z",
            "source": "PARAMETER_SETTINGS",
            "parameters": {"minimumCompositeScore": 0.4, "minimumHoldMs": 1500.0},
            "effectiveFrom": "2026-01-01T00:00:00.000000Z",
            "configuredRevision": 7,
            "effectiveRevision": 7,
        }


# -- Stage 13 ---------------------------------------------------------------


def test_stage13_links_preserved():
    envelope = completed_trade_evidence(
        STAGE13_RECORD,
        task_id="TRADINGAI-WORK-I-01",
        commit_sha="deadbeef",
        verified=True,
    )
    assert envelope.evidence_type == "TRADE_PERFORMANCE"
    assert envelope.lifecycle_stage == 13
    assert envelope.mode == "PAPER"
    assert envelope.trade_id == "trade-1"
    assert envelope.correlation_id == "trading-e2e-1"
    assert envelope.configuration_revision_id == "7"
    assert envelope.parameter_revision_id == "7"
    assert envelope.source_record_id == "stage13-record-1"
    assert envelope.links["sourceRecordId"] == "stage13-record-1"
    assert envelope.links["traceId"] == "trading-e2e-1"
    assert envelope.links["positionId"] == "position-1"
    assert envelope.provenance["verified"] is True
    assert envelope.payload["realizedPnl"] == 1.25


def test_stage13_missing_fields_use_availability_not_guesses():
    record = dict(STAGE13_RECORD)
    for key in ("configuredRevision", "effectiveRevision", "parameterRevision", "traceId"):
        record.pop(key, None)
    envelope = completed_trade_evidence(record)
    assert envelope.parameter_revision_id is None
    assert envelope.configuration_revision_id is None
    assert envelope.correlation_id is None
    assert envelope.availability["parameter_revision_id"] == "NOT_CAPTURED"
    assert envelope.availability["configuration_revision_id"] == "NOT_CAPTURED"
    assert envelope.availability["correlation_id"] == "NOT_CAPTURED"
    assert envelope.availability["timeframe"] == "NOT_APPLICABLE"


def test_stage13_without_mode_rejected():
    record = dict(STAGE13_RECORD)
    record.pop("mode")
    record.pop("scope")
    with pytest.raises(ValueError):
        completed_trade_evidence(record)


def test_stage13_live_mode_preserved():
    record = dict(STAGE13_RECORD)
    record["mode"] = "live"
    record["scope"] = "LIVE"
    envelope = completed_trade_evidence(record)
    assert envelope.mode == "LIVE"


# -- trading trace ----------------------------------------------------------


def test_trace_event_links_and_stage_mapping():
    envelope = trace_event_evidence(TRACE_EVENT)
    assert envelope.evidence_type == "AI_DECISION"
    assert envelope.lifecycle_stage == 5
    assert envelope.correlation_id == "trading-e2e-1"
    assert envelope.trade_id == "trade-1"
    assert envelope.parameter_revision_id == "7"
    assert envelope.source_record_id == "trace-event-1"
    assert envelope.links["decisionId"] == "decision-1"
    assert envelope.links["traceId"] == "trading-e2e-1"
    assert envelope.availability["cycle_id"] == "NOT_CAPTURED"


def test_trace_unknown_stage_rejected():
    event = dict(TRACE_EVENT)
    event["stage"] = "NOT_A_STAGE"
    with pytest.raises(ValueError):
        trace_event_evidence(event)


# -- parameter revision -----------------------------------------------------


def test_parameter_revision_link_without_duplication():
    envelope = parameter_revision_evidence(_FakeParameterSet())
    assert envelope.evidence_type == "PARAMETER_REVISION"
    assert envelope.lifecycle_stage == 0
    assert envelope.mode == "PAPER"
    assert envelope.parameter_revision_id == "7"
    assert envelope.configuration_revision_id == "7"
    assert envelope.source_record_id == "strategy-params/PAPER"
    assert envelope.availability["cycle_id"] == "NOT_APPLICABLE"
    assert envelope.availability["trade_id"] == "NOT_APPLICABLE"
    # Never a second copy of the revision: digest + names only.
    assert "parameters" not in envelope.payload
    assert envelope.payload["parameterDigest"]
    assert envelope.payload["parameterNames"] == [
        "minimumCompositeScore",
        "minimumHoldMs",
    ]


def test_parameter_revision_both_scope_requires_mode():
    data = _FakeParameterSet().to_dict()
    data["scope"] = "BOTH"
    with pytest.raises(ValueError):
        parameter_revision_evidence(data)
    envelope = parameter_revision_evidence(data, mode="LIVE")
    assert envelope.mode == "LIVE"


# -- read-only guarantees ---------------------------------------------------


def test_adapters_do_not_mutate_inputs():
    before = {key: value for key, value in STAGE13_RECORD.items()}
    completed_trade_evidence(STAGE13_RECORD)
    assert STAGE13_RECORD == before

    trace_before = dict(TRACE_EVENT)
    trace_event_evidence(TRACE_EVENT)
    assert TRACE_EVENT == trace_before


def test_stage13_evidence_persists_and_reloads(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    envelope = completed_trade_evidence(STAGE13_RECORD)
    assert store.append(envelope).outcome is AppendOutcome.WRITTEN
    reloaded = CycleEvidenceStore(tmp_path / "ce.jsonl")
    rows = reloaded.query(trade_id="trade-1")["records"]
    assert len(rows) == 1
    assert rows[0]["links"]["sourceRecordId"] == "stage13-record-1"
    assert rows[0]["parameter_revision_id"] == "7"


def test_incomplete_record_is_not_persisted(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    with pytest.raises(ValueError):
        completed_trade_evidence({"symbol": "X"})
    assert store.load() == []
