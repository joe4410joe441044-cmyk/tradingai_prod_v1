"""PAPER/LIVE monitoring is durable observation, never execution authority."""
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.money_management import router
from backend.money_management.loss_application_registration import build_default_money_management_config
from backend.money_management.loss_http_api import APPLICATION_STATE_ATTRIBUTE, MoneyManagementHttpBoundary
from backend.money_management.monitoring import SNAPSHOT_FILENAME, normalize_identity
from backend.money_management.timeline import MoneyManagementTimelineRecorder, MoneyManagementTimelineStore, TIMELINE_FILENAME
from tests.test_money_management_loss_runtime_update_dispatcher import NOW, metrics

SOURCES = {"PAPER": "PAPER_RUNTIME_EQUITY", "LIVE": "REAL_LIVE_ACCOUNT_EQUITY"}


def setup(tmp_path, maximum_events=5000):
    store = MoneyManagementTimelineStore(tmp_path, maximum_events=maximum_events)
    recorder = MoneyManagementTimelineRecorder(store, lambda: NOW)
    app = FastAPI()
    boundary = MoneyManagementHttpBoundary(app, timeline_recorder=recorder, timestamp_source=lambda: NOW)
    setattr(app.state, APPLICATION_STATE_ATTRIBUTE, boundary)
    app.include_router(router)
    return store, recorder, boundary, TestClient(app)


def record(recorder, authority, at=NOW, equity="100"):
    observation = replace(metrics(), accounting_authority_source=SOURCES[authority],
                          runtime_instance_id="runtime-1", session_id=7, captured_at=at,
                          equity=Decimal(equity), peak_equity=Decimal("100"), drawdown=Decimal("0"))
    recorder.record_runtime(observation, build_default_money_management_config(), "NORMAL")
    return observation


@pytest.mark.parametrize("authority", ["PAPER", "LIVE"])
def test_observation_durable_reload_api(tmp_path, authority):
    store, recorder, _, _ = setup(tmp_path)
    record(recorder, authority)
    _, _, _, client = setup(tmp_path)
    result = client.get("/api/money-management/history", params={"authority": authority})
    assert result.status_code == 200
    event = result.json()["events"][0]
    assert event["authority"] == authority
    assert event["accountingAuthoritySource"] == SOURCES[authority]
    assert event["runtimeInstanceId"] == "runtime-1"
    assert event["sessionId"] == 7
    assert event["capturedAt"] == "2026-07-26T12:00:00Z"
    view = client.get("/api/money-management/monitoring", params={"viewAuthority": authority}).json()
    assert view["dataAuthority"] == authority
    assert view["semantics"] == view["freshness"] == "LAST_KNOWN"
    assert view["snapshot"]["metrics"]["equity"] == "100"
    assert view["snapshot"]["realizedPnlSemantics"] == ("REALIZED_PNL_TODAY" if authority == "LIVE" else "PAPER_ENGINE_REPORTED_REALIZED_PNL")


def test_legacy_92_percent_is_audit_only_and_never_snapshot(tmp_path):
    store, recorder, _, _ = setup(tmp_path)
    legacy = recorder.record_started().to_dict()
    for key in normalize_identity(None):
        legacy.pop(key)
    legacy["metrics"].update(equity="7.91836966", peakEquity="100.0805801773", drawdownPercent="92.088")
    path = tmp_path / TIMELINE_FILENAME
    path.write_text(json.dumps(legacy) + "\n")
    original = path.read_bytes()
    store, recorder, boundary, client = setup(tmp_path)
    for query in ({}, {"authority": "ALL"}, {"authority": "UNKNOWN"}):
        events = client.get("/api/money-management/history", params=query).json()["events"]
        assert len(events) == 1 and events[0]["authority"] == "UNKNOWN"
    for authority in SOURCES:
        assert client.get("/api/money-management/history", params={"authority": authority}).json()["events"] == []
        assert boundary.get_monitoring(view_authority=authority)["availability"] == "UNAVAILABLE"
    assert path.read_bytes() == original
    record(recorder, "PAPER")
    assert boundary.get_monitoring(view_authority="PAPER")["snapshot"]["metrics"]["drawdownPercent"] == "0"
    assert boundary.get_monitoring(view_authority="LIVE")["availability"] == "UNAVAILABLE"


@pytest.mark.parametrize("authority", ["PAPER", "LIVE", "UNKNOWN", "ALL"])
def test_filter_before_pagination_and_duplicate_sequences(tmp_path, authority):
    store, recorder, _, _ = setup(tmp_path)
    recorder.record_started()
    for i in range(6):
        record(recorder, "PAPER" if i % 2 else "LIVE", equity=str(90+i))
    path = tmp_path / TIMELINE_FILENAME
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["sequence"] = 52
    path.write_text("".join(json.dumps(row)+"\n" for row in rows))
    store, _, _, client = setup(tmp_path)
    expected = store.query(authority=authority).events
    found = []
    cursor = None
    while True:
        query = {"authority": authority, "limit": 1}
        if cursor:
            query["before"] = cursor
        response = client.get("/api/money-management/history", params=query)
        assert response.status_code == 200
        page = response.json()
        found.extend(e["eventId"] for e in page["events"])
        if not page["hasMore"]:
            break
        cursor = page["nextCursor"]
    assert found == [e.event_id for e in expected]
    assert len(found) == len(set(found))
    assert store.query(before="52").events == ()  # old cursor semantics retained


def test_snapshots_survive_opposite_authority_and_retention(tmp_path):
    _, recorder, _, _ = setup(tmp_path, maximum_events=1)
    record(recorder, "PAPER", equity="100")
    record(recorder, "LIVE", equity="8")
    _, _, boundary, _ = setup(tmp_path, maximum_events=1)
    assert boundary.get_monitoring(view_authority="PAPER")["snapshot"]["metrics"]["equity"] == "100"
    assert boundary.get_monitoring(view_authority="LIVE")["snapshot"]["metrics"]["equity"] == "8"


@pytest.mark.parametrize("authority", ["PAPER", "LIVE"])
def test_stale_and_out_of_order_observations(tmp_path, authority):
    _, recorder, boundary, _ = setup(tmp_path)
    record(recorder, authority, NOW-timedelta(days=1), equity="90")
    record(recorder, authority, NOW-timedelta(days=2), equity="80")
    view = boundary.get_monitoring(view_authority=authority)
    assert view["freshness"] == "STALE" and view["semantics"] == "LAST_KNOWN"
    assert view["snapshot"]["metrics"]["equity"] == "90"


def test_view_has_no_runtime_or_execution_dependencies(tmp_path):
    _, recorder, boundary, client = setup(tmp_path)
    record(recorder, "PAPER")
    record(recorder, "LIVE")
    state = {"mode": "paper", "autoTrade": False, "loop": False, "governance": "BLOCKED",
             "emergency": True, "entryGates": "CLOSED"}
    original = deepcopy(state)
    methods = {name: Mock(side_effect=AssertionError(name)) for name in
               ("start", "stop", "arm_live", "rebase_accounting", "create_order", "set_governance", "set_emergency", "set_entry_gates")}
    bot = SimpleNamespace(config=state, engine=SimpleNamespace(mode="paper"), **methods)
    class ForbiddenRuntime:
        def __getattribute__(self, name):
            raise AssertionError("Monitoring accessed runtime: " + name)
    boundary._app = ForbiddenRuntime()
    boundary._dispatcher = ForbiddenRuntime()
    boundary._capital_authority_provider = Mock(side_effect=AssertionError("capital"))
    for authority in ("PAPER", "LIVE", "PAPER"):
        assert client.get("/api/money-management/monitoring", params={"viewAuthority": authority}).status_code == 200
    assert bot.config == original and bot.engine.mode == "paper"
    for method in methods.values():
        method.assert_not_called()
    boundary._capital_authority_provider.assert_not_called()


def test_invalid_filters_fail_closed(tmp_path):
    _, _, _, client = setup(tmp_path)
    assert client.get("/api/money-management/history?authority=paper").status_code == 422
    for value in ("UNKNOWN", "ALL", "live", "bogus"):
        assert client.get("/api/money-management/monitoring", params={"viewAuthority": value}).status_code == 422


def test_configuration_and_recovery_keep_observation_timestamp(tmp_path):
    store, recorder, _, _ = setup(tmp_path)
    record(recorder, "LIVE", NOW-timedelta(days=1))
    recorder.record_configuration(before=None, after=None, version=1)
    recorder.record_recovery(previous_state="LOCKED", current_state="NORMAL", version=1)
    for event in store.query().events:
        assert event.to_dict()["authority"] == "LIVE"
        assert event.to_dict()["capturedAt"] == "2026-07-25T12:00:00Z"
    assert store.monitoring.get("LIVE")["riskState"] == "NORMAL"


def test_authority_not_inferred_from_label_or_numbers():
    assert normalize_identity({"authority": "LIVE", "equity": "8"})["authority"] == "UNKNOWN"
    assert normalize_identity({"accountingAuthoritySource": "other"})["authority"] == "UNKNOWN"


def test_observation_scope_and_rebase_require_matching_authority(tmp_path):
    from backend.money_management.monitoring import observation_identity
    from backend.money_management.loss_persistence_models import AccountingRebaseAuthoritySource
    observation = replace(metrics(), accounting_authority_source=SOURCES["PAPER"])
    state = SimpleNamespace(accounting_authority_source=AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY,
                            account_scope="scope-1", accounting_rebases=(SimpleNamespace(rebase_id="validated-1"),))
    identity = observation_identity(observation, state)
    assert identity["accountScope"] == "scope-1"
    assert identity["accountingRebaseId"] == "validated-1"
    state.accounting_authority_source = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY
    identity = observation_identity(observation, state)
    assert identity["accountScope"] is None and identity["accountingRebaseId"] is None


def test_atomic_snapshot_failure_preserves_durable_and_memory_state(tmp_path, monkeypatch):
    _, recorder, boundary, _ = setup(tmp_path)
    record(recorder, "PAPER")
    original = (tmp_path / SNAPSHOT_FILENAME).read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr("backend.money_management.monitoring.os.replace", Mock(side_effect=OSError("failed replace")))
        with pytest.raises(OSError):
            record(recorder, "PAPER", equity="90")
    assert (tmp_path / SNAPSHOT_FILENAME).read_bytes() == original
    assert boundary.get_monitoring(view_authority="PAPER")["snapshot"]["metrics"]["equity"] == "100"
    assert list(tmp_path.glob(".mm-monitoring-*")) == []


def test_identical_metrics_across_authority_still_recorded(tmp_path):
    store, recorder, _, _ = setup(tmp_path)
    record(recorder, "PAPER")
    record(recorder, "LIVE")
    assert len(store.query(authority="PAPER").events) == 1
    assert len(store.query(authority="LIVE").events) == 1
    for authority in SOURCES:
        event = store.query(authority=authority).events[0].to_dict()
        assert event["realizedPnlSemantics"] == ("REALIZED_PNL_TODAY" if authority == "LIVE" else "PAPER_ENGINE_REPORTED_REALIZED_PNL")
