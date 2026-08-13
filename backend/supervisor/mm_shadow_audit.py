"""Bounded immutable audit event construction for MM SHADOW evaluations."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import Freshness, MMSupervisorAssessment, SupervisorAgentId, SupervisorContract, SupervisorMode
from .failure_codes import SupervisorFailureCode


MM_SHADOW_EVENT_TYPE = "MM_SHADOW_ASSESSMENT"
MM_SHADOW_CONTRACT_VERSION = "1"


class MMShadowAuditEvent(SupervisorContract):
    eventId: str = Field(min_length=1, max_length=80)
    eventType: Literal["MM_SHADOW_ASSESSMENT"] = MM_SHADOW_EVENT_TYPE
    agentId: Literal[SupervisorAgentId.MM_SUPERVISOR] = SupervisorAgentId.MM_SUPERVISOR
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    snapshotCapturedAt: datetime
    sourceEvaluatedAt: datetime | None = None
    runtimeEvaluatedAt: datetime
    providerIdentity: str = Field(min_length=1, max_length=100)
    providerVersion: str = Field(min_length=1, max_length=100)
    contractVersion: Literal["1"] = MM_SHADOW_CONTRACT_VERSION
    status: Literal["COMPLETED", "FAILED_CLOSED"]
    failureCode: SupervisorFailureCode | None = None
    overallFreshness: Freshness
    operationalEffect: Literal["NONE"] = "NONE"
    assessmentDigest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("snapshotCapturedAt", "sourceEvaluatedAt", "runtimeEvaluatedAt")
    @classmethod
    def aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("audit timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def coherent_outcome(self) -> "MMShadowAuditEvent":
        if self.status == "COMPLETED" and self.failureCode is not None:
            raise ValueError("completed audit event cannot contain a failure")
        if self.status == "FAILED_CLOSED" and self.failureCode is None:
            raise ValueError("failed audit event requires a failure code")
        return self


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def build_mm_shadow_audit_event(
    *,
    snapshot_captured_at: datetime,
    source_evaluated_at: datetime | None,
    runtime_evaluated_at: datetime,
    provider_identity: str,
    provider_version: str,
    status: Literal["COMPLETED", "FAILED_CLOSED"],
    failure_code: SupervisorFailureCode | None,
    overall_freshness: Freshness,
    assessment: MMSupervisorAssessment | None,
) -> MMShadowAuditEvent:
    """Hash only validated output or bounded outcome metadata, never raw provider data."""
    digest_material = (
        assessment.stable_json()
        if assessment is not None
        else json.dumps(
            {
                "failureCode": failure_code.value if failure_code else None,
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
    assessment_digest = _digest(digest_material)
    event_material = "|".join(
        (
            MM_SHADOW_EVENT_TYPE,
            snapshot_captured_at.isoformat(),
            runtime_evaluated_at.isoformat(),
            provider_identity,
            provider_version,
            status,
            failure_code.value if failure_code else "NONE",
            assessment_digest,
        )
    )
    return MMShadowAuditEvent(
        eventId=f"mm-shadow-{_digest(event_material)[:24]}",
        snapshotCapturedAt=snapshot_captured_at,
        sourceEvaluatedAt=source_evaluated_at,
        runtimeEvaluatedAt=runtime_evaluated_at,
        providerIdentity=provider_identity,
        providerVersion=provider_version,
        status=status,
        failureCode=failure_code,
        overallFreshness=overall_freshness,
        assessmentDigest=assessment_digest,
    )
