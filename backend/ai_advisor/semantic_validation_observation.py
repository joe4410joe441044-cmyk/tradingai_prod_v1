"""Secret-free observations for unexpected semantic-validation exceptions.

The Advisor response semantic validator must be total: for every syntactically
valid AdvisorResponseCandidate it returns either VALID, VALID_WITH_WARNINGS or
REJECTED. If an unexpected exception escapes the semantic path it must be
converted into a controlled REJECTED result and recorded here so a future
failure is attributable to a specific validation stage without exposing
credentials, raw provider text, or sensitive account data.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Protocol

from pydantic import Field, ValidationError

from backend.ai_advisor.provider_models import AdvisorProviderContractModel


class SemanticValidationPhase(str, Enum):
    CLAIM_DETECTION = "CLAIM_DETECTION"
    GROUNDING = "GROUNDING"
    INTEGRITY = "INTEGRITY"
    ENVELOPE_CONSTRUCTION = "ENVELOPE_CONSTRUCTION"
    SERIALIZATION = "SERIALIZATION"
    UNKNOWN = "UNKNOWN"


class SemanticValidationSafeReason(str, Enum):
    UNEXPECTED_VALIDATION_EXCEPTION = "UNEXPECTED_VALIDATION_EXCEPTION"


class SemanticValidationObservation(AdvisorProviderContractModel):
    requestId: str
    validationStage: SemanticValidationPhase
    exceptionClass: str
    safeReason: Literal["UNEXPECTED_VALIDATION_EXCEPTION"]
    ruleIdentifier: str
    responseCategory: Literal["REJECTED"] = "REJECTED"
    pydanticErrorType: Optional[str] = Field(default=None, max_length=64)
    pydanticFieldPath: Optional[str] = Field(default=None, max_length=256)


class SemanticValidationObservationSink(Protocol):
    def observe(self, observation: SemanticValidationObservation) -> None: ...


@dataclass(frozen=True)
class NoOpSemanticValidationObservationSink:
    def observe(self, observation: SemanticValidationObservation) -> None:
        return None


@dataclass
class RecordingSemanticValidationObservationSink:
    records: list[SemanticValidationObservation] = field(default_factory=list)

    def observe(self, observation: SemanticValidationObservation) -> None:
        self.records.append(
            SemanticValidationObservation.model_validate(
                observation.model_dump(warnings=False)
            )
        )


@dataclass(frozen=True)
class StructuredLoggingSemanticValidationObservationSink:
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("TradingAI.AIAdvisor")
    )

    def observe(self, observation: SemanticValidationObservation) -> None:
        trusted = SemanticValidationObservation.model_validate(
            observation.model_dump(warnings=False)
        )
        self.logger.warning(
            "ai_advisor_validation_exception %s",
            json.dumps(
                trusted.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


def safe_rule_identifier(exception: Exception) -> str:
    """Return a secret-free field/rule identifier without revealing values.

    Only schema field names (never input values) are surfaced from a pydantic
    ValidationError; otherwise the stable exception class name is used.
    """
    if isinstance(exception, ValidationError):
        errors = exception.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
        for error in errors:
            location = error.get("loc", ())
            if location and isinstance(location[0], str):
                return location[0]
        return "RESPONSE_ENVELOPE"
    return type(exception).__name__


def safe_validation_error_location(exception: Exception) -> Optional[str]:
    """Return a bounded, value-free pydantic field path (or None)."""
    if not isinstance(exception, ValidationError):
        return None
    try:
        errors = exception.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    except Exception:  # noqa: BLE001
        return None
    for error in errors:
        location = error.get("loc", ())
        if not location:
            continue
        parts = []
        for part in location:
            if isinstance(part, str) and not part.isdigit():
                parts.append(part)
            elif isinstance(part, int):
                parts.append(f"[{part}]")
            else:
                return None
        if parts:
            return ".".join(parts)[:256]
    return None


def safe_validation_error_type(exception: Exception) -> Optional[str]:
    """Return the stable pydantic error type keyword (never input values)."""
    if not isinstance(exception, ValidationError):
        return None
    try:
        errors = exception.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    except Exception:  # noqa: BLE001
        return None
    for error in errors:
        error_type = error.get("type")
        if isinstance(error_type, str) and error_type:
            return error_type[:64]
    return None


def project_semantic_validation_exception(
    *,
    request_id: str,
    stage: SemanticValidationPhase,
    exception: Exception,
    rule_identifier: str,
) -> SemanticValidationObservation:
    return SemanticValidationObservation(
        requestId=request_id,
        validationStage=stage,
        exceptionClass=type(exception).__name__,
        safeReason=SemanticValidationSafeReason.UNEXPECTED_VALIDATION_EXCEPTION.value,
        ruleIdentifier=rule_identifier,
        responseCategory="REJECTED",
        pydanticErrorType=safe_validation_error_type(exception),
        pydanticFieldPath=safe_validation_error_location(exception),
    )
