from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.supervisor.contracts import Freshness, MMSupervisorAssessment
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.mm_shadow_audit import build_mm_shadow_audit_event


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def assessment():
    return MMSupervisorAssessment(
        assessmentState="CAUTION",
        recommendedRiskDirection="MAINTAIN",
        recommendedRiskMultiplier="0.8",
        capitalCondition="DEGRADED",
        confidence=0.8,
        reasons=("bounded reason",),
        sourceEvaluatedAt=NOW,
        assessedAt=NOW,
    )


def event(value=None):
    return build_mm_shadow_audit_event(
        snapshot_captured_at=NOW,
        source_evaluated_at=NOW,
        runtime_evaluated_at=NOW,
        provider_identity="fake-structured-provider",
        provider_version="1.0",
        status="COMPLETED" if value is not None else "FAILED_CLOSED",
        failure_code=None if value is not None else SupervisorFailureCode.PROVIDER_UNAVAILABLE,
        overall_freshness=Freshness.FRESH,
        assessment=value,
    )


def test_audit_event_is_deterministic_bounded_and_contains_no_raw_material():
    first = event(assessment())
    second = event(assessment())

    assert first == second
    assert first.eventId == second.eventId
    assert first.assessmentDigest == second.assessmentDigest
    assert len(first.assessmentDigest) == 64
    assert first.eventType == "MM_SHADOW_ASSESSMENT"
    assert first.operationalEffect == "NONE"
    serialized = first.stable_json().lower()
    for forbidden in ("rawprompt", "rawoutput", "traceback", "credential", "secret"):
        assert forbidden not in serialized
    with pytest.raises(ValidationError):
        first.eventId = "changed"


def test_failed_audit_uses_stable_failure_code_without_exception_text():
    first = event()
    second = event()
    assert first == second
    assert first.failureCode is SupervisorFailureCode.PROVIDER_UNAVAILABLE
    assert "exception" not in first.stable_json().lower()
