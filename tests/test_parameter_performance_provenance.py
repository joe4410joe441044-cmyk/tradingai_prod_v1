"""Focused regression coverage for Parameter Performance history integrity.

Covers the Production/Test provenance boundary, test-store isolation, exact
revision scoping (no effectiveRevision=null fallback) and PAPER/LIVE isolation.
Provenance is never inferred from tradeId naming.
"""

import os
from pathlib import Path

from backend.runtime.parameter_performance import (
    DEFAULT_PARAMETER_PERFORMANCE_PATH,
    ORIGIN_NON_PRODUCTION,
    ORIGIN_PRODUCTION,
    ParameterPerformanceStore,
    build_completed_trade_record,
    default_parameter_performance_store,
    is_production_eligible,
    record_completed_trade,
)
from backend.runtime.parameter_performance_read import (
    ParameterPerformanceReadService,
)
from backend.strategy.parameters.revision_archive import ParameterRevisionArchive


def _record(
    *,
    scope="PAPER",
    revision=3,
    pnl=1.0,
    origin=None,
    trade_id="trade-1",
    entry_timestamp=1000.0,
    exit_timestamp=1001.0,
    reason="TP",
    values=None,
):
    record = {
        "schemaVersion": 1,
        "recordId": f"stage13-{scope}-{revision}-{trade_id}",
        "tradeId": trade_id,
        "scope": scope,
        "mode": scope.lower(),
        "symbol": "MOVEUSDT",
        "side": "BUY",
        "effectiveRevision": revision,
        "parameterContextAvailable": values is not None,
        "parameterSnapshot": values,
        "entryTimestamp": entry_timestamp,
        "exitTimestamp": exit_timestamp,
        "holdingMs": 1000.0,
        "entryPrice": 0.1,
        "exitPrice": 0.11,
        "quantity": 100.0,
        "realizedPnl": pnl,
        "realizedPnlAuthoritative": True,
        "exitReason": reason,
        "recordedAt": "2026-09-18T00:00:00.000000Z",
    }
    if origin is not None:
        record["origin"] = origin
    return record


def _service(tmp_path: Path) -> ParameterPerformanceReadService:
    return ParameterPerformanceReadService(
        store=ParameterPerformanceStore(tmp_path / "parameter_performance.jsonl"),
        archive=ParameterRevisionArchive(base_directory=tmp_path),
    )


def _append(tmp_path: Path, records):
    store = ParameterPerformanceStore(tmp_path / "parameter_performance.jsonl")
    for record in records:
        assert store.append(record) is True


# ---------------------------------------------------------------------------
# A. Test-store isolation
# ---------------------------------------------------------------------------


def test_default_store_is_isolated_from_production():
    store = default_parameter_performance_store()
    assert str(store.path) == os.environ["PARAMETER_PERFORMANCE_PATH"]
    assert str(store.path) != str(
        Path(DEFAULT_PARAMETER_PERFORMANCE_PATH).resolve()
    )


def test_test_store_path_is_not_production_path():
    test_path = Path(os.environ["PARAMETER_PERFORMANCE_PATH"]).resolve()
    production_path = Path(DEFAULT_PARAMETER_PERFORMANCE_PATH).resolve()
    assert test_path != production_path


# ---------------------------------------------------------------------------
# B. Test records cannot contaminate Production Parameter Performance
# ---------------------------------------------------------------------------


def test_real_writer_marks_test_session_non_production(tmp_path):
    source = {
        "tradeId": "paper-1-manual-d4-a-entry",
        "mode": "paper",
        "symbol": "XRPUSDT",
        "side": "BUY",
        "qty": 1.0,
        "entryPrice": 100.0,
        "exitPrice": 101.0,
        "pnl": 1.0,
        "reason": "MANUAL_CLOSE",
        "openedAt": 1000.0,
        "closedAt": 1001.0,
    }
    record = build_completed_trade_record(source)
    assert record["origin"] == ORIGIN_NON_PRODUCTION
    assert is_production_eligible(record) is False


def test_record_completed_trade_uses_isolated_store_and_tags_origin():
    source = {
        "tradeId": "paper-1-isolation-probe",
        "mode": "paper",
        "symbol": "XRPUSDT",
        "side": "BUY",
        "qty": 1.0,
        "entryPrice": 100.0,
        "exitPrice": 101.0,
        "pnl": 1.0,
        "reason": "MANUAL_CLOSE",
        "openedAt": 1000.0,
        "closedAt": 1001.0,
    }
    assert record_completed_trade(source) is True
    store = default_parameter_performance_store()
    rows = store.load()
    written = [r for r in rows if r.get("tradeId") == source["tradeId"]]
    assert len(written) == 1
    assert written[0]["origin"] == ORIGIN_NON_PRODUCTION
    # The isolated test store is never the Production store.
    assert str(store.path) == os.environ["PARAMETER_PERFORMANCE_PATH"]


def test_non_production_record_is_excluded_from_metrics(tmp_path):
    _append(tmp_path, [
        _record(origin=ORIGIN_PRODUCTION, revision=3, pnl=5.0),
        _record(
            origin=ORIGIN_NON_PRODUCTION,
            revision=3,
            pnl=1000.0,
            trade_id="paper-1-manual-d4-a-entry",
        ),
    ])
    service = _service(tmp_path)
    body = service.performance(scope="PAPER", revision=3)
    assert body["recordCount"] == 1
    assert body["metrics"]["realizedPnl"] == 5.0
    assert body["metrics"]["tradeCount"] == 1


# ---------------------------------------------------------------------------
# C / M. Production PAPER records are eligible
# ---------------------------------------------------------------------------


def test_production_paper_runtime_trade_is_eligible(tmp_path):
    _append(tmp_path, [_record(origin=ORIGIN_PRODUCTION, revision=3, pnl=2.0)])
    body = _service(tmp_path).performance(scope="PAPER", revision=3)
    assert body["recordCount"] == 1
    assert body["metrics"]["realizedPnl"] == 2.0


def test_legacy_record_with_provable_revision_is_eligible(tmp_path):
    # Legacy (no origin) but with a provable revision identity: the six real R3
    # records fall in this class.
    _append(tmp_path, [_record(revision=3, pnl=4.0)])
    body = _service(tmp_path).performance(scope="PAPER", revision=3)
    assert body["recordCount"] == 1
    assert body["metrics"]["realizedPnl"] == 4.0


# ---------------------------------------------------------------------------
# D. effectiveRevision=null is excluded from revision metrics
# ---------------------------------------------------------------------------


def test_null_revision_records_are_never_eligible(tmp_path):
    _append(tmp_path, [
        _record(revision=None, pnl=999.0, trade_id="manual-d4-a-entry"),
        _record(revision=3, pnl=1.0),
    ])
    service = _service(tmp_path)
    body = service.performance(scope="PAPER")
    # Scope-wide metrics include only the eligible R3 record.
    assert body["metrics"]["tradeCount"] == 1
    assert body["metrics"]["realizedPnl"] == 1.0
    # No synthetic null-revision revision entry.
    assert all(
        item["effectiveRevision"] is not None for item in body["revisions"]
    )


def test_is_production_eligible_contract():
    assert is_production_eligible({"origin": ORIGIN_PRODUCTION}) is True
    assert is_production_eligible({"origin": ORIGIN_NON_PRODUCTION}) is False
    assert is_production_eligible({"effectiveRevision": 3}) is True
    assert is_production_eligible({"effectiveRevision": None}) is False
    assert is_production_eligible({}) is False
    assert is_production_eligible({"effectiveRevision": True}) is False


# ---------------------------------------------------------------------------
# E / F. Exact revision scoping
# ---------------------------------------------------------------------------


def test_paper_r3_query_returns_only_r3(tmp_path):
    _append(tmp_path, [
        _record(revision=3, pnl=1.0),
        _record(revision=3, pnl=2.0),
        _record(revision=4, pnl=50.0),
        _record(revision=None, pnl=500.0, trade_id="manual-mm-close-1"),
    ])
    body = _service(tmp_path).performance(scope="PAPER", revision=3)
    assert body["recordCount"] == 2
    assert body["metrics"]["tradeCount"] == 2
    assert body["metrics"]["realizedPnl"] == 3.0
    assert all(r["effectiveRevision"] == 3 for r in body["records"])


def test_paper_r4_zero_trade_query_returns_zero(tmp_path):
    _append(tmp_path, [
        _record(revision=3, pnl=1.0),
        _record(revision=None, pnl=500.0, trade_id="manual-d4-a-entry"),
    ])
    body = _service(tmp_path).performance(scope="PAPER", revision=4)
    assert body["recordCount"] == 0
    assert body["metrics"]["tradeCount"] == 0
    assert body["metrics"]["realizedPnl"] is None
    assert body["records"] == []


# ---------------------------------------------------------------------------
# G / N. PAPER / LIVE isolation (tradeId naming has no authority)
# ---------------------------------------------------------------------------


def test_paper_and_live_are_isolated(tmp_path):
    _append(tmp_path, [
        _record(scope="PAPER", revision=3, pnl=1.0),
        _record(scope="LIVE", revision=3, pnl=9.0),
    ])
    service = _service(tmp_path)
    paper = service.performance(scope="PAPER", revision=3)
    live = service.performance(scope="LIVE", revision=3)
    assert paper["metrics"]["realizedPnl"] == 1.0
    assert live["metrics"]["realizedPnl"] == 9.0
    assert all(r["scope"] == "PAPER" for r in paper["records"])
    assert all(r["scope"] == "LIVE" for r in live["records"])


def test_live_open_1_naming_cannot_override_paper_scope(tmp_path):
    # A PAPER record named "live-open-1" must be PAPER evidence, never LIVE.
    _append(tmp_path, [
        _record(scope="PAPER", revision=3, pnl=1.0, trade_id="live-open-1"),
    ])
    service = _service(tmp_path)
    paper = service.performance(scope="PAPER", revision=3)
    live = service.performance(scope="LIVE", revision=3)
    assert paper["recordCount"] == 1
    assert live["recordCount"] == 0


def test_trade_id_prefix_is_never_used_as_provenance(tmp_path):
    # A non-production record with a Production-looking tradeId is excluded.
    _append(tmp_path, [
        _record(
            origin=ORIGIN_NON_PRODUCTION,
            revision=3,
            pnl=1000.0,
            trade_id="paper-trade-999-1789000000000",
        ),
    ])
    body = _service(tmp_path).performance(scope="PAPER", revision=3)
    assert body["recordCount"] == 0


# ---------------------------------------------------------------------------
# H. Revision A/B populations remain isolated
# ---------------------------------------------------------------------------


def test_revision_comparison_uses_isolated_eligible_populations(tmp_path):
    _append(tmp_path, [
        _record(revision=3, pnl=1.0, values={"minimumCompositeScore": 0.42}),
        _record(revision=4, pnl=-1.0, values={"minimumCompositeScore": 0.55}),
        _record(
            revision=None,
            pnl=1000.0,
            trade_id="manual-d4-a-entry",
            values={"minimumCompositeScore": 9.9},
        ),
        _record(
            origin=ORIGIN_NON_PRODUCTION,
            revision=3,
            pnl=500.0,
            values={"minimumCompositeScore": 8.8},
        ),
    ])
    comparison = _service(tmp_path).compare(
        scope="PAPER", revision_a=3, revision_b=4
    )
    assert comparison["revisionA"]["observedTradeCount"] == 1
    assert comparison["revisionB"]["observedTradeCount"] == 1
    diff = {item["name"]: item for item in comparison["parameterDiff"]}
    assert diff["minimumCompositeScore"]["a"] == 0.42
    assert diff["minimumCompositeScore"]["b"] == 0.55


# ---------------------------------------------------------------------------
# I / J. Headline + Observed Trades follow the selected revision
# ---------------------------------------------------------------------------


def test_headline_metrics_match_selected_revision(tmp_path):
    _append(tmp_path, [
        _record(revision=3, pnl=1.0),
        _record(revision=3, pnl=2.0),
        _record(revision=4, pnl=50.0),
    ])
    service = _service(tmp_path)
    r3 = service.performance(scope="PAPER", revision=3)
    r4 = service.performance(scope="PAPER", revision=4)
    assert r3["metrics"]["realizedPnl"] == 3.0
    assert r4["metrics"]["realizedPnl"] == 50.0
    assert r3["revision"] == 3
    assert r4["revision"] == 4


def test_observed_trades_match_selected_revision(tmp_path):
    _append(tmp_path, [
        _record(revision=3, pnl=1.0, trade_id="r3-a"),
        _record(revision=4, pnl=2.0, trade_id="r4-a"),
    ])
    body = _service(tmp_path).performance(scope="PAPER", revision=3)
    assert [r["tradeId"] for r in body["records"]] == ["r3-a"]


# ---------------------------------------------------------------------------
# K. Timestamps are returned truthfully
# ---------------------------------------------------------------------------


def test_timestamps_are_preserved_for_production_records(tmp_path):
    _append(tmp_path, [
        _record(
            revision=3,
            entry_timestamp=1789784124.9367893,
            exit_timestamp=1789784125.7253401,
        ),
    ])
    record = _service(tmp_path).performance(scope="PAPER", revision=3)["records"][0]
    assert record["entryTimestamp"] == 1789784124.9367893
    assert record["exitTimestamp"] == 1789784125.7253401
