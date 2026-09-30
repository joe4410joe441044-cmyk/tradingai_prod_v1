"""WORK I② — Advisor read-only knowledge/history consumer wiring tests.

Every storage target is synthetic JSONL under ``tmp_path``.  The Production
trace (``logs/runtime/trading_e2e_trace.jsonl``) and the Production cycle
evidence store are never read or written, no network is used and no provider is
called.  The shared query layer is read-only, so several tests assert the source
files are byte-identical before/after and that a disabled consumer calls
nothing at all.
"""

from __future__ import annotations

import builtins
import inspect
import json
import os
import socket
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.knowledge_history_consumer import (
    ADVISOR_CONTEXT_MAX_ITEMS,
    ADVISOR_QUERY_DEFAULT_LIMIT,
    AdvisorKnowledgeHistoryConsumer,
    AdvisorQuestionPlan,
    advisor_knowledge_history_enabled,
    assemble_knowledge_history_context,
    classify_advisor_question,
)
from backend.ai_advisor.mock_provider import MockAdvisorProvider, MockProviderFixture
from backend.ai_advisor.service_models import AdvisorServiceStatus
from backend.runtime.cycle_evidence import (
    AVAILABILITY_TRACKED_FIELDS,
    build_envelope,
)
from backend.runtime.cycle_evidence_store import CycleEvidenceStore
from backend.runtime.knowledge_history_models import (
    KnowledgeHistoryQuery,
    MAX_QUERY_LIMIT,
)
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
from tests.test_ai_advisor_api import client, headers, payload
from tests.test_ai_advisor_prompt_builder import make_request
from tests.test_ai_advisor_provider_contract import (
    capabilities,
    config,
    fixture_text,
    model_policy,
)
from tests.test_ai_advisor_service import service_input

RECORDED_AT = "2026-09-24T00:00:00.000000Z"
FLAG_ON = {"AI_ADVISOR_KNOWLEDGE_HISTORY_ENABLED": "1"}


# --------------------------------------------------------------------------- #
# synthetic canonical sources (never the production trace / evidence store)
# --------------------------------------------------------------------------- #


def _availability(**present):
    return {
        field: "NOT_CAPTURED"
        for field in AVAILABILITY_TRACKED_FIELDS
        if field not in present
    }


def _envelope(cycle_id="cycle-1", *, recorded_at=RECORDED_AT, **overrides):
    kwargs = dict(
        evidence_type="AI_DECISION",
        mode="PAPER",
        source={"subsystem": "advisor-consumer-test"},
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


def _cycle_store(tmp_path: Path, cycle_ids=("cycle-a",)) -> tuple[CycleEvidenceStore, Path]:
    path = tmp_path / "cycle_evidence.jsonl"
    store = CycleEvidenceStore(path)
    for cycle_id in cycle_ids:
        store.append(_envelope(cycle_id))
    return store, path


def _trace_reader(tmp_path: Path, *, name="trace.jsonl", events=1) -> tuple[TradingTraceReader, Path]:
    path = tmp_path / name
    trace_id = new_trace_id()
    with path.open("a", encoding="utf-8") as stream:
        for _ in range(events):
            event = make_event(
                trace_id=trace_id,
                mode="PAPER",
                stage="STRATEGY",
                status="BUY",
                symbol="BTCUSDT",
                runtime_id="runtime-1",
                decision_id="decision-1",
            ).to_dict()
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    return TradingTraceReader(path), path


def _query_service(cycle_source, trace_source, **kwargs) -> KnowledgeHistoryQueryService:
    return KnowledgeHistoryQueryService([cycle_source, trace_source], **kwargs)


class SpyFacade:
    """A facade that records whether a query was issued."""

    def __init__(self, delegate=None):
        self._delegate = delegate
        self.calls = 0

    def query(self, query=None, **kwargs):
        self.calls += 1
        if self._delegate is None:
            raise RuntimeError("spy query should not be called")
        return self._delegate.query(query, **kwargs)


def _advisor_service(consumer=None, *, response_text=None) -> AdvisorService:
    provider = MockAdvisorProvider(
        MockProviderFixture(responseText=response_text or fixture_text())
    )
    return AdvisorService(
        provider=provider,
        providerConfig=config(),
        modelPolicy=model_policy(),
        capabilities=capabilities(),
        knowledgeHistoryConsumer=consumer,
    )


def _consumer(facade=None, *, enabled=True) -> AdvisorKnowledgeHistoryConsumer:
    return AdvisorKnowledgeHistoryConsumer(
        facade=facade, environ=FLAG_ON if enabled else {}
    )


def _cycle_service_input(message: str):
    request, _ = make_request(message=message)
    return service_input(request=request)


# --------------------------------------------------------------------------- #
# 1 & 2 - flag OFF
# --------------------------------------------------------------------------- #


def test_flag_off_does_not_call_query_service(tmp_path):
    spy = SpyFacade()
    consumer = _consumer(spy, enabled=False)
    assert consumer.metadata_for_message("cycle_id=cycle-a の判断理由") is None
    assert spy.calls == 0
    assert advisor_knowledge_history_enabled({}) is False


def test_flag_off_advisor_result_has_no_knowledge_history():
    result = _advisor_service(_consumer(enabled=False)).generate_response(
        _cycle_service_input("Why was there no ENTRY for cycle-a?")
    )
    assert result.status is AdvisorServiceStatus.SUCCEEDED
    assert result.knowledgeHistory is None


def test_flag_off_api_response_shape_is_unchanged():
    api, _, _ = client(service_dependency=_advisor_service(_consumer(enabled=False)))
    response = api.post(
        "/api/ai-advisor/advice",
        content=json.dumps(payload()),
        headers=headers(),
    )
    assert response.status_code == 200
    assert "knowledgeHistory" not in response.json()


# --------------------------------------------------------------------------- #
# 3 & 4 - flag ON query planning
# --------------------------------------------------------------------------- #


def test_flag_on_history_question_runs_query(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _query_service(CycleEvidenceSource(store), TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")))
    spy = SpyFacade(KnowledgeHistoryQueryFacade(service))
    consumer = _consumer(spy)
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の判断理由")
    assert spy.calls == 1
    assert metadata["knowledge_history_used"] is True
    assert metadata["returned_count"] >= 1


def test_flag_on_non_history_question_does_not_query():
    spy = SpyFacade()
    consumer = _consumer(spy)
    metadata = consumer.metadata_for_message("How do I open the settings page?")
    assert metadata["knowledge_history_used"] is False
    assert spy.calls == 0


def test_advisor_service_flag_on_attaches_metadata(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _query_service(CycleEvidenceSource(store), TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")))
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    result = _advisor_service(consumer).generate_response(
        _cycle_service_input("cycle_id=cycle-a の判断理由を教えて")
    )
    assert result.status is AdvisorServiceStatus.SUCCEEDED
    assert result.knowledgeHistory is not None
    assert result.knowledgeHistory["knowledge_history_used"] is True


# --------------------------------------------------------------------------- #
# 5-8 - question classification / safe extraction
# --------------------------------------------------------------------------- #


def test_cycle_id_extraction():
    plan = classify_advisor_question("Why was there no ENTRY for cycle-abc123?")
    assert plan.relevant is True
    assert plan.query.cycle_id == "cycle-abc123"


def test_trace_id_extraction():
    plan = classify_advisor_question("trace_id=trace-77 の経緯を教えて")
    assert plan.query.trace_id == "trace-77"


def test_evidence_id_extraction():
    plan = classify_advisor_question("evidence_id=ev-123 の証跡とは")
    assert plan.query.evidence_id == "ev-123"


def test_symbol_extraction():
    plan = classify_advisor_question("symbol=BTCUSDT の最近の decision は?")
    assert plan.query.symbol == "BTCUSDT"


def test_stage_and_time_extraction():
    plan = classify_advisor_question(
        "stage=3 の decision を 2026-09-20T00:00:00Z から "
        "2026-09-21T00:00:00Z まで"
    )
    assert plan.query.stage == 3
    assert plan.query.time_from == "2026-09-20T00:00:00Z"
    assert plan.query.time_to == "2026-09-21T00:00:00Z"


def test_unparseable_filters_are_not_silently_narrowed():
    plan = classify_advisor_question("stage=99 の decision")
    assert plan.query.stage is None
    assert "STAGE_OUT_OF_RANGE" in plan.notes


# --------------------------------------------------------------------------- #
# 9 & 10 - bounded limit / hard maximum
# --------------------------------------------------------------------------- #


def test_bounded_default_limit(tmp_path):
    store, _ = _cycle_store(tmp_path)
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["query_summary"]["requested_limit"] == ADVISOR_QUERY_DEFAULT_LIMIT
    assert metadata["query_summary"]["resolved_limit"] == ADVISOR_QUERY_DEFAULT_LIMIT
    assert metadata["query_summary"]["resolved_limit"] <= MAX_QUERY_LIMIT


def test_hard_maximum_is_respected(tmp_path):
    store, _ = _cycle_store(tmp_path, ("cycle-a",))
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
        max_limit=4,
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["query_summary"]["resolved_limit"] == 4


# --------------------------------------------------------------------------- #
# 11 & 12 - sanitized context / secrets
# --------------------------------------------------------------------------- #


def test_context_is_sanitized_and_bounded():
    raw = {
        "query": {"cycle_id": "c1", "cursor": None},
        "items": [
            {
                "source": "CYCLE_EVIDENCE",
                "event_key": "k1",
                "evidence_id": "ev-1",
                "cycle_id": "c1",
                "trace_id": None,
                "stage": 3,
                "stage_name": "STRATEGY",
                "status": "BUY",
                "evidence_type": "AI_DECISION",
                "symbol": "BTCUSDT",
                "mode": "PAPER",
                "captured_at": RECORDED_AT,
                "payload": {"huge": "x" * 5000},
                "links": {"traceId": "t1"},
                "provenance": {"redacted": False},
            }
        ],
        "returned_count": 1,
        "limit": 8,
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
            }
        ],
        "freshness": {"overall": "FRESH", "sources": []},
        "availability": {"overall": "AVAILABLE", "by_source": {"CYCLE_EVIDENCE": "AVAILABLE"}},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
    }
    plan = AdvisorQuestionPlan(True, "HISTORY_RELEVANT", KnowledgeHistoryQuery(cycle_id="c1", limit=8))
    context = assemble_knowledge_history_context(raw, plan)
    assert context["knowledge_history_used"] is True
    assert context["items"][0]["evidence_id"] == "ev-1"
    assert "payload" not in context["items"][0]
    assert "links" not in context["items"][0]
    assert "x" * 100 not in json.dumps(context)


def test_secret_values_are_not_exposed():
    raw = {
        "query": {"cycle_id": "c1"},
        "items": [
            {
                "source": "CYCLE_EVIDENCE",
                "event_key": "k1",
                "evidence_id": "ev-1",
                "payload": {"token": "supersecretvalue"},
                "provenance": {"redacted": True, "source_path": "/home/private/ce.jsonl"},
            }
        ],
        "returned_count": 1,
        "limit": 8,
        "sources": [],
        "provenance": [
            {
                "source_type": "CYCLE_EVIDENCE",
                "source_path": "/home/private/ce.jsonl",
                "api_key": "SECRETKEYVALUE",
                "authority": "CycleEvidenceStore",
            }
        ],
        "freshness": {},
        "availability": {},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
    }
    plan = AdvisorQuestionPlan(True, "HISTORY_RELEVANT", KnowledgeHistoryQuery(cycle_id="c1"))
    context = assemble_knowledge_history_context(raw, plan)
    rendered = json.dumps(context)
    for secret in ("supersecretvalue", "SECRETKEYVALUE", "/home/private"):
        assert secret not in rendered


# --------------------------------------------------------------------------- #
# 13-15 - provenance / freshness / availability propagation
# --------------------------------------------------------------------------- #


def _metadata_for(tmp_path, message="cycle_id=cycle-a の理由", **svc_kwargs):
    store, path = _cycle_store(tmp_path, ("cycle-a",))
    trace_path = tmp_path / "trace.jsonl"
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(trace_path)),
        **svc_kwargs,
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    return consumer.metadata_for_message(message), path


def test_provenance_propagated(tmp_path):
    metadata, _ = _metadata_for(tmp_path)
    assert metadata["provenance"]
    record = metadata["provenance"][0]
    assert record["authority"]
    assert record["read_method"]
    assert "integrity" in record


def test_freshness_propagated(tmp_path):
    metadata, _ = _metadata_for(tmp_path)
    assert metadata["freshness"]["overall"] in {"FRESH", "STALE", "UNKNOWN"}


def test_availability_propagated(tmp_path):
    metadata, _ = _metadata_for(tmp_path)
    assert metadata["availability"]["by_source"]["CYCLE_EVIDENCE"] == "AVAILABLE"


def test_stale_is_declared(tmp_path):
    metadata, path = _metadata_for(tmp_path)
    when = time.time() - 7200.0
    os.utime(path, (when, when))
    store = CycleEvidenceStore(path)
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["freshness"]["overall"] == "STALE"
    assert metadata["returned_count"] >= 1


# --------------------------------------------------------------------------- #
# 16-18 - partial result / unsupported filter / corruption
# --------------------------------------------------------------------------- #


def test_partial_result_is_declared(tmp_path):
    store, _ = _cycle_store(tmp_path, ("cycle-a",))
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "missing.jsonl")),
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["partial_result"] is True
    assert metadata["availability"]["overall"] == "PARTIAL"
    assert metadata["returned_count"] >= 1


def test_source_failure_keeps_other_source(tmp_path):
    store, _ = _cycle_store(tmp_path, ("cycle-a",))
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "missing.jsonl")),
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["returned_count"] >= 1


def test_unsupported_filter_is_declared(tmp_path):
    store, _ = _cycle_store(tmp_path, ("cycle-a",))
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("evidence_id=ev-missing の証跡")
    filters = {(entry["source"], entry["filter"]) for entry in metadata["unsupported_filters"]}
    assert ("TRADING_TRACE", "evidence_id") in filters
    assert metadata["partial_result"] is True


def test_corrupt_source_warning(tmp_path):
    store, path = _cycle_store(tmp_path, ("cycle-a",))
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{ not valid json }\n")
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["corruption_count"] >= 1


# --------------------------------------------------------------------------- #
# 19-21 - context size / truncation
# --------------------------------------------------------------------------- #


def test_context_size_limit_and_truncated_flag():
    raw = {
        "query": {},
        "items": [
            {
                "source": "CYCLE_EVIDENCE",
                "event_key": f"key-{index}",
                "evidence_id": f"ev-{index}",
                "cycle_id": "c1",
                "status": "BUY",
                "provenance": {"redacted": False},
            }
            for index in range(80)
        ],
        "returned_count": 80,
        "limit": 8,
        "sources": [],
        "provenance": [],
        "freshness": {},
        "availability": {},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
    }
    plan = AdvisorQuestionPlan(True, "HISTORY_RELEVANT", KnowledgeHistoryQuery(limit=8))
    context = assemble_knowledge_history_context(raw, plan, max_characters=800)
    assert context["truncated"] is True
    assert len(context["items"]) <= ADVISOR_CONTEXT_MAX_ITEMS
    assert len(json.dumps(context, ensure_ascii=True, default=str).encode("utf-8")) <= 800


def test_truncated_when_more_items_than_budget():
    raw = {
        "query": {},
        "items": [{"source": "CYCLE_EVIDENCE", "event_key": f"k{i}"} for i in range(ADVISOR_CONTEXT_MAX_ITEMS + 5)],
        "returned_count": ADVISOR_CONTEXT_MAX_ITEMS + 5,
        "limit": 8,
        "sources": [],
        "provenance": [],
        "freshness": {},
        "availability": {},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
    }
    plan = AdvisorQuestionPlan(True, "HISTORY_RELEVANT", KnowledgeHistoryQuery(limit=8))
    context = assemble_knowledge_history_context(raw, plan)
    assert context["truncated"] is True
    assert len(context["items"]) == ADVISOR_CONTEXT_MAX_ITEMS


# --------------------------------------------------------------------------- #
# 22 - total query failure fallback
# --------------------------------------------------------------------------- #


def test_query_failure_falls_back_safely():
    consumer = _consumer(SpyFacade())
    metadata = consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert metadata["fallback"] is True
    assert metadata["knowledge_history_used"] is False
    assert metadata["uncertainty"] == "HIGH"


def test_service_survives_query_failure():
    result = _advisor_service(_consumer(SpyFacade())).generate_response(
        _cycle_service_input("cycle_id=cycle-a の理由")
    )
    assert result.status is AdvisorServiceStatus.SUCCEEDED
    assert result.knowledgeHistory["fallback"] is True


# --------------------------------------------------------------------------- #
# 23-25 - mock provider / no network / no writes
# --------------------------------------------------------------------------- #


def test_provider_is_mock_and_no_network(tmp_path):
    store, _ = _cycle_store(tmp_path, ("cycle-a",))
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    advisor = _advisor_service(_consumer(KnowledgeHistoryQueryFacade(service)))
    with patch.object(socket, "socket", side_effect=AssertionError("network")):
        result = advisor.generate_response(
            _cycle_service_input("cycle_id=cycle-a の理由")
        )
    assert result.status is AdvisorServiceStatus.SUCCEEDED


def test_no_evidence_write(tmp_path):
    store, path = _cycle_store(tmp_path, ("cycle-a",))
    trace_reader, trace_path = _trace_reader(tmp_path)
    service = _query_service(CycleEvidenceSource(store), TradingTraceSource(trace_reader))
    consumer = _consumer(KnowledgeHistoryQueryFacade(service))
    before_ce = path.read_bytes()
    before_trace = trace_path.read_bytes()
    consumer.metadata_for_message("cycle_id=cycle-a の理由")
    assert path.read_bytes() == before_ce
    assert trace_path.read_bytes() == before_trace


# --------------------------------------------------------------------------- #
# 26-30 - isolation, persistence, supervision, constructor I/O
# --------------------------------------------------------------------------- #


def test_conversation_is_not_double_saved():
    value = _cycle_service_input("cycle_id=cycle-a の理由")
    before = value.model_dump_json()
    _advisor_service(_consumer()).generate_response(value)
    assert value.model_dump_json() == before


def test_supervisor_not_connected():
    import backend.ai_advisor.knowledge_history_consumer as module

    source = inspect.getsource(module).lower()
    assert "ai_supervisor" not in source
    assert "consumer_facade" not in source
    capabilities_map = consumer_capabilities()
    assert capabilities_map["AI_SUPERVISOR"]["scheduler_registration"] is False
    assert capabilities_map["AI_ADVISOR"]["shared_service"] is True


def test_import_and_constructor_perform_no_io(tmp_path):
    spy = SpyFacade()
    with (
        patch.object(builtins, "open", side_effect=AssertionError("open")),
        patch.object(socket, "socket", side_effect=AssertionError("network")),
    ):
        consumer = _consumer(spy)
        assert consumer.metadata_for_message("How do I open the settings page?")["knowledge_history_used"] is False
    assert spy.calls == 0


def test_constructor_does_not_query_even_when_enabled():
    spy = SpyFacade()
    consumer = _consumer(spy)
    assert spy.calls == 0
    assert consumer.enabled is True


# --------------------------------------------------------------------------- #
# API backward-compatible projection when enabled
# --------------------------------------------------------------------------- #


def test_api_projects_knowledge_history_when_enabled(tmp_path):
    store, _ = _cycle_store(tmp_path, ("cycle-a",))
    service = _query_service(
        CycleEvidenceSource(store),
        TradingTraceSource(TradingTraceReader(tmp_path / "none.jsonl")),
    )
    advisor = _advisor_service(_consumer(KnowledgeHistoryQueryFacade(service)))
    api, _, _ = client(service_dependency=advisor)
    request, _ = make_request(message="cycle_id=cycle-a の判断理由")
    body = {"serviceInput": service_input(request=request).model_dump(mode="json")}
    response = api.post(
        "/api/ai-advisor/advice",
        content=json.dumps(body),
        headers=headers(),
    )
    assert response.status_code == 200
    assert "knowledgeHistory" in response.json()
    assert response.json()["knowledgeHistory"]["knowledge_history_used"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
