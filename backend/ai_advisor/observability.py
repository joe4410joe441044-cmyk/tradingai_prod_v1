"""Content-free request-scoped AI Advisor observability."""

from enum import Enum
from typing import Optional, Protocol, Tuple

from backend.ai_advisor.conversation_models import AdvisorContractModel


class AdvisorSecurityEventCategory(str, Enum):
    AUTHN_FAILED = "AUTHN_FAILED"
    AUTHZ_DENIED = "AUTHZ_DENIED"
    SOURCE_CONTRACT_INVALID = "SOURCE_CONTRACT_INVALID"
    PROMPT_INJECTION_SUSPECTED = "PROMPT_INJECTION_SUSPECTED"
    SENSITIVE_DATA_BLOCKED = "SENSITIVE_DATA_BLOCKED"
    FRESHNESS_UNSAFE = "FRESHNESS_UNSAFE"
    POLICY_REFUSAL = "POLICY_REFUSAL"


class AdvisorObservation(AdvisorContractModel):
    requestId: str
    status: str
    responseCategory: Optional[str] = None
    failureCode: Optional[str] = None
    refusalReason: Optional[str] = None
    approvedSourceIds: Tuple[str, ...] = ()
    usedSourceTypes: Tuple[str, ...] = ()
    freshness: Tuple[str, ...] = ()
    securityEventCategory: Optional[AdvisorSecurityEventCategory] = None
    latencyMilliseconds: Optional[int] = None


class AdvisorObservationSink(Protocol):
    def record(self, observation: AdvisorObservation) -> None: ...


class NoOpAdvisorObservationSink:
    def record(self, observation: AdvisorObservation) -> None:
        if not isinstance(observation, AdvisorObservation):
            raise TypeError("typed observation required")


class InMemoryAdvisorObservationSink:
    def __init__(self):
        self.records: list[AdvisorObservation] = []

    def record(self, observation: AdvisorObservation) -> None:
        if not isinstance(observation, AdvisorObservation):
            raise TypeError("typed observation required")
        self.records.append(observation)
