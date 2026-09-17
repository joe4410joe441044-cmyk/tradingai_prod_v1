"""E-PERF-2 focused tests: Stage 13 parameter-performance record connection.

Covers:

- production STRATEGY event shape (``metadata.decisionInput.parameterAuthority``)
  linking to Stage 13;
- missing authority never fabricates a linkage;
- the entry position ``parameter_snapshot`` surviving into the closed record;
- canonical ``(scope, effectiveRevision)`` identity and full retained values;
- durable parameter revision history (reconstruct N after N+1 and after reload);
- durable completed-trade records across reload;
- PAPER/LIVE scoping;
- recording never changing parameter authority;
- mixed entry-snapshot vs dynamic-authority semantics.
"""

import pytest

from Bot.engine.execution_engine import ExecutionEngine

from backend.runtime.parameter_performance import (
    DYNAMIC_AUTHORITY_PARAMETERS,
    ENTRY_SNAPSHOT_PARAMETERS,
    ParameterPerformanceStore,
    build_completed_trade_record,
)
from backend.runtime.trading_trace import (
    TradingTraceStore,
    make_event,
    strategy_decision_snapshot,
)
from backend.strategy.parameters.registry import StrategyParameterRegistry
from backend.strategy.parameters.revision_archive import ParameterRevisionArchive
from backend.strategy.parameters.settings_service import (
    ParameterSettingsService,
    UpdateOutcome,
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
    "authorityStatus": "PERSISTED",
    "storeStatus": "VALID",
    "parameterSetStatus": "ACTIVE",
    "parameters": {
        "minimumCompositeScore": {"value": 0.4, "unit": "score"},
        "minimumHoldMs": {"value": 1500, "unit": "ms"},
    },
}


def _source_record(scope="PAPER"):
    authority = dict(ENTRY_AUTHORITY)
    authority["canonicalScope"] = scope
    authority["scope"] = "PAPER_ONLY" if scope == "PAPER" else "LIVE_ONLY"
    authority["parameterSetId"] = f"strategy-params/{scope}"
    record = {
        "tradeId": "trade-1",
        "mode": scope.lower(),
        "traceId": "trading-e2e-perf2",
        "symbol": "MOVEUSDT",
        "side": "BUY",
        "qty": 100.0,
        "entryPrice": 0.1,
        "exitPrice": 0.11,
        "pnl": 1.0,
        "reason": "TAKE_PROFIT",
        "openedAt": 1000.0,
        "closedAt": 1060.0,
    }
    ExecutionEngine._attach_position_parameter_context(
        record, {"parameter_snapshot": authority}
    )
    return record


# ---------------------------------------------------------------------------
# A / B : Stage 13 trace linkage production shape
# ---------------------------------------------------------------------------


def _production_strategy_metadata():
    return {
        "decision": "BUY",
        "confidence": 0.7,
        "executionAllowed": True,
        "decisionInput": strategy_decision_snapshot(
            {
                "liquidityInstabilityDebug": {
                    "parameterAuthority": dict(ENTRY_AUTHORITY)
                },
                "entryReadiness": {"conditions": []},
            }
        ),
    }


def test_stage13_links_production_decision_input_shape():
    store = TradingTraceStore()
    trace_id = "trading-e2e-perf2-prod"
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="BUY",
        metadata=_production_strategy_metadata(),
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="RESULT", status="CLOSED",
        metadata={"decision": "BUY", "netPnL": 1.0},
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="HISTORY", status="RECORDED",
        metadata={"tradeId": "trade-1", "positionId": "pos-1"},
    ))

    history = next(e for e in store.events(trace_id) if e["stage"] == "HISTORY")
    assert history["metadata"]["parameterRevision"] == 7
    assert history["metadata"]["parameterScope"] == "PAPER"

    performance = store.trace(trace_id)["parameterPerformance"]
    assert performance["parameterRevision"] == 7
    assert performance["parameterSetId"] == "strategy-params/PAPER"
    assert performance["featureContract"] == "TIME_SYMBOL_NORMALIZED_V1"
    assert performance["tradeId"] == "trade-1"


def test_stage13_missing_authority_never_fabricates_linkage():
    store = TradingTraceStore()
    trace_id = "trading-e2e-perf2-missing"
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="HOLD",
        metadata={"decisionInput": {"parameterAuthority": None}},
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="HISTORY", status="RECORDED",
        metadata={"tradeId": "trade-missing"},
    ))
    history = next(e for e in store.events(trace_id) if e["stage"] == "HISTORY")
    assert "parameterRevision" not in history["metadata"]
    assert store.trace(trace_id)["parameterPerformance"] is None


def test_stage13_prefers_decision_input_over_top_level():
    store = TradingTraceStore()
    trace_id = "trading-e2e-perf2-precedence"
    top_level = dict(ENTRY_AUTHORITY)
    top_level["effectiveRevision"] = 3
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="BUY",
        metadata={
            "parameterAuthority": top_level,
            "decisionInput": {"parameterAuthority": dict(ENTRY_AUTHORITY)},
        },
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="HISTORY", status="RECORDED",
        metadata={"tradeId": "trade-precedence"},
    ))
    performance = store.trace(trace_id)["parameterPerformance"]
    assert performance["parameterRevision"] == 7


# ---------------------------------------------------------------------------
# C / D / E : closed record parameter context
# ---------------------------------------------------------------------------


def test_position_parameter_snapshot_survives_into_closed_record():
    record = {"tradeId": "trade-1", "mode": "paper"}
    ExecutionEngine._attach_position_parameter_context(
        record, {"parameter_snapshot": dict(ENTRY_AUTHORITY)}
    )
    assert record["parameterSnapshot"]["effectiveRevision"] == 7
    assert record["parameterScope"] == "PAPER"
    assert record["parameterRevision"] == 7
    assert record["featureContract"] == "TIME_SYMBOL_NORMALIZED_V1"


def test_completed_record_retains_scope_and_revision_identity():
    completed = build_completed_trade_record(_source_record())
    assert completed["scope"] == "PAPER"
    assert completed["effectiveRevision"] == 7
    assert completed["parameterRevision"] == 7
    assert completed["parameterSetId"] == "strategy-params/PAPER"


def test_completed_record_retains_full_parameter_values():
    completed = build_completed_trade_record(_source_record())
    assert completed["parameterContextAvailable"] is True
    assert completed["parameterSnapshot"]["minimumCompositeScore"] == 0.4
    assert completed["parameterSnapshot"]["minimumHoldMs"] == 1500
    assert completed["parameterContext"]["featureContract"] == (
        "TIME_SYMBOL_NORMALIZED_V1"
    )
    assert completed["holdingMs"] == 60000.0
    assert completed["notional"] == pytest.approx(11.0)
    assert completed["realizedPnlAuthoritative"] is True


def test_completed_record_without_authority_is_marked_unavailable():
    completed = build_completed_trade_record({
        "tradeId": "trade-noauth",
        "mode": "paper",
        "symbol": "MOVEUSDT",
        "pnl": 1.0,
        "openedAt": 0.0,
        "closedAt": 1.0,
    })
    assert completed["parameterContextAvailable"] is False
    assert completed["parameterSnapshot"] is None
    assert completed["effectiveRevision"] is None
    assert completed["scope"] == "PAPER"


# ---------------------------------------------------------------------------
# F / G : durable parameter revision history
# ---------------------------------------------------------------------------


def _promote(service, scope, value):
    configuration = service.configuration(scope)
    parameters = dict(configuration["parameters"])
    parameters["minimumCompositeScore"] = value
    result = service.update_configuration(
        scope=scope,
        parameters=parameters,
        expected_revision=configuration["configuredRevision"],
    )
    assert result.outcome is UpdateOutcome.ACCEPTED, result.payload
    promotion = service.promote_if_safe(scope, safe_to_promote=True)
    assert promotion["outcome"] == "PROMOTED", promotion


def test_revision_archive_reconstructs_older_revision_after_newer(tmp_path):
    service = ParameterSettingsService(base_directory=tmp_path)
    _promote(service, "PAPER", 0.42)
    _promote(service, "PAPER", 0.55)

    archive = ParameterRevisionArchive(base_directory=tmp_path)
    revision_2 = archive.get("PAPER", 2)
    revision_3 = archive.get("PAPER", 3)
    assert revision_2 is not None
    assert revision_3 is not None
    assert revision_2.parameters["minimumCompositeScore"] == 0.42
    assert revision_3.parameters["minimumCompositeScore"] == 0.55
    assert [item.effectiveRevision for item in archive.revisions("PAPER")] == [2, 3]


def test_revision_archive_survives_repository_reload(tmp_path):
    service = ParameterSettingsService(base_directory=tmp_path)
    _promote(service, "PAPER", 0.42)
    _promote(service, "PAPER", 0.55)

    # Fresh archive instance simulates a process restart.
    reloaded = ParameterRevisionArchive(base_directory=tmp_path)
    assert reloaded.get("PAPER", 2).parameters["minimumCompositeScore"] == 0.42
    assert reloaded.get("PAPER", 3).parameters["minimumCompositeScore"] == 0.55
    # The live effective store still holds only the newest revision.
    assert service.effective("PAPER")["effectiveRevision"] == 3


# ---------------------------------------------------------------------------
# H / I : durable completed-trade records
# ---------------------------------------------------------------------------


def test_completed_record_store_survives_reload(tmp_path):
    path = tmp_path / "parameter_performance.jsonl"
    store = ParameterPerformanceStore(path)
    assert store.append(build_completed_trade_record(_source_record())) is True

    reloaded = ParameterPerformanceStore(path)
    rows = reloaded.load()
    assert len(rows) == 1
    assert rows[0]["effectiveRevision"] == 7
    assert rows[0]["parameterSnapshot"]["minimumCompositeScore"] == 0.4


def test_completed_record_history_scopes_paper_and_live(tmp_path):
    store = ParameterPerformanceStore(tmp_path / "parameter_performance.jsonl")
    store.append(build_completed_trade_record(_source_record("PAPER")))
    store.append(build_completed_trade_record(_source_record("LIVE")))

    assert len(store.history(scope="PAPER")) == 1
    assert len(store.history(scope="LIVE")) == 1
    assert store.history(scope="PAPER")[0]["scope"] == "PAPER"
    assert store.history(scope="LIVE")[0]["scope"] == "LIVE"


def test_completed_record_revision_summary(tmp_path):
    store = ParameterPerformanceStore(tmp_path / "parameter_performance.jsonl")
    store.append(build_completed_trade_record(_source_record()))
    store.append(build_completed_trade_record(_source_record()))
    summaries = store.revisions()
    assert len(summaries) == 1
    assert summaries[0]["effectiveRevision"] == 7
    assert summaries[0]["observedTradeCount"] == 2


# ---------------------------------------------------------------------------
# J : recording never changes authority
# ---------------------------------------------------------------------------


def test_recording_does_not_change_parameter_authority(tmp_path, monkeypatch):
    from backend.runtime import parameter_performance

    service = ParameterSettingsService(base_directory=tmp_path)
    before = service.effective("PAPER")

    monkeypatch.setattr(
        parameter_performance,
        "default_parameter_performance_store",
        lambda: ParameterPerformanceStore(tmp_path / "parameter_performance.jsonl"),
    )
    assert parameter_performance.record_completed_trade(_source_record()) is True
    assert service.effective("PAPER") == before


# ---------------------------------------------------------------------------
# Mixed semantics
# ---------------------------------------------------------------------------


def test_entry_and_dynamic_semantics_are_distinct_and_complete():
    registry = {item.name for item in StrategyParameterRegistry.PARAMETERS}
    entry = set(ENTRY_SNAPSHOT_PARAMETERS)
    dynamic = set(DYNAMIC_AUTHORITY_PARAMETERS)

    assert entry.isdisjoint(dynamic)
    assert entry | dynamic == registry

    completed = build_completed_trade_record(_source_record())
    assert completed["entrySnapshotParameters"] == list(ENTRY_SNAPSHOT_PARAMETERS)
    assert completed["dynamicAuthorityParameters"] == list(
        DYNAMIC_AUTHORITY_PARAMETERS
    )
    assert completed["parameterSnapshotSemantics"] == (
        "ENTRY_AUTHORITY_AT_DECISION_BOUNDARY"
    )
    assert "NOT frozen" in completed["parameterSemanticsNote"]
