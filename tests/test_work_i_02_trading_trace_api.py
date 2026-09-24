"""WORK I② P0 — trading trace API compatibility and restart-safety tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import trading_trace as trading_trace_api
from backend.runtime.trading_trace import make_event, new_trace_id
from backend.runtime.trading_trace_reader import TradingTraceReader


def _event(trace_id, stage, status, *, mode="PAPER", timestamp=None, metadata=None):
    return make_event(
        trace_id=trace_id,
        mode=mode,
        stage=stage,
        status=status,
        symbol="BTCUSDT",
        runtime_id="runtime-1",
        reason_code=None,
        metadata=metadata,
        timestamp=timestamp,
    ).to_dict()


def _append(path: Path, records) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    trace_id = new_trace_id()
    _append(
        path,
        [
            _event(trace_id, "STRATEGY", "BUY", metadata={"rankingCycleId": "cyc-1", "tradeId": "trade-1"}),
            _event(trace_id, "GOVERNANCE", "ALLOW"),
            _event(trace_id, "RESULT", "EXECUTED", metadata={"decision": "BUY", "netPnL": 2.0}),
        ],
    )
    reader = TradingTraceReader(path)
    monkeypatch.setattr(trading_trace_api, "trace_reader", reader)
    app = FastAPI()
    app.include_router(trading_trace_api.router)
    with TestClient(app) as test_client:
        test_client.trace_id = trace_id
        yield test_client


def test_recent_endpoint_shape_is_backward_compatible(client):
    response = client.get("/api/trading-trace/recent", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"traces", "count"}
    assert body["count"] == 1
    assert body["traces"][0]["traceId"] == client.trace_id
    assert body["traces"][0]["finalStatus"] == "COMPLETE_EXECUTED"


def test_session_endpoint_shape_is_backward_compatible(client):
    response = client.get("/api/trading-trace/session", params={"mode": "PAPER"})
    assert response.status_code == 200
    body = response.json()
    assert body["observedDecisions"] == 1
    assert body["executedTrades"] == 1
    assert body["tradingAiStatus"] == "NOT_INSTALLED"


def test_get_trace_endpoint_and_not_found(client):
    response = client.get(f"/api/trading-trace/{client.trace_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["traceId"] == client.trace_id
    assert len(body["events"]) == 3

    missing = client.get("/api/trading-trace/trading-e2e-does-not-exist")
    assert missing.status_code == 404


def test_events_endpoint_filters_and_pagination(client):
    response = client.get("/api/trading-trace/events", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["ordering"] == "APPEND_ORDER"
    assert body["pagination"]["hasMore"] is True

    filtered = client.get(
        "/api/trading-trace/events",
        params={"cycleId": "cyc-1"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1

    trade = client.get("/api/trading-trace/events", params={"tradeId": "trade-1"})
    assert trade.json()["count"] == 1


def test_events_endpoint_time_range_alias(client):
    response = client.get(
        "/api/trading-trace/events",
        params={"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 3


def test_events_endpoint_stale_cursor_returns_conflict(client, tmp_path):
    first = client.get("/api/trading-trace/events", params={"limit": 1})
    cursor = first.json()["pagination"]["nextCursor"]
    assert cursor

    # Simulate replacement/rotation of the underlying file.
    reader = trading_trace_api.trace_reader
    path = reader.path
    path.unlink()
    _append(path, [_event(new_trace_id(), "STRATEGY", "BUY")])

    response = client.get("/api/trading-trace/events", params={"cursor": cursor})
    assert response.status_code == 409
    assert response.json()["stale"] is True
    assert response.json()["code"] == "FILE_ROTATED"
