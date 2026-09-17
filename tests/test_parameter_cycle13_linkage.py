"""E-PARAM-5 focused tests: Cycle 13 parameter-performance linkage.

Cycle 13 (Trade / Parameter Performance Record) must record the parameter
revision the trade ENTERED with, sourced from the entry runtime snapshot, never
from the latest configured/effective revision at close time.
"""

from backend.runtime.trading_trace import (
    TradingTraceStore,
    entry_parameter_metadata,
    make_event,
    parameter_authority_metadata,
    strategy_decision_snapshot,
)

ENTRY_AUTHORITY = {
    "scope": "PAPER_ONLY",
    "canonicalScope": "PAPER",
    "parameterSetId": "strategy-params/PAPER",
    "configuredRevision": 7,
    "effectiveRevision": 7,
    "source": "PARAMETER_SETTINGS",
    "featureContract": "TIME_SYMBOL_NORMALIZED_V1",
    "capturedAt": "2026-09-16T00:00:00.000000Z",
    "parameters": {
        "minimumCompositeScore": {"value": 0.4, "unit": "score"},
    },
}


def _strategy_state(authority):
    return {
        "liquidityInstabilityDebug": {"parameterAuthority": dict(authority)},
        "entryReadiness": {"conditions": []},
    }


def test_parameter_authority_metadata_extracts_entry_revision():
    metadata = parameter_authority_metadata(ENTRY_AUTHORITY)
    assert metadata["parameterRevision"] == 7
    assert metadata["parameterSetId"] == "strategy-params/PAPER"
    assert metadata["parameterScope"] == "PAPER"
    assert metadata["featureContract"] == "TIME_SYMBOL_NORMALIZED_V1"
    assert metadata["configuredRevision"] == 7
    assert metadata["effectiveRevision"] == 7
    assert "parameters" not in metadata


def test_parameter_authority_metadata_ignores_non_mapping():
    assert parameter_authority_metadata(None) == {}
    assert parameter_authority_metadata("nope") == {}


def test_strategy_decision_snapshot_exposes_parameter_revision():
    snapshot = strategy_decision_snapshot(_strategy_state(ENTRY_AUTHORITY))
    authority = snapshot["parameterAuthority"]
    assert authority["parameterRevision"] == 7
    assert authority["parameterScope"] == "PAPER"
    assert authority["parameterSetId"] == "strategy-params/PAPER"
    assert authority["effectiveRevision"] == 7


def test_history_record_preserves_entry_revision_after_effective_changes():
    store = TradingTraceStore()
    trace_id = "trading-e2e-cycle13-entry"
    strategy_snapshot = strategy_decision_snapshot(
        _strategy_state(ENTRY_AUTHORITY)
    )
    # Production shape: ExecutionRuntime nests the snapshot under decisionInput.
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="BUY",
        metadata={"decision": "BUY", "decisionInput": strategy_snapshot},
    ))

    # Later the operator promotes a new effective revision (R8); the completed
    # trade must still be linked to the revision it entered with (R7).
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="RESULT", status="CLOSED",
        metadata={"decision": "BUY", "netPnL": 1.0},
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="HISTORY", status="RECORDED",
        metadata={"tradeId": "trade-1", "positionId": "pos-1"},
    ))

    events = store.events(trace_id)
    history = next(e for e in events if e["stage"] == "HISTORY")
    metadata = history["metadata"]
    assert metadata["parameterRevision"] == 7
    assert metadata["parameterSetId"] == "strategy-params/PAPER"
    assert metadata["parameterScope"] == "PAPER"
    assert metadata["featureContract"] == "TIME_SYMBOL_NORMALIZED_V1"
    assert metadata["parameter"]["parameterRevision"] == 7

    trace = store.trace(trace_id)
    performance = trace["parameterPerformance"]
    assert performance["parameterRevision"] == 7
    assert performance["parameterSetId"] == "strategy-params/PAPER"
    assert performance["parameterScope"] == "PAPER"
    assert performance["featureContract"] == "TIME_SYMBOL_NORMALIZED_V1"
    assert performance["tradeId"] == "trade-1"


def test_entry_parameter_metadata_reads_strategy_event():
    store = TradingTraceStore()
    trace_id = "trading-e2e-cycle13-legacy"
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="HOLD",
        metadata={
            "decision": "HOLD",
            "decisionInput": strategy_decision_snapshot(
                _strategy_state(ENTRY_AUTHORITY)
            ),
        },
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="HISTORY", status="RECORDED",
        metadata={"tradeId": "trade-legacy"},
    ))
    linkage = entry_parameter_metadata(store.events(trace_id))
    assert linkage["parameterRevision"] == 7
    assert linkage["parameterScope"] == "PAPER"


def test_entry_parameter_metadata_accepts_legacy_top_level_shape():
    """Backward compatibility: the pre-E-PERF-2 top-level metadata shape.

    Production shape (``metadata.decisionInput.parameterAuthority``) is primary
    and takes precedence when both shapes are present.
    """

    store = TradingTraceStore()
    trace_id = "trading-e2e-cycle13-legacy-top-level"
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="HOLD",
        metadata=strategy_decision_snapshot(_strategy_state(ENTRY_AUTHORITY)),
    ))
    linkage = entry_parameter_metadata(store.events(trace_id))
    assert linkage["parameterRevision"] == 7
    assert linkage["parameterScope"] == "PAPER"


def test_trace_without_parameter_authority_has_no_linkage():
    store = TradingTraceStore()
    trace_id = "trading-e2e-cycle13-none"
    store.record(make_event(
        trace_id=trace_id, mode="LIVE", stage="STRATEGY", status="HOLD",
        metadata={"strategy": {}},
    ))
    store.record(make_event(
        trace_id=trace_id, mode="LIVE", stage="HISTORY", status="RECORDED",
        metadata={"tradeId": "trade-none"},
    ))
    assert store.trace(trace_id)["parameterPerformance"] is None
