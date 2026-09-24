"""WORK I P0 focused tests: durable canonical cycle evidence store.

Covers idempotent append, conflict fail-closed, restart-safe retrieval, bounded
pagination, corrupt/truncated isolation and concurrent append safety.  All
storage is under ``tmp_path``; no production path is used.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.runtime.cycle_evidence import AVAILABILITY_TRACKED_FIELDS, build_envelope
from backend.runtime.cycle_evidence_store import (
    AppendOutcome,
    CycleEvidenceStore,
    DEFAULT_CYCLE_EVIDENCE_PATH,
)

RECORDED_AT = "2026-09-24T00:00:00.000000Z"


def av(**present):
    return {
        field: "NOT_CAPTURED"
        for field in AVAILABILITY_TRACKED_FIELDS
        if field not in present
    }


def make(cycle_id="cycle-1", trade_id="trade-1", *, recorded_at=RECORDED_AT, **overrides):
    kwargs = dict(
        evidence_type="AI_DECISION",
        mode="PAPER",
        source={"subsystem": "store-test"},
        recorded_at=recorded_at,
        cycle_id=cycle_id,
        trade_id=trade_id,
    )
    kwargs.update(overrides)
    if "availability" not in overrides:
        present = {
            key: value
            for key, value in kwargs.items()
            if key in AVAILABILITY_TRACKED_FIELDS and value is not None
        }
        kwargs["availability"] = av(**present)
    return build_envelope(**kwargs)


def test_default_path_is_not_used_by_tests(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    assert store.path != DEFAULT_CYCLE_EVIDENCE_PATH
    assert not store.path.exists()


def test_append_and_restart_reload(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    envelope = make(payload={"decision": "BUY"})
    assert store.append(envelope).outcome is AppendOutcome.WRITTEN

    reloaded = CycleEvidenceStore(path)
    rows = reloaded.load()
    assert len(rows) == 1
    assert rows[0]["evidence_id"] == envelope.evidence_id
    assert rows[0]["payload"] == {"decision": "BUY"}
    assert reloaded.get(envelope.evidence_id) == rows[0]


def test_idempotent_duplicate_append(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    first = make(recorded_at="2026-09-24T00:00:00.000000Z")
    second = make(recorded_at="2026-10-01T12:00:00.000000Z")
    assert store.append(first).outcome is AppendOutcome.WRITTEN
    result = store.append(second)
    assert result.outcome is AppendOutcome.DUPLICATE
    assert result.idempotent is True
    assert len(path.read_text().strip().splitlines()) == 1


def test_conflicting_content_fails_closed(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    store.append(make(payload={"value": 1}))
    conflict = store.append(make(payload={"value": 2}))
    assert conflict.outcome is AppendOutcome.CONFLICT
    assert len(path.read_text().strip().splitlines()) == 1
    assert store.load()[0]["payload"] == {"value": 1}


def test_rejected_invalid_envelope(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    result = store.append({"not": "an envelope"})
    assert result.outcome is AppendOutcome.REJECTED
    assert result.error
    assert store.load() == []


def test_bounded_pagination(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    for index in range(5):
        store.append(make(cycle_id=f"cycle-{index}"))
    page_one = store.query(limit=2)
    assert page_one["count"] == 2
    assert page_one["pagination"]["hasMore"] is True
    assert page_one["pagination"]["nextCursor"]
    page_two = store.query(limit=2, cursor=page_one["pagination"]["nextCursor"])
    assert page_two["count"] == 2
    assert {r["cycle_id"] for r in page_one["records"]}.isdisjoint(
        {r["cycle_id"] for r in page_two["records"]}
    )
    page_three = store.query(limit=2, cursor=page_two["pagination"]["nextCursor"])
    assert page_three["count"] == 1
    assert page_three["pagination"]["hasMore"] is False
    assert page_three["pagination"]["nextCursor"] is None


def test_query_limit_is_bounded(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl", max_query_limit=3)
    for index in range(5):
        store.append(make(cycle_id=f"cycle-{index}"))
    assert store.query(limit=1000)["count"] == 3


def test_query_filters(tmp_path):
    store = CycleEvidenceStore(tmp_path / "ce.jsonl")
    store.append(make(cycle_id="cycle-a", evidence_type="AI_DECISION"))
    store.append(
        make(
            cycle_id="cycle-b",
            evidence_type="FILL",
            mode="LIVE",
            symbol="MOVEUSDT",
        )
    )
    assert store.query(cycle_id="cycle-a")["count"] == 1
    assert store.query(evidence_type="FILL")["count"] == 1
    assert store.query(mode="LIVE")["count"] == 1
    assert store.query(symbol="moveusdt")["count"] == 1
    assert store.query(lifecycle_stage=8)["count"] == 1
    assert store.query(cycle_id="missing")["count"] == 0
    with pytest.raises(ValueError):
        store.query(cursor="../bad")


def test_corrupt_line_isolation(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    store.append(make(cycle_id="cycle-1"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{this is not json}\n")
        stream.write("]\n")
    store.append(make(cycle_id="cycle-2"))

    rows = store.load()
    assert [row["cycle_id"] for row in rows] == ["cycle-1", "cycle-2"]
    report = store.corruption_report()
    assert len(report) == 2
    assert all(item["reason"] for item in report)
    assert store.query()["count"] == 2


def test_truncated_final_record_is_isolated(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    store.append(make(cycle_id="cycle-1"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"schema_version":"evidence-envelope/v1","partial"')

    rows = store.load()
    assert [row["cycle_id"] for row in rows] == ["cycle-1"]
    report = store.corruption_report()
    assert report and report[-1]["reason"] == "TRUNCATED_FINAL_RECORD"
    assert store.query()["count"] == 1


def test_missing_file(tmp_path):
    store = CycleEvidenceStore(tmp_path / "does-not-exist.jsonl")
    assert store.load() == []
    assert store.query()["count"] == 0
    assert store.corruption_report() == []
    assert store.get("evidence-unknown") is None


def test_empty_file(tmp_path):
    path = tmp_path / "ce.jsonl"
    path.write_text("")
    store = CycleEvidenceStore(path)
    assert store.load() == []
    assert store.query()["count"] == 0


def test_concurrent_append_safety(tmp_path):
    path = tmp_path / "ce.jsonl"
    store = CycleEvidenceStore(path)
    total = 40
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda index: store.append(make(cycle_id=f"cycle-{index}")), range(total))
        )
    assert all(result.outcome is AppendOutcome.WRITTEN for result in results)
    rows = store.load()
    assert len(rows) == total
    assert len(set(row["evidence_id"] for row in rows)) == total


def test_concurrent_instances_do_not_duplicate(tmp_path):
    path = tmp_path / "ce.jsonl"
    envelope = make(cycle_id="cycle-shared")

    def attempt(_):
        return CycleEvidenceStore(path).append(envelope).outcome

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert outcomes.count(AppendOutcome.WRITTEN) == 1
    assert len(path.read_text().strip().splitlines()) == 1
