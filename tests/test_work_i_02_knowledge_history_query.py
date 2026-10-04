"""WORK I② — shared read-only knowledge/history query foundation tests.

All storage is synthetic JSONL under ``tmp_path``; the Production trace
(``logs/runtime/trading_e2e_trace.jsonl``) is never read or written.  No test
performs a runtime/DB/exchange/LLM action.  The query layer is read-only, so
several tests assert that source files are byte-identical before/after.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from backend.runtime.cycle_evidence import (
    AVAILABILITY_TRACKED_FIELDS,
    build_envelope,
)
from backend.runtime.cycle_evidence_store import CycleEvidenceStore
from backend.runtime.knowledge_history_models import (
    ConsumerKind,
    KnowledgeHistoryCursorError,
    KnowledgeHistoryQuery,
    KnowledgeHistoryQueryError,
    KnowledgeHistorySecretError,
    MAX_QUERY_LIMIT,
)
from backend.runtime.knowledge_history_query import (
    KnowledgeHistoryQueryFacade,
    KnowledgeHistoryQueryService,
    consumer_capabilities,
    consumer_facade,
    default_knowledge_history_query_service,
    knowledge_history_consumers_enabled,
)
from backend.runtime.knowledge_history_sanitizer import sanitize_summary
from backend.runtime.knowledge_history_sources import (
    CycleEvidenceLinkResolver,
    CycleEvidenceSource,
    TradingTraceSource,
    source_catalog,
)
from backend.runtime.trading_trace import make_event, new_trace_id
from backend.runtime.trading_trace_reader import TradingTraceReader

RECORDED_AT = "2026-09-24T00:00:00.000000Z"


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
        source={"subsystem": "knowledge-history-test"},
        recorded_at=recorded_at,
        cycle_id=cycle_id,
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


def _write_cycle_evidence(path: Path, envelopes) -> CycleEvidenceStore:
    store = CycleEvidenceStore(path)
    for envelope in envelopes:
        store.append(envelope)
    return store


def _trace_event(
    trace_id,
    stage,
    status,
    *,
    mode="PAPER",
    symbol="BTCUSDT",
    timestamp=None,
    metadata=None,
):
    return make_event(
        trace_id=trace_id,
        mode=mode,
        stage=stage,
        status=status,
        symbol=symbol,
        runtime_id="runtime-1",
        decision_id="decision-1",
        metadata=metadata,
        timestamp=timestamp,
    ).to_dict()


def _write_trace(path: Path, events) -> TradingTraceReader:
    with path.open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    return TradingTraceReader(path)


def _service(ce_path: Path, trace_path: Path, **kwargs) -> KnowledgeHistoryQueryService:
    return KnowledgeHistoryQueryService(
        [CycleEvidenceSource(CycleEvidenceStore(ce_path)), TradingTraceSource(TradingTraceReader(trace_path))],
        **kwargs,
    )


# 1 ------------------------------------------------------------------- bounded


def test_cycle_evidence_bounded_query(tmp_path):
    store = _write_cycle_evidence(
        tmp_path / "ce.jsonl", [_envelope(f"cycle-{i}") for i in range(5)]
    )
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",), limit=2))
    assert result["returned_count"] == 2
    assert result["has_more"] is True
    assert result["next_cursor"]


def test_trading_trace_bounded_query(tmp_path):
    trace_id = new_trace_id()
    events = [_trace_event(trace_id, "STRATEGY", "BUY") for _ in range(5)]
    reader = _write_trace(tmp_path / "trace.jsonl", events)
    service = KnowledgeHistoryQueryService([TradingTraceSource(reader)])
    result = service.query(KnowledgeHistoryQuery(source=("TRADING_TRACE",), limit=2))
    assert result["returned_count"] == 2
    assert result["has_more"] is True
    assert all(item["source"] == "TRADING_TRACE" for item in result["items"])


# 2 --------------------------------------------------------------------- limit


def test_limit_is_upper_bounded(tmp_path):
    store = _write_cycle_evidence(
        tmp_path / "ce.jsonl", [_envelope(f"cycle-{i}") for i in range(5)]
    )
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",), limit=10_000))
    assert result["limit"] == MAX_QUERY_LIMIT


def test_invalid_limit_rejected(tmp_path):
    service = _service(tmp_path / "ce.jsonl", tmp_path / "trace.jsonl")
    with pytest.raises(KnowledgeHistoryQueryError):
        service.query(KnowledgeHistoryQuery(limit=0))


# 3 ----------------------------------------------------------- deterministic


def test_deterministic_ordering(tmp_path):
    store = _write_cycle_evidence(
        tmp_path / "ce.jsonl",
        [
            _envelope("c-b"),
            _envelope("c-a"),
            _envelope("c-c", recorded_at="2026-09-23T00:00:00.000000Z"),
        ],
    )
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    first = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    second = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    keys = [item["event_key"] for item in first["items"]]
    assert keys == [item["event_key"] for item in second["items"]]
    ordered = sorted(
        first["items"],
        key=lambda item: (item["captured_at"], item["event_key"]),
    )
    assert keys == [item["event_key"] for item in ordered]


# 4 ---------------------------------------------------------------- pagination


def test_cursor_pagination_walks_all_items(tmp_path):
    store = _write_cycle_evidence(
        tmp_path / "ce.jsonl", [_envelope(f"cycle-{i}") for i in range(5)]
    )
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    seen = []
    cursor = None
    for _ in range(10):
        result = service.query(
            KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",), limit=2, cursor=cursor)
        )
        seen.extend(item["event_key"] for item in result["items"])
        if not result["has_more"]:
            break
        cursor = result["next_cursor"]
    assert len(seen) == len(set(seen)) == 5


def test_malformed_cursor_rejected(tmp_path):
    store = _write_cycle_evidence(tmp_path / "ce.jsonl", [_envelope("c1")])
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    with pytest.raises(KnowledgeHistoryCursorError) as excinfo:
        service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",), cursor="!!!not-a-cursor!!!"))
    assert excinfo.value.code == "CURSOR_INVALID"


def test_cursor_query_mismatch_rejected(tmp_path):
    store = _write_cycle_evidence(
        tmp_path / "ce.jsonl", [_envelope("c1"), _envelope("c2")]
    )
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    first = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",), limit=1))
    with pytest.raises(KnowledgeHistoryCursorError) as excinfo:
        service.query(
            KnowledgeHistoryQuery(
                source=("CYCLE_EVIDENCE",), cycle_id="different", cursor=first["next_cursor"]
            )
        )
    assert excinfo.value.code == "CURSOR_QUERY_MISMATCH"


# 5 ---------------------------------------------------------- unsupported filter


def test_unsupported_filter_is_declared_not_ignored(tmp_path):
    service = _service(tmp_path / "ce.jsonl", tmp_path / "trace.jsonl")
    result = service.query(
        KnowledgeHistoryQuery(source=("TRADING_TRACE",), evidence_id="missing")
    )
    assert result["items"] == []
    assert result["partial_result"] is True
    filters = {(entry["source"], entry["filter"]) for entry in result["unsupported_filters"]}
    assert ("TRADING_TRACE", "evidence_id") in filters
    by_source = result["availability"]["by_source"]
    assert by_source["TRADING_TRACE"] == "UNSUPPORTED_FILTER"


# 6 -------------------------------------------------------------- missing source


def test_missing_source_is_not_fabricated(tmp_path):
    service = _service(tmp_path / "does-not-exist.jsonl", tmp_path / "trace.jsonl")
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    assert result["items"] == []
    assert result["partial_result"] is True
    assert result["availability"]["by_source"]["CYCLE_EVIDENCE"] == "NOT_AVAILABLE"


# 7 --------------------------------------------------------- corrupt isolation


def test_corrupt_record_is_isolated_not_returned(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = _write_cycle_evidence(path, [_envelope("c1")])
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{ this is not json }\n")
    store.append(_envelope("c2"))
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    assert result["returned_count"] == 2
    assert result["corruption_count"] == 1
    assert all(item["evidence_id"] for item in result["items"])


def test_corrupt_trace_record_isolated(tmp_path):
    path = tmp_path / "trace.jsonl"
    trace_id = new_trace_id()
    reader = _write_trace(path, [_trace_event(trace_id, "STRATEGY", "BUY")])
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
    service = KnowledgeHistoryQueryService([TradingTraceSource(reader)])
    result = service.query(KnowledgeHistoryQuery(source=("TRADING_TRACE",)))
    assert result["returned_count"] == 1
    assert result["corruption_count"] >= 1


# 8 -------------------------------------------------------------- partial result


def test_partial_result_when_one_source_missing(tmp_path):
    store = _write_cycle_evidence(tmp_path / "ce.jsonl", [_envelope("c1")])
    service = KnowledgeHistoryQueryService(
        [CycleEvidenceSource(store), TradingTraceSource(TradingTraceReader(tmp_path / "nope.jsonl"))]
    )
    result = service.query(KnowledgeHistoryQuery())
    assert result["returned_count"] == 1
    assert result["partial_result"] is True
    assert result["availability"]["overall"] == "PARTIAL"
    assert result["availability"]["by_source"]["TRADING_TRACE"] == "NOT_AVAILABLE"


# 9 ------------------------------------------------------------------- provenance


def test_provenance_present_for_every_source(tmp_path):
    store = _write_cycle_evidence(tmp_path / "ce.jsonl", [_envelope("c1")])
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    assert result["provenance"]
    record = result["provenance"][0]
    for field in ("source_type", "authority", "source_path", "read_method", "bounded_read", "integrity"):
        assert field in record
    assert record["bounded_read"] is True


# 10 ------------------------------------------------------------------- freshness


def _age_file(path: Path, seconds: float) -> None:
    when = time.time() - seconds
    os.utime(path, (when, when))


def test_freshness_fresh(tmp_path):
    store = _write_cycle_evidence(tmp_path / "ce.jsonl", [_envelope("c1")])
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    record = result["freshness"]["sources"][0]
    assert record["state"] == "FRESH"
    assert record["threshold_source"]
    assert result["freshness"]["overall"] == "FRESH"


def test_freshness_stale(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = _write_cycle_evidence(path, [_envelope("c1")])
    _age_file(path, 7200.0)
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    record = result["freshness"]["sources"][0]
    assert record["state"] == "STALE"
    assert record["reason"] == "AGE_EXCEEDS_MAX_AGE"
    # STALE history is returned, never discarded.
    assert result["returned_count"] == 1


def test_freshness_unknown(tmp_path):
    service = _service(tmp_path / "missing.jsonl", tmp_path / "trace.jsonl")
    result = service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    record = result["freshness"]["sources"][0]
    assert record["state"] == "UNKNOWN"


# 11 ----------------------------------------------------------- availability agg


def test_availability_aggregation(tmp_path):
    store = _write_cycle_evidence(tmp_path / "ce.jsonl", [_envelope("c1")])
    service = KnowledgeHistoryQueryService(
        [CycleEvidenceSource(store), TradingTraceSource(TradingTraceReader(tmp_path / "nope.jsonl"))]
    )
    result = service.query(KnowledgeHistoryQuery())
    assert result["availability"]["by_source"] == {
        "CYCLE_EVIDENCE": "AVAILABLE",
        "TRADING_TRACE": "NOT_AVAILABLE",
    }
    assert result["availability"]["overall"] == "PARTIAL"


# 12 --------------------------------------------------------------- link resolver


def test_link_resolution(tmp_path):
    store = _write_cycle_evidence(
        tmp_path / "ce.jsonl",
        [
            _envelope(
                "c1",
                trade_id="trade-1",
                correlation_id="trace-1",
                links={"traceId": "trace-1", "tradeId": "trade-1"},
            ),
            _envelope(
                "c1",
                trade_id="trade-2",
                correlation_id="trace-2",
                links={"traceId": "trace-2", "tradeId": "trade-2"},
            ),
        ],
    )
    resolver = CycleEvidenceLinkResolver(store)
    by_trace = resolver.resolve_by_evidence_id(store.load()[0]["evidence_id"])
    assert by_trace is not None
    assert by_trace["cycle_id"] == "c1"
    assert by_trace["links"]["traceId"] == "trace-1"
    by_cycle = resolver.resolve_by_cycle_id("c1")
    assert set(by_cycle["evidence_ids"]) == {row["evidence_id"] for row in store.load()}


def test_link_resolution_for_trace_event(tmp_path):
    resolver = CycleEvidenceLinkResolver(CycleEvidenceStore(tmp_path / "unused.jsonl"))
    event = _trace_event(new_trace_id(), "POSITION", "OPEN", metadata={"positionId": "pos-9"})
    envelope = resolver.project_trace_event(event)
    assert envelope is not None
    assert envelope["links"]["positionId"] == "pos-9"


# 13 ------------------------------------------------------------- dedup


class _FakeSource:
    def __init__(self, name, items):
        self.source = name
        self._items = items

    def read(self, query, *, limit, cursor):
        from backend.runtime.knowledge_history_sources import SourcePage

        return SourcePage(source=self.source, items=list(self._items[:limit]))


def test_duplicate_item_suppression(tmp_path):
    duplicate = {
        "source": "CYCLE_EVIDENCE",
        "event_key": "shared-key",
        "evidence_id": "ev-1",
        "cycle_id": "c1",
        "trace_id": None,
        "stage": 5,
        "stage_name": "AI_DECISION_REVIEW",
        "status": "BUY",
        "evidence_type": "AI_DECISION",
        "symbol": None,
        "mode": "PAPER",
        "captured_at": RECORDED_AT,
        "source_reference": {},
        "links": {},
        "payload": {},
        "availability": {},
        "provenance": {},
    }
    service = KnowledgeHistoryQueryService(
        [
            _FakeSource("CYCLE_EVIDENCE", [dict(duplicate)]),
            _FakeSource("TRADING_TRACE", [dict(duplicate)]),
        ]
    )
    result = service.query(KnowledgeHistoryQuery())
    assert result["returned_count"] == 1
    assert any("DEDUPLICATED" in warning for warning in result["warnings"])


# 14 --------------------------------------------------------------- secret policy


def test_secret_redaction():
    cleaned, redacted = sanitize_summary(
        {"api_key": "super-secret-value", "note": "token=abcdef123", "ok": 1}
    )
    assert redacted is True
    assert "api_key" not in cleaned
    assert "super-secret-value" not in json.dumps(cleaned)
    assert "token=abcdef123" not in json.dumps(cleaned)
    assert cleaned["ok"] == 1


def test_secret_reject_policy(tmp_path):
    service = _service(tmp_path / "ce.jsonl", tmp_path / "trace.jsonl")
    with pytest.raises(KnowledgeHistorySecretError):
        service.query(KnowledgeHistoryQuery(cycle_id="api_key=abc123"))


# 15 --------------------------------------------------------------- no I/O rules


def test_import_and_construction_perform_no_write(tmp_path):
    ce_path = tmp_path / "ce.jsonl"
    trace_path = tmp_path / "trace.jsonl"
    _service(ce_path, trace_path)
    assert not ce_path.exists()
    assert not trace_path.exists()
    # A lazy default service constructs adapters but must not create files.
    default_knowledge_history_query_service()
    assert not ce_path.exists()


def test_query_does_not_write(tmp_path):
    ce_path = tmp_path / "ce.jsonl"
    store = _write_cycle_evidence(ce_path, [_envelope("c1")])
    before = ce_path.read_bytes()
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    service.query(KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",)))
    assert ce_path.read_bytes() == before


def test_production_trace_path_not_used(tmp_path):
    trace_id = new_trace_id()
    trace_path = tmp_path / "trace.jsonl"
    reader = _write_trace(trace_path, [_trace_event(trace_id, "STRATEGY", "BUY")])
    service = KnowledgeHistoryQueryService([TradingTraceSource(reader)])
    result = service.query(KnowledgeHistoryQuery(source=("TRADING_TRACE",)))
    assert result["provenance"][0]["source_path"] == str(trace_path)
    assert "trading_e2e_trace" not in str(result["provenance"][0]["source_path"])


# 16 --------------------------------------------------------- shared consumers


def test_advisor_and_supervisor_share_one_service():
    advisor = consumer_facade(ConsumerKind.AI_ADVISOR)
    supervisor = consumer_facade(ConsumerKind.AI_SUPERVISOR)
    assert advisor.service is supervisor.service
    assert isinstance(advisor, KnowledgeHistoryQueryFacade)


def test_consumers_not_connected_to_production(tmp_path):
    import backend.runtime.knowledge_history_query as module

    assert not hasattr(module, "router")
    assert not hasattr(module, "app")
    capabilities = consumer_capabilities()
    for name in ("AI_ADVISOR", "AI_SUPERVISOR"):
        assert capabilities[name]["read_only"] is True
        assert capabilities[name]["writes"] is False
        assert capabilities[name]["api_route"] is None
    assert capabilities["AI_SUPERVISOR"]["scheduler_registration"] is False
    assert knowledge_history_consumers_enabled({}) is False
    # Phase A producer flag is independent and not enabled by this layer.
    assert os.environ.get("CYCLE_EVIDENCE_PHASE_A_ENABLED") in (None, "", "0", "false", "False")


# 17 ---------------------------------------------------------- no fabrication


def test_stage_6_to_14_not_fabricated(tmp_path):
    store = _write_cycle_evidence(tmp_path / "ce.jsonl", [_envelope("c1")])
    service = KnowledgeHistoryQueryService([CycleEvidenceSource(store)])
    for stage in range(6, 15):
        result = service.query(
            KnowledgeHistoryQuery(source=("CYCLE_EVIDENCE",), stage=stage)
        )
        assert result["items"] == []
        assert result["returned_count"] == 0


def test_source_catalog_is_read_only(tmp_path):
    for capability in source_catalog():
        assert capability["writable"] is False
        assert capability["bounded"] is True
