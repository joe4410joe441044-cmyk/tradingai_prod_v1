"""E-PARAM-4 focused tests: PARAMETER SETTINGS API + single write authority.

These tests prove the operator-facing parameter settings API is a thin client of
the existing canonical authority:

- the schema is registry-driven (exactly 12 V1 parameters, 5 primary / 7
  advanced);
- PAPER and LIVE configuration reads are isolated;
- configured / effective / runtime are distinguishable;
- exactly one authenticated write path exists and it enforces canonical
  validation and optimistic concurrency;
- LIVE writes are fail-closed for parameters without a proven canonical LIVE
  consumer;
- the API never mutates order / bot / runtime authority.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.parameter_settings import router as parameter_settings_router
from backend.auth.api import create_operator_auth_router
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    OperatorCsrfProtection,
)
from backend.auth.operator_auth import (
    OperatorAuthenticator,
    hash_operator_credential,
)
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.strategy.parameters.resolver import CanonicalParameterResolver
from backend.strategy.parameters.runtime_registry import (
    get_runtime_snapshot,
    reset_runtime_snapshots,
)
from backend.strategy.parameters.settings_service import (
    ParameterSettingsService,
)

SESSION_SECRET = "c" * 32
TEST_CREDENTIAL = "parameter-settings-operator-1"
TEST_CREDENTIAL_HASH = hash_operator_credential(TEST_CREDENTIAL)
CSRF_PATHS = frozenset({"/api/parameter-settings/configuration"})

CANONICAL_PARAMETER_NAMES = (
    "minimumCompositeScore",
    "maximumStrategySpreadPct",
    "momentumWindowSeconds",
    "minimumStrategyConfidence",
    "maximumHoldMs",
    "minimumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
    "momentumMinimumWarmupSeconds",
    "absorptionVolumePercentile",
    "liquidityQualityPercentile",
)

LIVE_WRITABLE_NAMES = (
    "minimumCompositeScore",
    "minimumStrategyConfidence",
    "maximumHoldMs",
    "minimumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
)


def _build_app(tmp_path: Path):
    config = OperatorAuthConfig(
        credential_hash=TEST_CREDENTIAL_HASH,
        session_secret=SESSION_SECRET,
        session_ttl_seconds=3600,
        secure_cookie=False,
        cookie_path="/",
        cookie_samesite="lax",
    )
    manager = OperatorSessionManager(SESSION_SECRET, 3600)
    authenticator = OperatorAuthenticator(TEST_CREDENTIAL_HASH)
    app = FastAPI()
    app.state.parameter_settings_service = ParameterSettingsService(
        base_directory=tmp_path
    )
    app.add_middleware(
        OperatorSessionMiddleware,
        session_manager=manager,
        config=config,
    )
    app.add_middleware(
        OperatorCsrfProtection,
        csrf_required_paths=CSRF_PATHS,
    )
    app.include_router(create_operator_auth_router(authenticator, manager, config))
    app.include_router(parameter_settings_router)
    return app


@pytest.fixture(autouse=True)
def _clean_runtime_registry():
    reset_runtime_snapshots()
    yield
    reset_runtime_snapshots()


@pytest.fixture
def client(tmp_path):
    return TestClient(_build_app(tmp_path), raise_server_exceptions=False)


def _extract_cookie(response, name):
    for header in response.headers.get_list("set-cookie"):
        for part in header.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                if key.strip() == name:
                    return value.strip()
    return None


def _login(client):
    resp = client.post("/api/auth/login", json={"credential": TEST_CREDENTIAL})
    assert resp.status_code == 200, resp.text
    session = _extract_cookie(resp, COOKIE_NAME)
    csrf = _extract_cookie(resp, CSRF_TOKEN_COOKIE)
    assert session and csrf
    return session, csrf


def _put(client, session, csrf, payload):
    return client.put(
        "/api/parameter-settings/configuration",
        json=payload,
        cookies={COOKIE_NAME: session, CSRF_TOKEN_COOKIE: csrf},
        headers={CSRF_TOKEN_HEADER: csrf},
    )


def _configured_parameters(client, scope):
    resp = client.get(
        "/api/parameter-settings/configuration", params={"scope": scope}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------


def test_schema_is_registry_driven(client):
    resp = client.get("/api/parameter-settings/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert body["parameterCount"] == 12
    assert body["primaryCount"] == 5
    assert body["advancedCount"] == 7
    assert len(body["parameters"]) == 12
    assert tuple(entry["name"] for entry in body["parameters"]) == (
        CANONICAL_PARAMETER_NAMES
    )
    required = {
        "name",
        "labelEn",
        "labelJa",
        "unit",
        "minimum",
        "maximum",
        "minimumInclusive",
        "maximumInclusive",
        "precision",
        "scopeApplicability",
        "couplingGroup",
        "tier",
        "primaryAdvanced",
        "editable",
        "description",
    }
    for entry in body["parameters"]:
        assert required.issubset(entry), entry
    spread = next(
        entry
        for entry in body["parameters"]
        if entry["name"] == "maximumStrategySpreadPct"
    )
    assert "percent" in spread["unit"]
    assert spread["liveWritable"] is False


def test_paper_and_live_configuration_reads_are_isolated(client):
    paper = _configured_parameters(client, "PAPER")
    live = _configured_parameters(client, "LIVE")

    assert paper["scope"] == "PAPER"
    assert live["scope"] == "LIVE"
    assert paper["parameterSetId"] == "strategy-params/PAPER"
    assert live["parameterSetId"] == "strategy-params/LIVE"
    assert paper["source"] == "MIGRATED_PAPER_CALIBRATION"
    assert live["source"] == "MIGRATED_CLASS_CONSTANT"
    # PAPER and LIVE baselines are genuinely different.
    assert (
        paper["parameters"]["minimumCompositeScore"]
        != live["parameters"]["minimumCompositeScore"]
    )
    assert set(paper["parameters"]) == set(CANONICAL_PARAMETER_NAMES)
    assert set(live["parameters"]) == set(CANONICAL_PARAMETER_NAMES)


def test_unsupported_scope_is_rejected(client):
    resp = client.get(
        "/api/parameter-settings/configuration", params={"scope": "BOTH"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_SCOPE"
    missing = client.get("/api/parameter-settings/configuration")
    assert missing.status_code == 422


def test_effective_read_is_configured_until_promoted(client):
    resp = client.get(
        "/api/parameter-settings/effective", params={"scope": "PAPER"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validation"]["isValid"] is True
    assert body["effectiveRevision"] == body["configuredRevision"]
    assert set(body["parameters"]) == set(CANONICAL_PARAMETER_NAMES)
    assert body["warnings"] == []


def test_runtime_no_snapshot_state_and_observed_snapshot(client, tmp_path):
    empty = client.get(
        "/api/parameter-settings/runtime", params={"scope": "PAPER"}
    )
    assert empty.status_code == 200
    assert empty.json()["status"] == "NO_RUNTIME_SNAPSHOT"
    assert empty.json()["runtimeSnapshotAvailable"] is False

    # A read endpoint must never fabricate an observed runtime snapshot.
    assert get_runtime_snapshot("PAPER") is None

    snapshot = CanonicalParameterResolver(
        base_directory=tmp_path
    ).resolve_paper()
    from backend.strategy.parameters.runtime_registry import (
        record_runtime_snapshot,
    )

    record_runtime_snapshot("PAPER", snapshot)

    observed = client.get(
        "/api/parameter-settings/runtime", params={"scope": "PAPER"}
    )
    assert observed.status_code == 200
    body = observed.json()
    assert body["status"] == "AVAILABLE"
    assert body["runtimeSnapshotAvailable"] is True
    assert body["capturedAt"]
    assert set(body["parameters"]) == set(CANONICAL_PARAMETER_NAMES)


def test_status_exposes_operator_safe_health(client):
    resp = client.get("/api/parameter-settings/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert body["parameterCount"] == 12
    for scope in ("PAPER", "LIVE"):
        entry = body["scopes"][scope]
        assert entry["health"] == "OK"
        assert entry["fallbackActive"] is True
        assert entry["configuredAvailable"] is True
        assert entry["effectiveAvailable"] is True
        assert entry["runtimeSnapshotAvailable"] is False
        assert entry["configuredRevision"] == 1
        assert entry["effectiveRevision"] == 1


# ---------------------------------------------------------------------------
# Write authority
# ---------------------------------------------------------------------------


def test_unauthenticated_write_is_rejected(client, tmp_path):
    payload = {
        "scope": "PAPER",
        "parameters": _configured_parameters(client, "PAPER")["parameters"],
        "expectedRevision": 1,
    }
    resp = client.put(
        "/api/parameter-settings/configuration", json=payload
    )
    assert resp.status_code in (401, 403), resp.text
    # The rejected write must not persist anything.
    configured = _configured_parameters(client, "PAPER")
    assert configured["configuredRevision"] == 1


def test_authenticated_write_accepts_and_increments_once(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "PAPER")
    parameters = dict(before["parameters"])
    parameters["minimumCompositeScore"] = 0.42

    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "CONFIGURATION_ACCEPTED"
    assert body["configuredRevision"] == before["configuredRevision"] + 1
    assert body["effectiveRevision"] == before["effectiveRevision"]
    assert body["status"] == "PENDING"

    after = _configured_parameters(client, "PAPER")
    assert after["configuredRevision"] == before["configuredRevision"] + 1
    assert after["parameters"]["minimumCompositeScore"] == 0.42
    assert after["status"] == "PENDING"

    # CONFIGURED and EFFECTIVE stay distinct: the pending revision is not
    # falsely reported as already effective.
    effective = client.get(
        "/api/parameter-settings/effective", params={"scope": "PAPER"}
    ).json()
    assert effective["effectiveRevision"] == before["effectiveRevision"]
    assert effective["parameters"]["minimumCompositeScore"] == (
        before["parameters"]["minimumCompositeScore"]
    )


def test_revision_conflict_returns_409(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "PAPER")
    parameters = dict(before["parameters"])
    parameters["minimumCompositeScore"] = 0.42
    accepted = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert accepted.status_code == 200

    stale = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert stale.status_code == 409
    conflict = stale.json()
    assert conflict["code"] == "REVISION_CONFLICT"
    assert conflict["configuredRevision"] == before["configuredRevision"] + 1
    assert conflict["configuration"]["configuredRevision"] == (
        before["configuredRevision"] + 1
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: values.update({"minimumCompositeScore": 2.0}),
        lambda values: values.update({"minimumCompositeScore": "bad"}),
        lambda values: values.update({"minimumHoldMs": 999999}),
        lambda values: values.update({"nope": 1.0}),
    ],
)
def test_invalid_configuration_returns_422_and_no_revision(client, mutate):
    session, csrf = _login(client)
    before = _configured_parameters(client, "PAPER")
    parameters = dict(before["parameters"])
    mutate(parameters)

    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "INVALID_CONFIGURATION"
    assert _configured_parameters(client, "PAPER")["configuredRevision"] == (
        before["configuredRevision"]
    )


def test_cross_field_validation_is_authoritative(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "PAPER")

    hold = dict(before["parameters"])
    hold["minimumHoldMs"] = 5000
    hold["maximumHoldMs"] = 3000
    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": hold,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert resp.status_code == 422
    codes = {
        issue["code"] for issue in resp.json()["validation"]["errors"]
    }
    assert "HOLD_TIME_ORDER" in codes

    warmup = dict(before["parameters"])
    warmup["momentumWindowSeconds"] = 30
    warmup["momentumMinimumWarmupSeconds"] = 60
    resp2 = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": warmup,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert resp2.status_code == 422
    codes2 = {
        issue["code"] for issue in resp2.json()["validation"]["errors"]
    }
    assert "MOMENTUM_WARMUP_ORDER" in codes2


def test_live_write_requires_confirmation(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "LIVE")
    parameters = dict(before["parameters"])
    parameters["minimumCompositeScore"] = 0.61

    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "LIVE",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "LIVE_CONFIRMATION_REQUIRED"
    assert _configured_parameters(client, "LIVE")["configuredRevision"] == (
        before["configuredRevision"]
    )


def test_live_unmigrated_parameter_write_is_rejected(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "LIVE")
    parameters = dict(before["parameters"])
    parameters["maximumStrategySpreadPct"] = 0.9

    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "LIVE",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
            "confirmLive": True,
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "LIVE_UNMIGRATED_PARAMETER_WRITE_REJECTED"
    assert body["rejectedParameters"] == ["maximumStrategySpreadPct"]
    assert _configured_parameters(client, "LIVE")["configuredRevision"] == (
        before["configuredRevision"]
    )


def test_live_writable_parameter_write_is_accepted(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "LIVE")
    parameters = dict(before["parameters"])
    parameters["minimumCompositeScore"] = 0.61

    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "LIVE",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
            "confirmLive": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["configuredRevision"] == before["configuredRevision"] + 1
    assert _configured_parameters(client, "LIVE")["parameters"][
        "minimumCompositeScore"
    ] == 0.61


def test_paper_write_never_alters_live(client):
    session, csrf = _login(client)
    live_before = _configured_parameters(client, "LIVE")
    paper_before = _configured_parameters(client, "PAPER")
    parameters = dict(paper_before["parameters"])
    parameters["minimumCompositeScore"] = 0.11
    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": parameters,
            "expectedRevision": paper_before["configuredRevision"],
        },
    )
    assert resp.status_code == 200
    assert _configured_parameters(client, "LIVE") == live_before


def test_write_does_not_mutate_order_or_runtime_authority(client):
    session, csrf = _login(client)
    before = _configured_parameters(client, "PAPER")
    parameters = dict(before["parameters"])
    parameters["minimumCompositeScore"] = 0.42
    resp = _put(
        client,
        session,
        csrf,
        {
            "scope": "PAPER",
            "parameters": parameters,
            "expectedRevision": before["configuredRevision"],
        },
    )
    assert resp.status_code == 200
    # No observed runtime snapshot is fabricated by a configuration write.
    assert get_runtime_snapshot("PAPER") is None
    # The accepted payload carries no order/bot authority keys.
    body = resp.json()
    assert set(body) <= {
        "code",
        "message",
        "scope",
        "configuredRevision",
        "effectiveRevision",
        "status",
        "warnings",
        "configuration",
        "effective",
    }
    for forbidden in ("order", "leverage", "quantity", "symbol", "arm"):
        assert forbidden not in body


def test_only_one_write_route_is_registered():
    write_routes = []
    for route in parameter_settings_router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if methods & {"POST", "PUT", "PATCH", "DELETE"}:
            write_routes.append((path, sorted(methods)))
    assert write_routes == [
        ("/api/parameter-settings/configuration", ["PUT"])
    ], write_routes
