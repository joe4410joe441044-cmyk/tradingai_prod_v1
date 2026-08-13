import json
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.supervisor import create_supervisor_router
from backend.supervisor.runtime_snapshot_adapter import (
    RuntimeAuthorityReaders,
    RuntimeSnapshotAdapter,
)


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def payloads():
    return {
        "bot": {
            "timestamp": NOW,
            "botState": "RUNNING",
            "loopEnabled": True,
            "loopState": "RUNNING",
            "selectedMode": "PAPER",
            "dryRun": True,
            "autoTradeEnabled": False,
            "realOrderAllowed": False,
            "accountSource": "PAPER_SIMULATION",
            "governance_state": {"mode": "PAPER", "execution_enabled": False},
            "emergency": {"locked": False, "state": "READY"},
            "pendingOrderState": "NONE",
            "activeSymbol": "BTC-USDT",
            "marketReady": True,
            "marketStale": False,
            "selectionMode": "MANUAL",
            "tradingDecision": {"status": "HOLD", "evaluatedAt": NOW},
        },
        "governance": {
            "sourceEvaluatedAt": NOW,
            "mode": "PAPER",
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
                "equity": "1234.123456789123456789",
                "availableCapital": "1200.000000000000000001",
                "riskBudget": "12.000000000000000001",
                "remainingExposure": "80.000000000000000001",
                "remainingPositionCapacity": "2",
                "executionEntryAllowed": False,
                "evaluatedAt": NOW,
                "authorityFresh": True,
            },
            "metrics": {
                "drawdownPercent": "0.100000000000000001",
                "openExposure": "20.000000000000000001",
                "openPositionState": "NONE",
                "metricsGeneratedAt": NOW,
            },
            "secret": "SECRET_VALUE_MUST_NOT_LEAK",
        },
        "health": {"sourceEvaluatedAt": NOW, "status": "ok", "runtimeHealthy": True},
    }


def make_client(values=None):
    values = values or payloads()
    readers = RuntimeAuthorityReaders(
        bot=lambda _app, _at: values["bot"],
        governance=lambda _app, _at: values["governance"],
        moneyManagement=lambda _app, _at: values["moneyManagement"],
        health=lambda _app, _at: values["health"],
    )
    app = FastAPI()
    app.include_router(create_supervisor_router(
        RuntimeSnapshotAdapter(readers=readers, clock=lambda: NOW)
    ))
    return TestClient(app), app


def test_in_process_get_returns_typed_stable_snapshot_without_precision_loss():
    client, _app = make_client()
    response = client.get("/api/supervisor/snapshot")
    body = response.json()

    assert response.status_code == 200
    assert body["schemaVersion"] == 1
    assert body["capturedAt"] == "2026-08-12T12:00:00Z"
    assert body["overallFreshness"] == "FRESH"
    assert body["moneyManagement"]["equity"] == "1234.123456789123456789"
    assert "fieldStates" in body["moneyManagement"]
    assert "fieldStates" in body["governance"]
    assert "SECRET_VALUE_MUST_NOT_LEAK" not in response.text
    assert response.text == client.get("/api/supervisor/snapshot").text


def test_router_exposes_only_get_for_snapshot():
    client, app = make_client()
    routes = [
        route for route in app.routes
        if getattr(route, "path", None) == "/api/supervisor/snapshot"
    ]

    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/supervisor/snapshot").status_code == 405


def test_invalid_contract_returns_stable_fail_closed_response_without_details():
    values = payloads()
    values["moneyManagement"]["capitalEligibility"]["equity"] = "NaN"
    values["moneyManagement"]["secret"] = "SECRET_VALUE_MUST_NOT_LEAK"
    client, _app = make_client(values)

    response = client.get("/api/supervisor/snapshot")
    body = response.json()
    assert response.status_code == 503
    assert body["code"] == "SUPERVISOR_INPUT_INVALID"
    assert body["message"] == "Supervisor snapshot is unavailable."
    assert body["timestamp"].endswith("Z")
    assert "NaN" not in response.text
    assert "SECRET_VALUE_MUST_NOT_LEAK" not in response.text
    assert "traceback" not in response.text.lower()


def test_main_registers_supervisor_once_and_preserves_required_routes():
    source = (ROOT / "backend/main.py").read_text(encoding="utf-8")

    assert source.count("from backend.api.supervisor import router as supervisor_router") == 1
    assert source.count("app.include_router(supervisor_router)") == 1
    assert re.search(r"app\.include_router\(\s*money_management_router\s*\)", source)
    assert '@app.get("/health")' in source
    assert "create_advice_router(" in source


def test_provider_status_is_read_only_and_fail_closed_when_default_disabled():
    client, _app = make_client()
    response = client.get("/api/supervisor/provider/status")
    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "DISABLED"
    assert body["availability"] == "UNAVAILABLE"
    assert body["localhostOnly"] is True
    assert body["mode"] == "SHADOW"
    assert body["operationalEffect"] == "NONE"
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/supervisor/provider/status").status_code == 405


def test_provider_status_separates_core_from_llm_when_disabled():
    client, _app = make_client()
    body = client.get("/api/supervisor/provider/status").json()
    assert body["supervisorCore"] == "AVAILABLE"
    assert body["llmStatus"] == "DISABLED"
    assert body["providerConfigured"] is True
    assert body["providerEnabled"] is False
    assert body["providerAvailable"] is False
    assert body["llmInterpretationAvailable"] is False
    assert body["operationalEffect"] == "NONE"
