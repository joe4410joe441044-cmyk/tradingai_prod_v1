"""Phase 3D-1 authorization/capability and trigger feature-flag tests.

Pure inputs only: no environment mutation, no I/O, no Production authority.
"""
from __future__ import annotations

import builtins
import inspect
import types

import pytest

from backend.supervisor import monitoring_trigger_security as security
from backend.supervisor.monitoring_trigger_security import (
    POST_ROUTE_IMPLEMENTATION_GATE,
    PRODUCTION_AUTHORIZATION_SOURCE,
    TRIGGER_API_ENABLED_ENV,
    TRIGGER_CAPABILITY,
    TRIGGER_PERSIST_CAPABILITY,
    MONITORING_ENABLED_ENV,
    AuthorizationInput,
    authorize,
    evaluate_authorization,
    evaluate_trigger_flags,
    evaluate_trigger_flags_from_environ,
    principal_reference,
)

VERIFIED = dict(
    authenticated=True,
    principal_id="operator",
    capability_source="VERIFIED_ADAPTER",
    source_available=True,
    source_freshness="FRESH",
)


def verified(**changes) -> AuthorizationInput:
    data = dict(VERIFIED)
    data.update(changes)
    return AuthorizationInput(**data)


# --- authorization: 1-10 ----------------------------------------------------

def test_unauthenticated_denied():
    assert evaluate_authorization(AuthorizationInput(authenticated=False)) == "DENY_UNAUTHENTICATED"
    assert evaluate_authorization(None) == "DENY_MALFORMED_INPUT"


def test_constant_operator_without_capability_denied():
    result = evaluate_authorization(verified())
    assert result == "DENY_CAPABILITY_MISSING"
    assert result != "ALLOW"


def test_authenticated_but_capability_missing_denied():
    assert evaluate_authorization(verified(capabilities=("SOME_OTHER_CAP",))) == "DENY_CAPABILITY_MISSING"


def test_capability_authority_unavailable_denied():
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_CAPABILITY,), source_available=False)
    ) == "DENY_AUTHORITY_UNAVAILABLE"
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_CAPABILITY,), capability_source="UNAVAILABLE")
    ) == "DENY_AUTHORITY_UNAVAILABLE"
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_CAPABILITY,), capability_source="UNVERIFIED")
    ) == "DENY_AUTHORITY_UNAVAILABLE"


def test_stale_authority_denied():
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_CAPABILITY,), source_freshness="STALE")
    ) == "DENY_AUTHORITY_STALE"


def test_malformed_principal_denied():
    assert evaluate_authorization({"authenticated": True, "principal_id": "bad id!"}) == (
        "DENY_MALFORMED_INPUT"
    )
    assert evaluate_authorization("not-a-mapping") == "DENY_MALFORMED_INPUT"


def test_explicit_verified_capability_allowed():
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_CAPABILITY,))
    ) == "ALLOW"
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_PERSIST_CAPABILITY,)), capability=TRIGGER_PERSIST_CAPABILITY
    ) == "ALLOW"


def test_unrelated_capability_denied():
    assert evaluate_authorization(
        verified(capabilities=("SOME_OTHER_CAP",))
    ) == "DENY_CAPABILITY_MISSING"
    # A persist-only principal is still denied the observation capability.
    assert evaluate_authorization(
        verified(capabilities=(TRIGGER_PERSIST_CAPABILITY,))
    ) == "DENY_CAPABILITY_MISSING"


def test_deterministic_authorization_result():
    value = verified(capabilities=(TRIGGER_CAPABILITY,))
    assert evaluate_authorization(value) == evaluate_authorization(value) == "ALLOW"


def test_no_implicit_production_user_authorization():
    assert PRODUCTION_AUTHORIZATION_SOURCE == "UNRESOLVED"
    assert POST_ROUTE_IMPLEMENTATION_GATE == "BLOCKED"
    assert AuthorizationInput().capabilities == ()
    assert evaluate_authorization(AuthorizationInput()) != "ALLOW"


def test_authorization_decision_is_privacy_safe():
    decision = authorize(verified(capabilities=(TRIGGER_CAPABILITY,)))
    assert decision.allowed is True
    assert decision.result == "ALLOW"
    assert decision.principal_ref is not None
    assert "operator" not in decision.principal_ref


def test_principal_reference_is_stable_and_not_raw():
    ref = principal_reference("operator")
    assert ref == principal_reference("operator")
    assert ref != "operator"
    assert ref.startswith("P")


# --- feature flags: 11-15 ---------------------------------------------------

def test_flag_absent_disabled():
    evaluation = evaluate_trigger_flags()
    assert evaluation.api_enabled is False
    assert evaluation.both_enabled is False
    assert evaluation.reason_code == "FLAG_OFF_API"


def test_flag_false_disabled():
    for raw in ("0", "false", "no", "off", ""):
        assert evaluate_trigger_flags(api_raw=raw).api_enabled is False


def test_flag_true_enabled():
    for raw in ("1", "true", "yes", "on", "TRUE"):
        assert evaluate_trigger_flags(api_raw=raw).api_enabled is True


def test_flag_malformed_fails_closed():
    evaluation = evaluate_trigger_flags(api_raw="enabled", monitoring_raw="true")
    assert evaluation.api_enabled is False
    assert evaluation.api_flag.valid is False
    assert evaluation.both_enabled is False
    assert evaluation.reason_code == "FLAG_INVALID"


def test_api_and_monitoring_flags_independently_required():
    assert evaluate_trigger_flags(api_raw="true", monitoring_raw=None).both_enabled is False
    assert evaluate_trigger_flags(api_raw=None, monitoring_raw="true").both_enabled is False
    assert evaluate_trigger_flags(api_raw="true", monitoring_raw="true").both_enabled is True


def test_flags_from_injected_environ_mapping():
    environ = {TRIGGER_API_ENABLED_ENV: "true", MONITORING_ENABLED_ENV: "1"}
    evaluation = evaluate_trigger_flags_from_environ(environ)
    assert evaluation.both_enabled is True


def test_import_has_no_side_effects(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    source = inspect.getsource(security)
    module = types.ModuleType("backend.supervisor._trigger_security_reimport")
    module.__package__ = "backend.supervisor"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        exec(compile(source, "monitoring_trigger_security.py", "exec"), module.__dict__)
    assert callable(module.evaluate_authorization)
