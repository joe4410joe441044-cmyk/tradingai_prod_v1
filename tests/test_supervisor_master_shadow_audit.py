from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.supervisor.contracts import Freshness, MasterSupervisorDecision
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.master_shadow_audit import build_master_shadow_audit_event
from backend.supervisor.operator_constitution import (
    TRADINGAI_OPERATOR_CONSTITUTION,
    constitution_identity,
)


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
MM_DIGEST = "a" * 64


def decision():
    return MasterSupervisorDecision(
        agent="MASTER_SUPERVISOR",
        mode="SHADOW",
        overallPosture="CAUTION",
        tradingRecommendation="PAUSE_NEW_ENTRIES",
        mmRecommendation={"riskDirection": "MAINTAIN", "riskMultiplier": "0.8"},
        humanAttention="REVIEW",
        summary="現在は慎重な監視が必要です。",
        reasons=("状態を確認中",),
        sourceEvaluatedAt=NOW,
        decidedAt=NOW,
    )


def event(value=None):
    return build_master_shadow_audit_event(
        snapshot_captured_at=NOW,
        mm_assessment_digest=MM_DIGEST,
        constitution_identity=constitution_identity(TRADINGAI_OPERATOR_CONSTITUTION),
        runtime_evaluated_at=NOW,
        provider_identity="fake-master-provider",
        provider_version="1.0",
        status="COMPLETED" if value else "FAILED_CLOSED",
        failure_code=None if value else SupervisorFailureCode.PROVIDER_UNAVAILABLE,
        overall_freshness=Freshness.FRESH,
        decision=value,
    )


def test_master_audit_is_immutable_deterministic_and_bounded():
    first = event(decision())
    second = event(decision())
    assert first == second
    assert first.eventType == "MASTER_SHADOW_DECISION"
    assert first.mmAssessmentDigest == MM_DIGEST
    assert first.constitutionIdentity.constitutionDigest == TRADINGAI_OPERATOR_CONSTITUTION.digest()
    assert len(first.decisionDigest) == 64
    assert first.operationalEffect == "NONE"
    serialized = first.stable_json().lower()
    for forbidden in ("rawprompt", "rawoutput", "rawsnapshot", "traceback", "secret", "credential"):
        assert forbidden not in serialized
    with pytest.raises(ValidationError):
        first.eventId = "changed"


def test_failed_audit_has_stable_failure_identity_and_no_decision_material():
    first = event()
    assert first.failureCode is SupervisorFailureCode.PROVIDER_UNAVAILABLE
    assert first == event()
    assert "exception" not in first.stable_json().lower()
