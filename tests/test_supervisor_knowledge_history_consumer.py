"""WORK I② — Supervisor read-only knowledge/history consumer wiring tests.

All storage targets are synthetic JSONL under ``tmp_path``.  The Production
trace (``logs/runtime/trading_e2e_trace.jsonl``) and the Production cycle
evidence store are never read or written.  No network, provider, scheduler,
runtime or persistence action is performed.
"""

from __future__ import annotations

import builtins
import inspect
import json
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.supervisor import create_supervisor_router
from backend.runtime.cycle_evidence import (
    AVAILABILITY_TRACKED_FIELDS,
    build_envelope,
)
from backend.runtime.cycle_evidence_store import CycleEvidenceStore
from backend.runtime.knowledge_history_models import MAX_QUERY_LIMIT
from backend.runtime.knowledge_history_query import (
    KnowledgeHistoryQueryFacade,
    KnowledgeHistoryQueryService,
    consumer_capabilities,
)
from backend.runtime.knowledge_history_sources import (
    CycleEvidenceSource,
    TradingTraceSource,
)
from backend.runtime.trading_trace import make_event, new_trace_id
from backend.runtime.trading_trace_reader import TradingTraceReader
from backend.supervisor.knowledge_history_consumer import (
    SUPERVISOR_QUERY_DEFAULT_LIMIT,
    SupervisorKnowledgeHistoryConsumer,
    plan_supervisor_query,
    supervisor_knowledge_history_enabled,
)
from backend.supervisor.provider_configuration import SupervisorProviderConfiguration
from backend.supervisor.runtime_snapshot_adapter import (
    RuntimeAuthorityReaders,
    RuntimeSnapshotAdapter,
)

NOW = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
RECORDED_AT = "2026-09-24T00:00:00.000000Z"
FLAG_ON = {"AI_SUPERVISOR_KNOWLEDGE_HISTORY_ENABLED": "1"}


# --------------------------------------------------------------------------- #
# synthetic canonical sources
# --------------------------------------------------------------------------- #


def _availability(**present):
    return {
        field: "NOT_CAPTURED"
        for field in AVAILABILITY_TRACKED_FIELDS
        if field not in present
    }


def _envelope(cycle_id="cycle-a", *, recorded_at=RECORDED_AT, **overrides):
    kwargs = dict(
        evidence_type="AI_DECISION",
        mode="PAPER",
        source={"subsystem": "supervisor-consumer-test"},
        recorded_at=recorded_at,
        cycle_id=cycle_id,
        symbol="BTCUSDT",
    )
    kwargs.update(overrides)
    if "availability" not in overrides:
        present = {
            key: value
            for key, value in kwargs.items()
            if key in AVAILABILITY_TRACKED_FIELDS and value is not None
        }
        kwargs["availability"] = _availability(**present)
    return build_envelope(**kwargs)


def _cycle_store(tmp_path: Path, cycle_ids=("cycle-a",)):
    path = tmp_path / "cycle_evidence.jsonl"
    store = CycleEvidenceStore(path)
    for cycle_id in cycle_ids:
        store.append(_envelope(cycle_id))
    return store, path


def _trace_reader(tmp_path: Path):
    path = tmp_path / "trace.jsonl"
    event = make_event(
        trace_id=new_trace_id(),
        mode="PAPER",
        stage="STRATEGY",
        status="BUY",
        symbol="BTCUSDT",
        runtime_id="runtime-1",
        decision_id="decision-1",
    ).to_dict()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    return TradingTraceReader(path), path


def _service(cycle_source, trace_source, **kwargs):
    return KnowledgeHistoryQueryService([cycle_source, trace_source], **kwargs)


class SpyFacade:
    def __init__(self, delegate=None, *, result=None, error=None):
        self._delegate = delegate
        self._result = result
        self._error = error
        self.calls = 0

    def query(self, query=None, **kwargs):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        if self._delegate is None:
            raise RuntimeError("spy query should not be called")
        return self._delegate.query(query, **kwargs)


def _consumer(facade=None, *, enabled=True, **kwargs):
    return SupervisorKnowledgeHistoryConsumer(
        facade=facade, environ=FLAG_ON if enabled else {}, **kwargs
    )


# --------------------------------------------------------------------------- #
# snapshots
# --------------------------------------------------------------------------- #


def _payloads(*, cycle_id="cycle-a", symbol="BTCUSDT", mode="PAPER"):
    return {
        "bot": {
            "timestamp": NOW,
            "botState": "RUNNING",
            "loopEnabled": True,
            "loopState": "RUNNING",
            "selectedMode": mode,
            "dryRun": True,
            "autoTradeEnabled": False,
            "realOrderAllowed": False,
            "accountSource": "PAPER_SIMULATION",
            "governance_state": {"mode": mode, "execution_enabled": False},
            "emergency": {"locked": False, "state": "READY"},
            "pendingOrderState": "NONE",
            "activeSymbol": symbol,
            "marketReady": True,
            "marketStale": False,
            "selectionMode": "AUTO",
            "autoMarketSelection": {
                "selectionCycleId": cycle_id,
                "activeSymbol": symbol,
            },
            "tradingDecision": {"status": "HOLD", "evaluatedAt": NOW},
        },
        "governance": {
            "sourceEvaluatedAt": NOW,
            "mode": mode,
            "execution_enabled": False,
            "risk_profile": "SAFE",
            "emergency_stop": False,
            "emergency_state": "READY",
        },
        "moneyManagement": {
            "generatedAt": NOW,
            "capitalEligibility": {
                "capitalAuthority": "MONEY_MANAGEMENT",
                "capitalSource": "PAPER",
                "equity": "1234.5",
                "availableCapital": "1200.0",
                "riskBudget": "12.0",
                "remainingExposure": "80.0",
                "remainingPositionCapacity": "2",
                "executionEntryAllowed": False,
                "evaluatedAt": NOW,
                "authorityFresh": True,
            },
            "metrics": {
                "drawdownPercent": "0.1",
                "openExposure": "20.0",
                "openPositionState": "NONE",
                "metricsGeneratedAt": NOW,
            },
        },
        "health": {"sourceEvaluatedAt": NOW, "status": "ok", "runtimeHealthy": True},
    }


def _adapter(values=None, *, now=NOW):
    values = values or _payloads()
    readers = RuntimeAuthorityReaders(
        bot=lambda _app, _at: values["bot"],
        governance=lambda _app, _at: values["governance"],
        moneyManagement=lambda _app, _at: values["moneyManagement"],
        health=lambda _app, _at: values["health"],
    )
    return RuntimeSnapshotAdapter(readers=readers, clock=lambda: now)


def _snapshot(values=None):
    return _adapter(values).build(None)


def _api(*, consumer=None, values=None):
    app = FastAPI()
    app.include_router(
        create_supervisor_router(
            _adapter(values),
            provider_configuration=SupervisorProviderConfiguration(),
            knowledge_history_consumer=consumer,
        )
    )
    return TestClient(app), app


def _canned_result(**overrides):
    result = {
        "query": {"cycle_id": "cycle-a", "cursor": None},
        "items": [
            {
                "source": "CYCLE_EVIDENCE",
                "event_key": "k1",
                "evidence_id": "ev-1",
                "cycle_id": "cycle-a",
                "trace_id": None,
                "stage": 3,
                "stage_name": "STRATEGY",
                "status": "BUY",
                "evidence_type": "AI_DECISION",
                "symbol": "BTCUSDT",
                "mode": "PAPER",
                "captured_at": RECORDED_AT,
                "payload": {"secret": "supersecretvalue"},
                "links": {"traceId": "t1"},
                "provenance": {"redacted": True, "source_path": "/home/private/ce.jsonl"},
            }
        ],
        "returned_count": 1,
        "limit": SUPERVISOR_QUERY_DEFAULT_LIMIT,
        "has_more": False,
        "sources": [
            {
                "source": "CYCLE_EVIDENCE",
                "availability": "AVAILABLE",
                "items_returned": 1,
                "corruption_count": 0,
                "bounded": True,
                "read_method": "CycleEvidenceStore.iter_records",
            }
        ],
        "provenance": [
            {
                "source_type": "CYCLE_EVIDENCE",
                "authority": "CycleEvidenceStore",
                "read_method": "iter_records",
                "bounded_read": True,
                "integrity": "VERIFIED",
                "source_path": "/home/private/ce.jsonl",
                "api_key": "SECRETKEYVALUE",
            }
        ],
        "freshness": {"overall": "FRESH", "sources": []},
        "availability": {"overall": "AVAILABLE", "by_source": {"CYCLE_EVIDENCE": "AVAILABLE"}},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
    }
    result.update(overrides)
    return result


# --------------------------------------------------------------------------- #
# 1 & 2 - flag OFF
# --------------------------------------------------------------------------- #


def test_flag_off_does_not_call_query_service():
    spy = SpyFacade()
    consumer = _consumer(spy, enabled=False)
    assert consumer.metadata_for_snapshot(_snapshot()) is None
    assert spy.calls == 0
    assert supervisor_knowledge_history_enabled({}) is False


def test_flag_off_preserves_existing_supervisor_result():
    plain, _ = _api(consumer=None)
    off, _ = _api(consumer=_consumer(_consumer_facade(), enabled=False))
    assert off.get("/api/supervisor/snapshot").text == plain.get(
        "/api/supervisor/snapshot"
    ).text
    assert "knowledgeHistory" not in off.get("/api/supervisor/snapshot").text


# --------------------------------------------------------------------------- #
# 3 - flag ON bounded query
# --------------------------------------------------------------------------- #


def test_flag_on_executes_bounded_query(tmp_path):
    store, _ = _cycle_store(tmp_path)
    trace_reader, _ = _trace_reader(tmp_path)
    service = _service(CycleEvidenceSource(store), TradingTraceSource(trace_reader))
    spy = SpyFacade(KnowledgeHistoryQueryFacade(service))
    metadata = _consumer(spy).metadata_for_snapshot(_snapshot())
    assert spy.calls == 1
    assert metadata["knowledge_history_used"] is True
    assert metadata["returned_count"] >= 1
    assert metadata["query_summary"]["filters"]["cycle_id"] == "cycle-a"


# --------------------------------------------------------------------------- #
# 4-9 - observation-input query planning
# --------------------------------------------------------------------------- #


def test_cycle_id_filter():
    plan = plan_supervisor_query(_snapshot())
    assert plan.query.cycle_id == "cycle-a"


def test_trace_id_filter():
    plan = plan_supervisor_query(_snapshot(), trace_id="trace-77")
    assert plan.query.trace_id == "trace-77"


def test_symbol_filter():
    plan = plan_supervisor_query(_snapshot())
    assert plan.query.symbol == "BTCUSDT"


def test_stage_filter():
    plan = plan_supervisor_query(_snapshot(), stage=3)
    assert plan.query.stage == 3


def test_mode_filter():
    plan = plan_supervisor_query(_snapshot())
    assert plan.query.mode == "PAPER"


def test_time_window_filter():
    plan = plan_supervisor_query(_snapshot(), time_window_seconds=3600.0)
    assert plan.query.time_from == "2026-09-24T00:00:00Z"
    assert plan.query.time_to == "2026-09-24T01:00:00Z"


def test_no_observation_scope_does_not_query():
    plan = plan_supervisor_query(
        _snapshot(_payloads(cycle_id=None, symbol=None))
    )
    assert plan.relevant is False
    assert plan.query is None


# --------------------------------------------------------------------------- #
# 10 & 11 - limits
# --------------------------------------------------------------------------- #


def test_bounded_default_limit(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["query_summary"]["requested_limit"] == SUPERVISOR_QUERY_DEFAULT_LIMIT
    assert metadata["query_summary"]["resolved_limit"] == SUPERVISOR_QUERY_DEFAULT_LIMIT
    assert metadata["query_summary"]["resolved_limit"] <= MAX_QUERY_LIMIT


def test_hard_maximum_is_respected(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
        max_limit=4,
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["query_summary"]["resolved_limit"] == 4


# --------------------------------------------------------------------------- #
# 12-20 - context assembly / warnings / sanitization
# --------------------------------------------------------------------------- #


def test_unsupported_filter_metadata():
    result = _canned_result(
        partial_result=True,
        unsupported_filters=[
            {"source": "TRADING_TRACE", "filter": "evidence_id", "reason": "SOURCE_CANNOT_EVALUATE_FILTER"}
        ],
    )
    metadata = _consumer(SpyFacade(result=result)).metadata_for_snapshot(_snapshot())
    assert metadata["unsupported_filters"][0]["filter"] == "evidence_id"
    assert metadata["partial_result"] is True


def test_sanitization_excludes_raw_payload_and_links():
    metadata = _consumer(SpyFacade(result=_canned_result())).metadata_for_snapshot(
        _snapshot()
    )
    item = metadata["items"][0]
    assert item["evidence_id"] == "ev-1"
    assert "payload" not in item
    assert "links" not in item


def test_secret_values_are_not_exposed():
    metadata = _consumer(SpyFacade(result=_canned_result())).metadata_for_snapshot(
        _snapshot()
    )
    rendered = json.dumps(metadata)
    for secret in ("supersecretvalue", "SECRETKEYVALUE", "/home/private"):
        assert secret not in rendered


def test_provenance_propagated():
    metadata = _consumer(SpyFacade(result=_canned_result())).metadata_for_snapshot(
        _snapshot()
    )
    record = metadata["provenance"][0]
    assert record["authority"]
    assert record["read_method"]
    assert "integrity" in record


def test_freshness_propagated():
    metadata = _consumer(SpyFacade(result=_canned_result())).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["freshness"]["overall"] == "FRESH"


def test_stale_is_declared(tmp_path):
    store, path = _cycle_store(tmp_path)
    when = time.time() - 7200.0
    os.utime(path, (when, when))
    service = _service(
        CycleEvidenceSource(CycleEvidenceStore(path)),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["freshness"]["overall"] == "STALE"


def test_availability_propagated(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["availability"]["by_source"]["CYCLE_EVIDENCE"] == "AVAILABLE"


def test_partial_result_declared(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "missing.jsonl")),
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["partial_result"] is True
    assert metadata["availability"]["overall"] == "PARTIAL"
    assert metadata["returned_count"] >= 1


def test_corruption_warning():
    metadata = _consumer(
        SpyFacade(result=_canned_result(corruption_count=2))
    ).metadata_for_snapshot(_snapshot())
    assert metadata["corruption_count"] == 2


# --------------------------------------------------------------------------- #
# 21-22 - context size / truncation
# --------------------------------------------------------------------------- #


def test_context_size_limit_and_truncated_flag():
    items = [
        {
            "source": "CYCLE_EVIDENCE",
            "event_key": f"key-{index}",
            "evidence_id": f"ev-{index}",
            "cycle_id": "cycle-a",
            "status": "BUY",
            "provenance": {"redacted": False},
        }
        for index in range(80)
    ]
    result = _canned_result(items=items, returned_count=80)
    metadata = _consumer(SpyFacade(result=result)).metadata_for_snapshot(_snapshot())
    assert metadata["truncated"] is True
    assert len(metadata["items"]) <= 12


# --------------------------------------------------------------------------- #
# 23-25 - failure isolation
# --------------------------------------------------------------------------- #


def test_total_query_failure_falls_back_safely():
    metadata = _consumer(SpyFacade(error=RuntimeError("boom"))).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["fallback"] is True
    assert metadata["knowledge_history_used"] is False
    assert metadata["uncertainty"] == "HIGH"


def test_partial_source_failure_keeps_other_source(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "missing.jsonl")),
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["returned_count"] >= 1
    assert metadata["partial_result"] is True


def test_evaluation_result_unchanged_on_query_failure():
    plain, _ = _api(consumer=None)
    failing, _ = _api(consumer=_consumer(SpyFacade(error=RuntimeError("boom"))))
    plain_body = json.loads(plain.get("/api/supervisor/snapshot").text)
    failing_body = json.loads(failing.get("/api/supervisor/snapshot").text)
    assert failing_body.pop("knowledgeHistory")["fallback"] is True
    assert failing_body == plain_body


def test_query_failure_metadata_fallback_is_auditable():
    metadata = _consumer(SpyFacade(error=RuntimeError("boom"))).metadata_for_snapshot(
        _snapshot()
    )
    assert metadata["reason"] == "QUERY_FAILED"


# --------------------------------------------------------------------------- #
# 26-32 - isolation / persistence / scheduler / notifications
# --------------------------------------------------------------------------- #


def test_no_evidence_write(tmp_path):
    store, path = _cycle_store(tmp_path)
    trace_reader, trace_path = _trace_reader(tmp_path)
    service = _service(CycleEvidenceSource(store), TradingTraceSource(trace_reader))
    before_ce = path.read_bytes()
    before_trace = trace_path.read_bytes()
    _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(_snapshot())
    assert path.read_bytes() == before_ce
    assert trace_path.read_bytes() == before_trace


def test_no_persistence_write():
    import re

    import backend.supervisor.knowledge_history_consumer as module

    source = inspect.getsource(module)
    assert "SupervisorAuditStore" not in source
    assert "sqlite3" not in source
    assert "psycopg" not in source
    assert "INSERT INTO" not in source
    assert re.search(r"open\([^)]*['\"][wa]", source) is None
    assert ".commit(" not in source


def test_no_runtime_write():
    import backend.supervisor.knowledge_history_consumer as module

    source = inspect.getsource(module)
    for forbidden in (
        "start_bot",
        "stop_bot",
        "submit_order",
        "place_order",
        "governance_state",
        "set_parameter",
    ):
        assert forbidden not in source


def test_no_background_task():
    import backend.supervisor.knowledge_history_consumer as module

    source = inspect.getsource(module)
    for forbidden in (
        "import asyncio",
        "import threading",
        "asyncio.",
        "threading.",
        "create_task",
        "Thread(",
        "Timer(",
    ):
        assert forbidden not in source


def test_scheduler_not_connected():
    capabilities = consumer_capabilities()
    assert capabilities["AI_SUPERVISOR"]["scheduler_registration"] is False
    assert capabilities["AI_SUPERVISOR"]["shared_service"] is True
    assert capabilities["AI_ADVISOR"]["shared_service"] is True


def test_no_notification():
    import backend.supervisor.knowledge_history_consumer as module

    source = inspect.getsource(module).lower()
    for forbidden in ("smtp", "email", "slack", "webhook", "websocket", "notify", "notification"):
        assert forbidden not in source


def test_no_advisor_conversation_access():
    import backend.supervisor.knowledge_history_consumer as module

    source = inspect.getsource(module)
    for forbidden in (
        "conversation_models",
        "conversation_contracts",
        "SupervisorConversationService",
        "prompt_builder",
        "AdvisorQuestionPlan",
        "classify_advisor_question",
    ):
        assert forbidden not in source


def test_same_shared_source_authority_as_advisor():
    from backend.runtime.knowledge_history_query import shared_knowledge_history_facade

    consumer = _consumer()
    assert consumer._resolve_facade().service is shared_knowledge_history_facade().service


# --------------------------------------------------------------------------- #
# 33-36 - I/O boundaries
# --------------------------------------------------------------------------- #


def test_no_startup_io():
    with (
        patch.object(builtins, "open", side_effect=AssertionError("open")),
        patch.object(socket, "socket", side_effect=AssertionError("network")),
    ):
        consumer = _consumer(_consumer_facade(), enabled=False)
        assert consumer.metadata_for_snapshot(_snapshot()) is None


def test_no_production_trace_access(tmp_path):
    store, path = _cycle_store(tmp_path)
    service = _service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    metadata = _consumer(KnowledgeHistoryQueryFacade(service)).metadata_for_snapshot(
        _snapshot()
    )
    rendered = json.dumps(metadata)
    assert "trading_e2e_trace" not in rendered
    assert str(path) not in rendered


def test_import_and_constructor_perform_no_io():
    spy = SpyFacade()
    with (
        patch.object(builtins, "open", side_effect=AssertionError("open")),
        patch.object(socket, "socket", side_effect=AssertionError("network")),
    ):
        consumer = _consumer(spy, enabled=False)
        assert consumer.metadata_for_snapshot(_snapshot()) is None
    assert spy.calls == 0


def test_constructor_does_not_query_even_when_enabled():
    spy = SpyFacade()
    consumer = _consumer(spy)
    assert spy.calls == 0
    assert consumer.enabled is True


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _consumer_facade(tmp_path: Path | None = None):
    """A facade over empty synthetic sources (never production paths)."""

    tmp_path = tmp_path or Path(os.environ.get("PYTEST_CURRENT_TEST_TMP", "/tmp/opencode/supervisor-empty"))
    store = CycleEvidenceStore(tmp_path / "ce.jsonl" if tmp_path else None)
    service = KnowledgeHistoryQueryService(
        [
            CycleEvidenceSource(store),
            TradingTraceSource(TradingTraceReader(tmp_path / "trace.jsonl")),
        ]
    )
    return KnowledgeHistoryQueryFacade(service)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
