"""Phase 3C read-only Supervisor monitoring API tests (synthetic, no Production)."""
from __future__ import annotations

import builtins
import inspect
import types
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import supervisor_monitoring as api_module
from backend.api.supervisor_monitoring import (
    MONITORING_UNAVAILABLE,
    create_supervisor_monitoring_router,
)
from backend.supervisor.monitoring_read_service import MonitoringReadService
from backend.supervisor.monitoring_scheduler_models import FeatureFlagStatus
from backend.supervisor.monitoring_state_store import MonitoringStateStore
from test_supervisor_monitoring_models import NOW

CLOCK_AT = NOW + timedelta(minutes=1)
FLAG_ON = FeatureFlagStatus(
    enabled=True, source="ENV", raw_value_present=True, valid=True, reason_code=None,
)
HEALTH_KEYS = (
    "schemaVersion", "generatedAt", "featureFlagName", "featureEnabled", "defaultEnabled",
    "activationStatus", "schedulerState", "schedulerConnected", "backgroundTaskActive",
    "lastRunId", "lastRunMode", "lastRunStatus", "anomalyCounts", "activeCount",
    "acknowledgedCount", "resolvedCount", "cooldownCount", "suppressedCount",
    "journalAvailability", "recoveryStatus", "corruptionCount", "partialResult",
    "freshness", "provenance", "availability", "warnings", "crossProcessSafety",
    "productionActivationAllowed",
)


def fixed_clock():
    return CLOCK_AT


def make_client(service=None):
    app = FastAPI()
    app.include_router(create_supervisor_monitoring_router(service))
    return TestClient(app), app


def default_service(**kwargs):
    kwargs.setdefault("clock", fixed_clock)
    return MonitoringReadService(**kwargs)


# --- 1-2 import / construction -------------------------------------------

def test_import_has_no_side_effects(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    source = inspect.getsource(api_module)
    module = types.ModuleType("backend.api._monitoring_reimport")
    module.__package__ = "backend.api"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        exec(compile(source, "supervisor_monitoring.py", "exec"), module.__dict__)
    assert callable(module.create_supervisor_monitoring_router)


def test_constructor_has_no_io(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during router construction")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        app = FastAPI()
        app.include_router(create_supervisor_monitoring_router())
    assert app is not None


# --- 3-5 GET only ---------------------------------------------------------

def test_get_only_routes():
    client, _app = make_client(default_service())
    assert client.get("/monitoring/health").status_code == 200
    assert client.get("/monitoring/state").status_code == 200
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/monitoring/health").status_code == 405
        assert getattr(client, method)("/monitoring/state").status_code == 405


def test_no_monitoring_mutation_routes():
    router = create_supervisor_monitoring_router(default_service())
    monitoring_routes = [r for r in router.routes if "monitoring" in getattr(r, "path", "")]
    assert len(monitoring_routes) == 2
    for route in monitoring_routes:
        assert set(route.methods) <= {"GET", "HEAD"}


# --- 6-7 response contracts ----------------------------------------------

def test_health_response_contract():
    client, _app = make_client(default_service())
    body = client.get("/monitoring/health").json()
    for key in HEALTH_KEYS:
        assert key in body


def test_state_response_contract():
    client, _app = make_client(default_service())
    body = client.get("/monitoring/state").json()
    for key in HEALTH_KEYS:
        assert key in body


# --- 8-14 flag / fixed facts ---------------------------------------------

def test_feature_flag_default_off():
    client, _app = make_client(default_service())
    body = client.get("/monitoring/health").json()
    assert body["featureEnabled"] is False
    assert body["defaultEnabled"] is False
    assert body["activationStatus"] == "DISABLED"


def test_enabled_flag_still_not_active():
    client, _app = make_client(default_service(feature_flag=FLAG_ON))
    body = client.get("/monitoring/health").json()
    assert body["featureEnabled"] is True
    assert body["activationStatus"] == "CONFIGURED_ENABLED_INACTIVE"
    assert body["schedulerConnected"] is False
    assert body["backgroundTaskActive"] is False
    assert body["productionActivationAllowed"] is False


def test_cross_process_limitation_reported():
    client, _app = make_client(default_service())
    body = client.get("/monitoring/health").json()
    assert body["crossProcessSafety"] == "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED"
    assert body["productionActivationAllowed"] is False


# --- 15-18 journal states through the API --------------------------------

def test_journal_missing_not_created(tmp_path):
    path = tmp_path / "missing.jsonl"
    client, _app = make_client(default_service(store=MonitoringStateStore(path)))
    body = client.get("/monitoring/state").json()
    assert body["journalAvailability"] == "UNAVAILABLE"
    assert "JOURNAL_MISSING" in body["warnings"]
    assert not path.exists()


def test_journal_partial(tmp_path):
    path = tmp_path / "partial.jsonl"
    store = MonitoringStateStore(path, max_recovery_records=1)
    from test_supervisor_monitoring_read_service import anomaly_state, make_event

    store.append(make_event(anomaly_state("a" * 64), "1"))
    store.append(make_event(anomaly_state("b" * 64), "2"))
    client, _app = make_client(default_service(store=store))
    body = client.get("/monitoring/state").json()
    assert body["journalAvailability"] == "PARTIAL"
    assert body["partialResult"] is True
    assert body["recordsRead"] == 1


def test_corrupt_record_isolated(tmp_path):
    path = tmp_path / "corrupt.jsonl"
    store = MonitoringStateStore(path)
    from test_supervisor_monitoring_read_service import anomaly_state, make_event

    store.append(make_event(anomaly_state("a" * 64), "1"))
    with path.open("ab") as handle:
        handle.write(b"{broken\n")
    client, _app = make_client(default_service(store=store))
    body = client.get("/monitoring/state").json()
    assert body["corruptionCount"] >= 1
    assert body["journalAvailability"] == "CORRUPT"


# --- 43 dependency failure isolation -------------------------------------

def test_route_level_failure_is_bounded(monkeypatch):
    instance = default_service()

    def boom():
        raise RuntimeError("sensitive internal detail")

    monkeypatch.setattr(instance, "read", boom)
    client, _app = make_client(instance)
    response = client.get("/monitoring/health")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == MONITORING_UNAVAILABLE
    assert "sensitive internal detail" not in response.text
    assert "Traceback" not in response.text


def test_dependency_exception_still_serves_read_model(tmp_path, monkeypatch):
    store = MonitoringStateStore(tmp_path / "raises.jsonl")

    def boom():
        raise RuntimeError("disk failure")

    monkeypatch.setattr(store, "recover", boom)
    client, _app = make_client(default_service(store=store))
    body = client.get("/monitoring/health").json()
    assert body["journalAvailability"] == "UNAVAILABLE"
    assert "JOURNAL_READ_FAILED" in body["warnings"]


# --- 44 existing snapshot compatibility ----------------------------------

def test_existing_snapshot_compatibility():
    root = Path(__file__).resolve().parents[1]
    source = (root / "backend/api/supervisor.py").read_text()
    assert '@router.get("/snapshot"' in source
    assert "create_supervisor_monitoring_router(monitoring_read_service)" in source

    app = FastAPI()
    app.include_router(
        create_supervisor_monitoring_router(default_service()), prefix="/api/supervisor"
    )

    @app.get("/api/supervisor/snapshot")
    def snapshot():
        return {"schemaVersion": 1}

    client = TestClient(app)
    assert client.get("/api/supervisor/snapshot").json() == {"schemaVersion": 1}
    assert client.get("/api/supervisor/monitoring/health").status_code == 200
    assert client.get("/api/supervisor/monitoring/state").status_code == 200


# --- 45 advisor consumer compatibility -----------------------------------

def test_advisor_consumer_compatibility():
    import backend.ai_advisor.knowledge_history_consumer as advisor_consumer

    assert callable(advisor_consumer.AdvisorKnowledgeHistoryConsumer) or hasattr(
        advisor_consumer, "AdvisorKnowledgeHistoryConsumer"
    )


# --- 46-47 bounded / no authority ----------------------------------------

def test_bounded_response():
    client, _app = make_client(default_service())
    response = client.get("/monitoring/health")
    assert len(response.text) < 50000


def test_no_trading_authority_fields():
    from backend.supervisor.monitoring_read_service import MonitoringReadResponse

    forbidden = {"allow", "block", "order", "execute", "arm", "disarm", "remediate"}
    assert not set(MonitoringReadResponse.model_fields) & forbidden
