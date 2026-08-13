"""Bounded contracts for non-operational Supervisor conversations."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import HumanAttention, SupervisorAgentId, SupervisorContract, SupervisorMode
from .failure_codes import SupervisorFailureCode


class ConversationStatus(str, Enum):
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED_CLOSED = "FAILED_CLOSED"


class SupervisorConversationRequest(SupervisorContract):
    schemaVersion: Literal[1] = 1
    agentId: SupervisorAgentId
    message: str = Field(min_length=1, max_length=1000)
    conversationId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    requestedAt: datetime

    @field_validator("message")
    @classmethod
    def non_blank_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value

    @field_validator("requestedAt")
    @classmethod
    def aware_request_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requestedAt must be timezone-aware")
        return value


class SupervisorConversationProviderOutput(SupervisorContract):
    answer: str = Field(min_length=1, max_length=1000)
    warnings: tuple[str, ...] = Field(default=(), max_length=10)

    @field_validator("answer")
    @classmethod
    def safe_answer(cls, value: str) -> str:
        value = value.strip()
        if not value or re.search(r"<[^>]+>", value):
            raise ValueError("answer must be bounded plain text")
        return value

    @field_validator("warnings")
    @classmethod
    def safe_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 200 or re.search(r"<[^>]+>", value) for value in values):
            raise ValueError("warnings must be bounded plain text")
        return values


class SupervisorConversationResponse(SupervisorContract):
    schemaVersion: Literal[1] = 1
    agentId: SupervisorAgentId
    conversationId: str = Field(min_length=1, max_length=100)
    messageId: str = Field(min_length=1, max_length=100)
    mode: Literal[SupervisorMode.SHADOW] = SupervisorMode.SHADOW
    status: ConversationStatus
    answer: str = Field(min_length=1, max_length=1000)
    humanAttention: HumanAttention
    operationalEffect: Literal["NONE"] = "NONE"
    configurationChanged: Literal[False] = False
    snapshotCapturedAt: datetime
    decisionIdentity: str | None = Field(default=None, max_length=100)
    assessmentIdentity: str | None = Field(default=None, max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=10)
    failureCode: SupervisorFailureCode | None = None
    respondedAt: datetime

    @model_validator(mode="after")
    def coherent_response(self) -> "SupervisorConversationResponse":
        for timestamp in (self.snapshotCapturedAt, self.respondedAt):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("response timestamps must be timezone-aware")
        if self.status is ConversationStatus.COMPLETED and self.failureCode is not None:
            raise ValueError("completed response cannot contain a failure")
        if self.status is not ConversationStatus.COMPLETED and self.failureCode is None:
            raise ValueError("non-completed response requires a failure")
        return self
