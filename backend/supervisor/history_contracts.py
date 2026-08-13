"""Immutable sanitized Supervisor history and replay contracts."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import Field, field_validator
from .contracts import HumanAttention, SupervisorAgentId, SupervisorContract, SupervisorMode
from .failure_codes import SupervisorFailureCode

class SupervisorEventType(str, Enum):
    MM_SHADOW_ASSESSMENT="MM_SHADOW_ASSESSMENT"
    MASTER_SHADOW_DECISION="MASTER_SHADOW_DECISION"
    MASTER_CONVERSATION_SUCCESS="MASTER_CONVERSATION_SUCCESS"
    MASTER_CONVERSATION_FAILURE="MASTER_CONVERSATION_FAILURE"
    MM_CONVERSATION_SUCCESS="MM_CONVERSATION_SUCCESS"
    MM_CONVERSATION_FAILURE="MM_CONVERSATION_FAILURE"
    PROVIDER_UNAVAILABLE="PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT="PROVIDER_TIMEOUT"
    PROVIDER_OUTPUT_INVALID="PROVIDER_OUTPUT_INVALID"
    BINDING_FAILURE="BINDING_FAILURE"
    SECURITY_REJECTION="SECURITY_REJECTION"

def _aware(v: datetime|None):
    if v is not None and (v.tzinfo is None or v.utcoffset() is None): raise ValueError("timezone-aware timestamp required")
    return v

class SupervisorHistoryEvent(SupervisorContract):
    schemaVersion: Literal[1]=1
    eventId: str=Field(min_length=1,max_length=100,pattern=r"^[A-Za-z0-9._:-]+$")
    eventType: SupervisorEventType
    agentId: SupervisorAgentId
    mode: Literal[SupervisorMode.SHADOW]=SupervisorMode.SHADOW
    occurredAt: datetime
    conversationId: str|None=Field(default=None,max_length=100)
    snapshotCapturedAt: datetime
    sourceEvaluatedAt: datetime|None=None
    freshness: str|None=Field(default=None,max_length=30)
    status: str=Field(min_length=1,max_length=30)
    failureCode: SupervisorFailureCode|None=None
    humanAttention: HumanAttention|None=None
    operationalEffect: Literal["NONE"]="NONE"
    summary: str=Field(min_length=1,max_length=300)
    decisionDigest: str|None=Field(default=None,pattern=r"^[0-9a-f]{64}$")
    assessmentDigest: str|None=Field(default=None,pattern=r"^[0-9a-f]{64}$")
    providerIdentity: str=Field(min_length=1,max_length=100)
    providerVersion: str=Field(min_length=1,max_length=100)
    contractVersion: Literal["1"]="1"
    _timestamps=field_validator("occurredAt","snapshotCapturedAt","sourceEvaluatedAt")(_aware)

class SupervisorHistoryPage(SupervisorContract):
    schemaVersion: Literal[1]=1
    events: tuple[SupervisorHistoryEvent,...]
    nextCursor: str|None=None
    order: Literal["NEWEST_FIRST"]="NEWEST_FIRST"

class SupervisorReplay(SupervisorContract):
    schemaVersion: Literal[1]=1
    replayMode: Literal["READ_ONLY"]="READ_ONLY"
    sourceEventId: str
    eventType: SupervisorEventType
    agentId: SupervisorAgentId
    occurredAt: datetime
    status: str
    summary: str
    humanAttention: HumanAttention|None=None
    failureCode: SupervisorFailureCode|None=None
    snapshotCapturedAt: datetime
    freshness: str|None=None
    decisionIdentity: str|None=None
    assessmentIdentity: str|None=None
    operationalEffect: Literal["NONE"]="NONE"
    providerCalled: Literal[False]=False
    runtimeCalled: Literal[False]=False
    configurationChanged: Literal[False]=False
    orderAction: Literal["NONE"]="NONE"
