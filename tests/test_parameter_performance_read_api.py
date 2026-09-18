"""E-PERF-3 focused tests: read-only Parameter Performance API.

These tests prove the operator-facing read path is a thin, read-only projection
over the durable E-PERF-2 stores:

- revision history grouped by the canonical identity (scope, effectiveRevision);
- PAPER / LIVE isolation;
- completed-trade retrieval with factual deterministic metrics;
- explicit win / loss / breakeven semantics;
- revision comparison source data with parameter deltas;
- truthful empty / unavailable states (no historical fabrication);
- GET endpoints never mutate parameter, execution or trading authority.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.parameter_settings import router as parameter_settings_router
from backend.runtime.parameter_performance import ParameterPerformanceStore
from backend.runtime.parameter_performance_read import (
    ParameterPerformanceReadService,
    compute_metrics,
)
from backend.strategy.parameters.settings_service import ParameterSettingsService


def _seed_revision(tmp_path: Path, value: float) -> None:
    service = ParameterSettingsService(base_directory=tmp_path)
    configuration = service.configuration("PAPER")
    parameters = dict(configuration["parameters"])
    parameters["minimumCompositeScore"] = value
    result = service.update_configuration(
        scope="PAPER",
        parameters=parameters,
        expected_revision=configuration["configuredRevision"],
    )
    assert result.outcome.value == "ACCEPTED"
    promotion = service.promote_if_safe("PAPER", safe_to_promote=True)
    assert promotion["outcome"] == "PROMOTED"


def _record(
    *,
    scope="PAPER",
    revision,
    pnl,
    holding_ms=1000.0,
    reason="TAKE_PROFIT",
    values=None,
    authoritative=True,
    parameter_set_id=None,
):
    return {
        "schemaVersion": 1,
        "recordId": f"stage13-{scope}-{revision}-{pnl}-{holding_ms}",
        "tradeId": f"trade-{scope}-{revision}-{pnl}",
        "traceId": "trading-e2e-perf3",
        "positionId": "pos-1",
        "scope": scope,
        "mode": scope.lower(),
        "symbol": "MOVEUSDT",
        "side": "BUY",
        "parameterSetId": parameter_set_id or f"strategy-params/{scope}",
        "configuredRevision": revision,
        "effectiveRevision": revision,
        "parameterRevision": revision,
        "parameterContextAvailable": values is not None,
        "parameterSnapshot": values,
        "parameterContext": {"featureContract": "TIME_SYMBOL_NORMALIZED_V1"}
        if values is not None
        else None,
        "entryTimestamp": 0.0,
        "exitTimestamp": holding_ms / 1000.0,
        "holdingMs": holding_ms,
        "entryPrice": 0.1,
        "exitPrice": 0.11,
        "quantity": 100.0,
        "notional": 11.0,
        "realizedPnl": pnl,
        "realizedPnlAuthoritative": authoritative,
        "exitReason": reason,
        "featureContract": "TIME_SYMBOL_NORMALIZED_V1",
        "recordedAt": "2026-09-18T00:00:00.000000Z",
    }


def _append(tmp_path: Path, records) -> None:
    store = ParameterPerformanceStore(tmp_path / "parameter_performance.jsonl")
    for record in records:
        assert store.append(record) is True


def _build_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.parameter_performance_read_service = (
        ParameterPerformanceReadService(base_directory=tmp_path)
    )
    app.include_router(parameter_settings_router)
    return app


@pytest.fixture
def client(tmp_path):
    return TestClient(_build_app(tmp_path), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Endpoint registration / read-only
# ---------------------------------------------------------------------------


def test_performance_endpoints_are_read_only():
    new_routes = [
        route
        for route in parameter_settings_router.routes
        if getattr(route, "path", "").startswith(
            "/api/parameter-settings/performance"
        )
    ]
    assert len(new_routes) == 2
    for route in new_routes:
        assert getattr(route, "methods", set()) == {"GET"}


def test_write_route_set_is_unchanged():
    write_routes = []
    for route in parameter_settings_router.routes:
        methods = getattr(route, "methods", set()) or set()
        if methods & {"POST", "PUT", "PATCH", "DELETE"}:
            write_routes.append((getattr(route, "path", ""), sorted(methods)))
    assert write_routes == [
        ("/api/parameter-settings/configuration", ["PUT"])
    ]


# ---------------------------------------------------------------------------
# Empty / unavailable
# ---------------------------------------------------------------------------


def test_empty_history_is_truthful(client):
    resp = client.get(
        "/api/parameter-settings/performance", params={"scope": "PAPER"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is False
    assert body["revisionCount"] == 0
    assert body["recordCount"] == 0
    assert body["revisions"] == []
    assert body["records"] == []
    assert body["metrics"]["tradeCount"] == 0
    assert body["metrics"]["winRate"] is None
    assert body["metrics"]["realizedPnl"] is None


def test_unsupported_scope_is_rejected(client):
    resp = client.get(
        "/api/parameter-settings/performance", params={"scope": "BOTH"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_SCOPE"


# ---------------------------------------------------------------------------
# Revision history
# ---------------------------------------------------------------------------


def test_revision_history_from_archive_with_values(client, tmp_path):
    _seed_revision(tmp_path, 0.42)
    _seed_revision(tmp_path, 0.55)

    resp = client.get(
        "/api/parameter-settings/performance", params={"scope": "PAPER"}
    )
    assert resp.status_code == 200
    body = resp.json()
    revisions = {
        item["effectiveRevision"]: item for item in body["revisions"]
    }
    assert set(revisions) == {2, 3}
    assert revisions[2]["parameterValues"]["minimumCompositeScore"] == 0.42
    assert revisions[3]["parameterValues"]["minimumCompositeScore"] == 0.55
    assert revisions[2]["valueSource"] == "REVISION_ARCHIVE"
    assert revisions[2]["scope"] == "PAPER"
    assert revisions[2]["parameterSetId"] == "strategy-params/PAPER"


def test_paper_and_live_revisions_are_isolated(client, tmp_path):
    _seed_revision(tmp_path, 0.42)
    _append(tmp_path, [
        _record(scope="LIVE", revision=2, pnl=5.0, values={"a": 1}),
    ])

    paper = client.get(
        "/api/parameter-settings/performance", params={"scope": "PAPER"}
    ).json()
    live = client.get(
        "/api/parameter-settings/performance", params={"scope": "LIVE"}
    ).json()

    assert all(item["scope"] == "PAPER" for item in paper["revisions"])
    assert all(item["scope"] == "LIVE" for item in live["revisions"])
    assert {item["effectiveRevision"] for item in paper["revisions"]} == {2}
    assert {item["effectiveRevision"] for item in live["revisions"]} == {2}
    assert paper["recordCount"] == 0
    assert live["recordCount"] == 1


# ---------------------------------------------------------------------------
# Completed trades + metrics
# ---------------------------------------------------------------------------


def test_completed_trades_and_deterministic_metrics(client, tmp_path):
    _append(tmp_path, [
        _record(revision=2, pnl=10.0, holding_ms=1000.0, reason="TP"),
        _record(revision=2, pnl=-5.0, holding_ms=2000.0, reason="SL"),
        _record(revision=2, pnl=0.0, holding_ms=3000.0, reason="TIME"),
        _record(revision=2, pnl=2.0, holding_ms=4000.0, reason="TP"),
    ])

    resp = client.get(
        "/api/parameter-settings/performance",
        params={"scope": "PAPER", "revision": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    metrics = body["metrics"]
    assert metrics["tradeCount"] == 4
    assert metrics["pnlRecordCount"] == 4
    assert metrics["winCount"] == 2
    assert metrics["lossCount"] == 1
    assert metrics["breakevenCount"] == 1
    assert metrics["winRate"] == 0.5
    assert metrics["realizedPnl"] == 7.0
    assert metrics["averagePnl"] == 1.75
    assert metrics["medianPnl"] == 1.0
    assert metrics["averageHoldingMs"] == 2500.0
    assert metrics["realizedPnlAuthoritative"] is True
    assert metrics["exitReasons"] == [
        {"reason": "TP", "count": 2},
        {"reason": "SL", "count": 1},
        {"reason": "TIME", "count": 1},
    ]
    assert body["recordCount"] == 4
    assert len(body["records"]) == 4


def test_non_authoritative_live_pnl_is_flagged(tmp_path):
    _append(tmp_path, [
        _record(scope="LIVE", revision=5, pnl=3.0, authoritative=False),
    ])
    service = ParameterPerformanceReadService(base_directory=tmp_path)
    metrics = service.performance(scope="LIVE")["metrics"]
    assert metrics["realizedPnl"] == 3.0
    assert metrics["realizedPnlAuthoritative"] is False


def test_records_without_pnl_are_excluded_from_win_loss(tmp_path):
    _append(tmp_path, [
        _record(revision=4, pnl=None),
        _record(revision=4, pnl=5.0),
    ])
    service = ParameterPerformanceReadService(base_directory=tmp_path)
    metrics = service.performance(scope="PAPER")["metrics"]
    assert metrics["tradeCount"] == 2
    assert metrics["pnlRecordCount"] == 1
    assert metrics["winCount"] == 1
    assert metrics["lossCount"] == 0
    assert metrics["winRate"] == 1.0


def test_missing_optional_fields_are_handled_safely(tmp_path):
    _append(tmp_path, [{
        "schemaVersion": 1,
        "recordId": "stage13-min",
        "scope": "PAPER",
        "effectiveRevision": 9,
        "realizedPnl": 1.0,
    }])
    service = ParameterPerformanceReadService(base_directory=tmp_path)
    body = service.performance(scope="PAPER")
    record = body["records"][0]
    assert record["effectiveRevision"] == 9
    assert record.get("exitReason") is None
    metrics = body["metrics"]
    assert metrics["tradeCount"] == 1
    assert metrics["averageHoldingMs"] is None
    assert metrics["exitReasons"] == []


# ---------------------------------------------------------------------------
# No fabrication
# ---------------------------------------------------------------------------


def test_missing_parameter_snapshot_is_not_fabricated(tmp_path):
    _append(tmp_path, [_record(revision=6, pnl=1.0, values=None)])
    service = ParameterPerformanceReadService(base_directory=tmp_path)
    body = service.performance(scope="PAPER")
    summary = next(
        item for item in body["revisions"] if item["effectiveRevision"] == 6
    )
    assert summary["parameterValues"] is None
    assert summary["valueSource"] == "UNAVAILABLE"


def test_record_values_are_used_when_no_archive_exists(tmp_path):
    _append(tmp_path, [
        _record(revision=6, pnl=1.0, values={"minimumCompositeScore": 0.77}),
    ])
    service = ParameterPerformanceReadService(base_directory=tmp_path)
    body = service.performance(scope="PAPER")
    summary = next(
        item for item in body["revisions"] if item["effectiveRevision"] == 6
    )
    assert summary["parameterValues"]["minimumCompositeScore"] == 0.77
    assert summary["valueSource"] == "TRADE_RECORD"


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def test_revision_comparison_source_data(client, tmp_path):
    _seed_revision(tmp_path, 0.42)
    _seed_revision(tmp_path, 0.55)
    _append(tmp_path, [
        _record(revision=2, pnl=1.0, values={"minimumCompositeScore": 0.42}),
        _record(revision=3, pnl=-1.0, values={"minimumCompositeScore": 0.55}),
    ])

    resp = client.get(
        "/api/parameter-settings/performance/compare",
        params={"scope": "PAPER", "revisionA": 2, "revisionB": 3},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "PAPER"
    assert body["revisionA"]["effectiveRevision"] == 2
    assert body["revisionB"]["effectiveRevision"] == 3

    diff = {item["name"]: item for item in body["parameterDiff"]}
    composite = diff["minimumCompositeScore"]
    assert composite["a"] == 0.42
    assert composite["b"] == 0.55
    assert composite["delta"] == pytest.approx(0.13)
    assert composite["changed"] is True
    unchanged = diff["maximumStrategySpreadPct"]
    assert unchanged["changed"] is False
    assert unchanged["delta"] == 0.0
    assert body["changedCount"] == 1


def test_comparison_of_missing_revision_is_truthful(client, tmp_path):
    _seed_revision(tmp_path, 0.42)
    resp = client.get(
        "/api/parameter-settings/performance/compare",
        params={"scope": "PAPER", "revisionA": 2, "revisionB": 99},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["revisionA"]["effectiveRevision"] == 2
    assert body["revisionB"] is None
    diff = {item["name"]: item for item in body["parameterDiff"]}
    assert diff["minimumCompositeScore"]["b"] is None
    assert diff["minimumCompositeScore"]["changed"] is False


# ---------------------------------------------------------------------------
# Read-only safety
# ---------------------------------------------------------------------------


def test_get_does_not_mutate_stores_or_authority(client, tmp_path):
    _seed_revision(tmp_path, 0.42)
    _append(tmp_path, [_record(revision=2, pnl=1.0)])

    store_path = tmp_path / "parameter_performance.jsonl"
    before_records = store_path.read_bytes()
    service = ParameterSettingsService(base_directory=tmp_path)
    effective_before = service.effective("PAPER")

    client.get(
        "/api/parameter-settings/performance", params={"scope": "PAPER"}
    )
    client.get(
        "/api/parameter-settings/performance/compare",
        params={"scope": "PAPER", "revisionA": 2, "revisionB": 2},
    )

    assert store_path.read_bytes() == before_records
    assert service.effective("PAPER") == effective_before


def test_persistence_reload_is_readable(tmp_path):
    _append(tmp_path, [_record(revision=2, pnl=4.0)])
    fresh = ParameterPerformanceReadService(base_directory=tmp_path)
    body = fresh.performance(scope="PAPER")
    assert body["recordCount"] == 1
    assert body["metrics"]["realizedPnl"] == 4.0


def test_compute_metrics_is_deterministic():
    records = [
        {"realizedPnl": 1.0, "holdingMs": 10.0, "exitReason": "A"},
        {"realizedPnl": 1.0, "holdingMs": 20.0, "exitReason": "A"},
    ]
    first = compute_metrics(records)
    second = compute_metrics(list(reversed(records)))
    assert first == second
