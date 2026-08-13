"""Immutable bounded audit event for Master SHADOW decisions."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Freshness, MasterSupervisorDecision, SupervisorAgentId, SupervisorContract, SupervisorMode
from .failure_codes import SupervisorFailureCode
from .operator_constitution import ConstitutionIdentity


MASTER_SHADOW_EVENT_TYPE = "MASTER_SHADOW_DECISION"
MASTER_SHADOW_CONTRACT_VERSION = "1"


class MasterShadowAuditEvent(SupervisorContract):
    eventId: str = Field(min_length=1, max_length=80)
    eventType: Literal["MASTER_SHADOW_DECISION"] = MASTER_SHADOW_EVENT_TYPE
    agentId: Literal[SupervisorAgentId.MASTER_SUPERVISOR] = SupervisorAgentId.MASTER_SUPERVISOR
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    snapshotCapturedAt: datetime
    mmAssessmentDigest: str = Field(pattern=r"^[0-9a-f]{64}$")
    constitutionIdentity: ConstitutionIdentity
    runtimeEvaluatedAt: datetime
    providerIdentity: str = Field(min_length=1, max_length=100)
    providerVersion: str = Field(min_length=1, max_length=100)
    contractVersion: Literal["1"] = MASTER_SHADOW_CONTRACT_VERSION
    status: Literal["COMPLETED", "FAILED_CLOSED"]
    failureCode: SupervisorFailureCode | None = None
    overallFreshness: Freshness
    operationalEffect: Literal["NONE"] = "NONE"
    decisionDigest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("snapshotCapturedAt", "runtimeEvaluatedAt")
    @classmethod
    def aware_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def coherent_outcome(self) -> "MasterShadowAuditEvent":
        if self.status == "COMPLETED" and self.failureCode is not None:
            raise ValueError("completed audit cannot contain failure")
        if self.status == "FAILED_CLOSED" and self.failureCode is None:
            raise ValueError("failed audit requires failure code")
        return self


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def build_master_shadow_audit_event(
    *,
    snapshot_captured_at: datetime,
    mm_assessment_digest: str,
    constitution_identity: ConstitutionIdentity,
    runtime_evaluated_at: datetime,
    provider_identity: str,
    provider_version: str,
    status: Literal["COMPLETED", "FAILED_CLOSED"],
    failure_code: SupervisorFailureCode | None,
    overall_freshness: Freshness,
    decision: MasterSupervisorDecision | None,
) -> MasterShadowAuditEvent:
    digest_material = (
        decision.stable_json()
        if decision is not None
        else json.dumps(
            {
                "constitutionDigest": constitution_identity.constitutionDigest,
                "failureCode": failure_code.value if failure_code else None,
                "mmAssessmentDigest": mm_assessment_digest,
                "overallFreshness": overall_freshness.value,
                "providerIdentity": provider_identity,
                "providerVersion": provider_version,
                "runtimeEvaluatedAt": runtime_evaluated_at.isoformat(),
                "snapshotCapturedAt": snapshot_captured_at.isoformat(),
                "status": status,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    decision_digest = _digest(digest_material)
    event_material = "|".join((
        MASTER_SHADOW_EVENT_TYPE,
        snapshot_captured_at.isoformat(),
        mm_assessment_digest,
        constitution_identity.constitutionDigest,
        runtime_evaluated_at.isoformat(),
        provider_identity,
        provider_version,
        status,
        failure_code.value if failure_code else "NONE",
        decision_digest,
    ))
    return MasterShadowAuditEvent(
        eventId=f"master-shadow-{_digest(event_material)[:24]}",
        snapshotCapturedAt=snapshot_captured_at,
        mmAssessmentDigest=mm_assessment_digest,
        constitutionIdentity=constitution_identity,
        runtimeEvaluatedAt=runtime_evaluated_at,
        providerIdentity=provider_identity,
        providerVersion=provider_version,
        status=status,
        failureCode=failure_code,
        overallFreshness=overall_freshness,
        decisionDigest=decision_digest,
    )
