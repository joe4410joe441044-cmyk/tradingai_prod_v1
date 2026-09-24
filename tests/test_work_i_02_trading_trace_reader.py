"""WORK I② P0 — restart-safe trading trace reader tests.

All tests use temporary synthetic files; the Production trace is never used or
written.  No test performs any runtime/DB/exchange action.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from backend.runtime.trading_trace import make_event, new_trace_id
from backend.runtime.trading_trace_reader import (
    TradingTraceReader,
    TraceCursorError,
    _encode_cursor,
)


def _event(
    trace_id: str,
    stage: str,
    status: str,
    *,
    mode: str = "PAPER",
    reason: str | None = None,
    timestamp: str | None = None,
    symbol: str | None = "BTCUSDT",
    metadata: dict | None = None,
) -> dict:
    return make_event(
        trace_id=trace_id,
        mode=mode,
        stage=stage,
        status=status,
        symbol=symbol,
        runtime_id="runtime-1",
        decision_id="decision-1",
        reason_code=reason,
        metadata=metadata,
        timestamp=timestamp,
    ).to_dict()


def _append(path: Path, records) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            if isinstance(record, str):
                stream.write(record)
            else:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _trace(trace_id: str, *, mode: str = "PAPER", cycle: str | None = None) -> list[dict]:
    metadata = {"rankingCycleId": cycle} if cycle else None
    return [
        _event(trace_id, "STRATEGY", "BUY", mode=mode, metadata=metadata),
        _event(trace_id, "GOVERNANCE", "ALLOW", mode=mode),
        _event(trace_id, "EXECUTION", "PAPER_FILLED", mode=mode),
        _event(trace_id, "POSITION", "OPEN", mode=mode),
        _event(trace_id, "RESULT", "EXECUTED", mode=mode, metadata={"decision": "BUY", "netPnL": 1.5}),
    ]


def test_restart_persistence_reads_disk_records(tmp_path):
    path = tmp_path / "trace.jsonl"
    trace_id = new_trace_id()
    _append(path, _trace(trace_id))

    first = TradingTraceReader(path)
    assert first.query_events()["count"] == 5

    # A brand-new reader ("restart") still finds the durable records.
    restarted = TradingTraceReader(path)
    trace = restarted.get_trace(trace_id)
    assert trace is not None
    assert trace["finalStatus"] == "COMPLETE_EXECUTED"
    assert [event["stage"] for event in trace["events"]] == [
        "STRATEGY",
        "GOVERNANCE",
        "EXECUTION",
        "POSITION",
        "RESULT",
    ]


def test_bounded_page_and_stable_cursor(tmp_path):
    path = tmp_path / "trace.jsonl"
    _append(path, [_event(new_trace_id(), "STRATEGY", "BUY") for _ in range(9)])
    reader = TradingTraceReader(path)

    page_one = reader.query_events(limit=4)
    assert page_one["count"] == 4
    assert page_one["pagination"]["hasMore"] is True
    cursor = page_one["pagination"]["nextCursor"]

    # Stable cursor: replaying the same cursor yields the exact same page.
    replay = reader.query_events(limit=4, cursor=cursor)
    page_two = reader.query_events(limit=4, cursor=cursor)
    assert replay["events"] == page_two["events"]
    assert len(page_two["events"]) == 4

    seen = [event["eventId"] for event in page_one["events"] + page_two["events"]]
    final = reader.query_events(limit=4, cursor=page_two["pagination"]["nextCursor"])
    seen += [event["eventId"] for event in final["events"]]
    assert final["pagination"]["hasMore"] is False
    assert len(seen) == len(set(seen)) == 9


def test_forward_and_reverse_pagination(tmp_path):
    path = tmp_path / "trace.jsonl"
    records = [_event(new_trace_id(), "STRATEGY", "BUY") for _ in range(6)]
    _append(path, records)
    reader = TradingTraceReader(path)

    forward = reader.query_events(limit=6)
    assert [e["eventId"] for e in forward["events"]] == [r["eventId"] for r in records]

    reverse = reader.query_events(limit=3, direction="reverse")
    assert [e["eventId"] for e in reverse["events"]] == [
        records[5]["eventId"],
        records[4]["eventId"],
        records[3]["eventId"],
    ]
    assert reverse["pagination"]["hasMore"] is True
    older = reader.query_events(
        limit=3, direction="reverse", cursor=reverse["pagination"]["nextCursor"]
    )
    assert [e["eventId"] for e in older["events"]] == [
        records[2]["eventId"],
        records[1]["eventId"],
        records[0]["eventId"],
    ]
    assert older["pagination"]["hasMore"] is False


def test_filters_cycle_trade_correlation_mode_stage_reason(tmp_path):
    path = tmp_path / "trace.jsonl"
    a, b = new_trace_id(), new_trace_id()
    _append(
        path,
        [
            _event(a, "STRATEGY", "BUY", mode="PAPER", reason="OK", metadata={"rankingCycleId": "cyc-a", "tradeId": "trade-a", "correlationId": "corr-a"}),
            _event(a, "RESULT", "EXECUTED", mode="PAPER", metadata={"rankingCycleId": "cyc-a", "tradeId": "trade-a", "correlationId": "corr-a"}),
            _event(b, "STRATEGY", "SELL", mode="LIVE", reason="BLOCKED", metadata={"rankingCycleId": "cyc-b"}),
        ],
    )
    reader = TradingTraceReader(path)

    assert reader.query_events(cycle_id="cyc-a")["count"] == 2
    assert reader.query_events(trade_id="trade-a")["count"] == 2
    assert reader.query_events(correlation_id="corr-a")["count"] == 2
    assert reader.query_events(mode="LIVE")["count"] == 1
    assert reader.query_events(stage="STRATEGY")["count"] == 2
    assert reader.query_events(reason_code="BLOCKED")["count"] == 1
    assert reader.query_events(symbol="BTCUSDT")["count"] == 3


def test_correlation_id_falls_back_to_trace_id(tmp_path):
    path = tmp_path / "trace.jsonl"
    trace_id = new_trace_id()
    _append(path, _trace(trace_id))
    reader = TradingTraceReader(path)
    assert reader.query_events(correlation_id=trace_id)["count"] == 5


def test_time_range_filter(tmp_path):
    path = tmp_path / "trace.jsonl"
    early, middle, late = new_trace_id(), new_trace_id(), new_trace_id()
    _append(
        path,
        [
            _event(early, "STRATEGY", "BUY", timestamp="2026-01-01T00:00:00Z"),
            _event(middle, "STRATEGY", "BUY", timestamp="2026-01-02T00:00:00Z"),
            _event(late, "STRATEGY", "BUY", timestamp="2026-01-03T00:00:00Z"),
        ],
    )
    reader = TradingTraceReader(path)
    window = reader.query_events(
        time_from="2026-01-02T00:00:00Z", time_to="2026-01-03T00:00:00Z"
    )
    assert [event["traceId"] for event in window["events"]] == [middle]


def test_malformed_middle_line_is_isolated(tmp_path):
    path = tmp_path / "trace.jsonl"
    first, second = new_trace_id(), new_trace_id()
    _append(
        path,
        [
            _event(first, "STRATEGY", "BUY"),
            "{ this is not valid json }\n",
            _event(second, "STRATEGY", "SELL"),
        ],
    )
    reader = TradingTraceReader(path)
    result = reader.query_events()
    assert {event["traceId"] for event in result["events"]} == {first, second}
    assert result["scan"]["isolatedRecords"] == 1
    assert result["scan"]["truncatedFinalRecord"] is False


def test_truncated_final_line_is_isolated(tmp_path):
    path = tmp_path / "trace.jsonl"
    first = new_trace_id()
    _append(
        path,
        [
            _event(first, "STRATEGY", "BUY"),
            '{"traceId": "trading-e2e-partial", "mode": "PAPER", "stage": "STRAT',
        ],
    )
    reader = TradingTraceReader(path)
    result = reader.query_events()
    assert [event["traceId"] for event in result["events"]] == [first]
    assert result["scan"]["truncatedFinalRecord"] is True


def test_missing_file_and_empty_file(tmp_path):
    missing = TradingTraceReader(tmp_path / "does-not-exist.jsonl")
    result = missing.query_events()
    assert result["count"] == 0
    assert result["scan"]["reason"] == "FILE_MISSING"
    assert missing.recent(10) == []
    assert missing.get_trace(new_trace_id()) is None

    empty_path = tmp_path / "empty.jsonl"
    empty_path.write_text("", encoding="utf-8")
    empty = TradingTraceReader(empty_path)
    assert empty.query_events()["count"] == 0
    assert empty.query_events()["scan"]["reason"] is None


def test_rotated_replaced_file_detects_stale_cursor(tmp_path):
    path = tmp_path / "trace.jsonl"
    _append(path, _trace(new_trace_id()))
    reader = TradingTraceReader(path)
    cursor = reader.query_events(limit=2)["pagination"]["nextCursor"]
    assert cursor

    path.unlink()
    _append(path, _trace(new_trace_id(), mode="LIVE"))

    with pytest.raises(TraceCursorError) as excinfo:
        reader.query_events(limit=2, cursor=cursor)
    assert excinfo.value.code == "FILE_ROTATED"


def test_truncated_file_detects_stale_cursor(tmp_path):
    path = tmp_path / "trace.jsonl"
    padding = _event(new_trace_id(), "STRATEGY", "BUY", metadata={"blob": "x" * 4096})
    _append(path, [padding] + _trace(new_trace_id()))
    reader = TradingTraceReader(path)
    cursor = reader.query_events(limit=1)["pagination"]["nextCursor"]
    assert cursor

    # Truncate to exactly 4096 bytes so the head digest is unchanged but the
    # file is now shorter than the cursor's recorded size.
    path.write_bytes(path.read_bytes()[:4096])

    with pytest.raises(TraceCursorError) as excinfo:
        reader.query_events(limit=1, cursor=cursor)
    assert excinfo.value.code == "FILE_TRUNCATED"


def test_out_of_range_and_invalid_cursor(tmp_path):
    path = tmp_path / "trace.jsonl"
    _append(path, _trace(new_trace_id()))
    reader = TradingTraceReader(path)
    snapshot = reader.snapshot()

    out_of_range = _encode_cursor(
        {
            "v": 1,
            "o": snapshot.size + 100,
            "d": snapshot.device,
            "i": snapshot.inode,
            "h": snapshot.head,
            "z": snapshot.size,
            "dir": "forward",
        }
    )
    with pytest.raises(TraceCursorError) as excinfo:
        reader.query_events(cursor=out_of_range)
    assert excinfo.value.code == "CURSOR_OUT_OF_RANGE"

    with pytest.raises(TraceCursorError) as excinfo:
        reader.query_events(cursor="not-a-real-cursor")
    assert excinfo.value.code == "CURSOR_INVALID"


def test_scan_budget_exceeded_returns_partial_result(tmp_path):
    path = tmp_path / "trace.jsonl"
    records = [_event(new_trace_id(), "STRATEGY", "BUY") for _ in range(50)]
    _append(path, records)
    reader = TradingTraceReader(path, max_scan_lines=5)

    result = reader.query_events(limit=20)
    assert result["count"] == 5
    assert result["scan"]["partial"] is True
    assert result["scan"]["reason"] == "SCAN_LINE_BUDGET"
    assert result["pagination"]["hasMore"] is True

    # Resuming with the returned cursor continues without replaying.
    resumed = reader.query_events(limit=20, cursor=result["pagination"]["nextCursor"])
    assert resumed["count"] == 5
    assert set(e["eventId"] for e in resumed["events"]).isdisjoint(
        e["eventId"] for e in result["events"]
    )


def test_timeout_returns_partial_result(monkeypatch, tmp_path):
    path = tmp_path / "trace.jsonl"
    _append(path, [_event(new_trace_id(), "STRATEGY", "BUY") for _ in range(20)])

    import backend.runtime.trading_trace_reader as reader_module

    calls = {"count": 0}

    def fake_monotonic() -> float:
        calls["count"] += 1
        return 0.0 if calls["count"] == 1 else 100.0

    monkeypatch.setattr(reader_module, "monotonic", fake_monotonic)
    reader = TradingTraceReader(path, timeout_seconds=1.0)
    result = reader.query_events(limit=20)
    assert result["scan"]["partial"] is True
    assert result["scan"]["reason"] == "TIMEOUT"
    assert result["pagination"]["hasMore"] is True


def test_invalid_direction_is_rejected(tmp_path):
    path = tmp_path / "trace.jsonl"
    _append(path, _trace(new_trace_id()))
    reader = TradingTraceReader(path)
    with pytest.raises(TraceCursorError) as excinfo:
        reader.query_events(direction="sideways")
    assert excinfo.value.code == "DIRECTION_INVALID"


def test_secret_redaction_on_read(tmp_path):
    path = tmp_path / "trace.jsonl"
    raw = {
        "traceId": "trading-e2e-secret",
        "eventId": "event-secret",
        "timestamp": "2026-01-01T00:00:00Z",
        "mode": "PAPER",
        "stage": "STRATEGY",
        "status": "BUY",
        "symbol": "BTCUSDT",
        "apiKey": "should-not-appear",
        "metadata": {
            "safe": "kept",
            "apiKey": "should-not-appear",
            "nested": {"passphrase": "should-not-appear", "reason": "KEEP"},
        },
    }
    _append(path, [json.dumps(raw) + "\n"])
    reader = TradingTraceReader(path)
    result = reader.query_events()
    encoded = json.dumps(result)
    assert "should-not-appear" not in encoded
    assert result["events"][0]["metadata"] == {"safe": "kept", "nested": {"reason": "KEEP"}}
    assert "apiKey" not in result["events"][0]


def test_recent_returns_newest_first_and_session(tmp_path):
    path = tmp_path / "trace.jsonl"
    first, second = new_trace_id(), new_trace_id()
    _append(path, _trace(first))
    _append(path, _trace(second))
    reader = TradingTraceReader(path)

    traces = reader.recent(10)
    assert [trace["traceId"] for trace in traces] == [second, first]

    session = reader.session(mode="PAPER")
    assert session["observedDecisions"] == 2
    assert session["executedTrades"] == 2


def test_concurrent_append_during_read(tmp_path):
    path = tmp_path / "trace.jsonl"
    _append(path, [_event(new_trace_id(), "STRATEGY", "BUY") for _ in range(50)])
    reader = TradingTraceReader(path)
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            while not stop.is_set():
                _append(path, [_event(new_trace_id(), "STRATEGY", "BUY")])
        except BaseException as exc:  # noqa: BLE001 - surfaced in the test
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        for _ in range(50):
            page = reader.query_events(limit=20)
            assert page["count"] <= 20
            assert page["scan"]["partial"] is False
    finally:
        stop.set()
        thread.join()

    assert errors == []
    assert reader.query_events(limit=200)["count"] <= 200


def test_large_synthetic_file_bounded_scan(tmp_path):
    path = tmp_path / "large.jsonl"
    with path.open("w", encoding="utf-8") as stream:
        for index in range(20000):
            record = _event(f"trading-e2e-large-{index}", "STRATEGY", "BUY")
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    reader = TradingTraceReader(path, max_scan_lines=1000)
    result = reader.query_events(limit=5)
    assert result["count"] == 5
    assert result["scan"]["scannedLines"] <= 1000
    assert reader.recent(5)[0]["traceId"] == "trading-e2e-large-19999"
