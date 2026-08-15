"""Secret-free, internal-only provider failure observation contracts."""

import json
import logging

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Annotated, Literal, Optional, Protocol, Tuple

from pydantic import ConfigDict, Field, model_validator

from backend.ai_advisor.provider_models import AdvisorProviderContractModel


class ProviderSafeReason(str, Enum):
    LIVE_PROVIDER_AUTHENTICATION_FAILED = (
        "LIVE_PROVIDER_AUTHENTICATION_FAILED"
    )
    LIVE_PROVIDER_PERMISSION_DENIED = "LIVE_PROVIDER_PERMISSION_DENIED"
    LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED = (
        "LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED"
    )
    LIVE_PROVIDER_BAD_REQUEST = "LIVE_PROVIDER_BAD_REQUEST"
    LIVE_PROVIDER_TIMEOUT = "LIVE_PROVIDER_TIMEOUT"
    LIVE_PROVIDER_CONNECTION_FAILED = "LIVE_PROVIDER_CONNECTION_FAILED"
    LIVE_PROVIDER_SERVER_ERROR = "LIVE_PROVIDER_SERVER_ERROR"
    LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED = (
        "LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED"
    )
    LIVE_PROVIDER_MODEL_CONTRACT_FAILED = "LIVE_PROVIDER_MODEL_CONTRACT_FAILED"
    LIVE_PROVIDER_STATUS_CONTRACT_FAILED = "LIVE_PROVIDER_STATUS_CONTRACT_FAILED"
    LIVE_PROVIDER_OUTPUT_TEXT_CONTRACT_FAILED = (
        "LIVE_PROVIDER_OUTPUT_TEXT_CONTRACT_FAILED"
    )
    LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED = (
        "LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED"
    )
    LIVE_PROVIDER_CREDENTIAL_UNAVAILABLE = (
        "LIVE_PROVIDER_CREDENTIAL_UNAVAILABLE"
    )
    LIVE_PROVIDER_UNKNOWN_FAILURE = "LIVE_PROVIDER_UNKNOWN_FAILURE"


class ProviderFailureCategory(str, Enum):
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    RATE_LIMIT = "RATE_LIMIT"
    MODEL_NOT_FOUND_OR_UNAVAILABLE = "MODEL_NOT_FOUND_OR_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    STRUCTURED_OUTPUT_OR_RESPONSE_FORMAT = "STRUCTURED_OUTPUT_OR_RESPONSE_FORMAT"
    TIMEOUT = "TIMEOUT"
    NETWORK_OR_TRANSPORT = "NETWORK_OR_TRANSPORT"
    PROVIDER_SERVER_ERROR = "PROVIDER_SERVER_ERROR"
    RESPONSE_VALIDATION = "RESPONSE_VALIDATION"
    CLIENT_CONFIGURATION = "CLIENT_CONFIGURATION"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    UNKNOWN_PROVIDER_FAILURE = "UNKNOWN_PROVIDER_FAILURE"


class ProviderErrorType(str, Enum):
    INVALID_REQUEST_ERROR = "invalid_request_error"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_ERROR = "permission_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    SERVER_ERROR = "server_error"


class ProviderErrorCode(str, Enum):
    MODEL_NOT_FOUND = "model_not_found"
    MODEL_NOT_AVAILABLE = "model_not_available"
    INVALID_RESPONSE_FORMAT = "invalid_response_format"
    UNSUPPORTED_RESPONSE_FORMAT = "unsupported_response_format"


class ProviderFailureStage(str, Enum):
    CONFIGURATION = "CONFIGURATION"
    CREDENTIAL_RESOLUTION = "CREDENTIAL_RESOLUTION"
    CLIENT_CREATION = "CLIENT_CREATION"
    PROVIDER_INVOCATION = "PROVIDER_INVOCATION"
    RESPONSE_VALIDATION = "RESPONSE_VALIDATION"
    UNKNOWN = "UNKNOWN"


class ResponseValidationCode(str, Enum):
    JSON_DECODE_FAILED = "JSON_DECODE_FAILED"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    TOP_LEVEL_NOT_OBJECT = "TOP_LEVEL_NOT_OBJECT"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    UNEXPECTED_FIELD = "UNEXPECTED_FIELD"
    FIELD_TYPE_INVALID = "FIELD_TYPE_INVALID"
    ENUM_VALUE_INVALID = "ENUM_VALUE_INVALID"
    NULL_NOT_ALLOWED = "NULL_NOT_ALLOWED"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    NESTED_SCHEMA_INVALID = "NESTED_SCHEMA_INVALID"
    RESPONSE_CANDIDATE_INVALID = "RESPONSE_CANDIDATE_INVALID"
    UNKNOWN_RESPONSE_CONTRACT_FAILURE = "UNKNOWN_RESPONSE_CONTRACT_FAILURE"


class ResponseTopLevelType(str, Enum):
    OBJECT = "OBJECT"
    ARRAY = "ARRAY"
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    NULL = "NULL"
    UNKNOWN = "UNKNOWN"


class ResponseContractField(str, Enum):
    RESPONSE_VERSION = "responseVersion"
    REQUEST_ID = "requestId"
    PROMPT_VERSION = "promptVersion"
    SUMMARY = "summary"
    FACTS = "facts"
    INFERENCES = "inferences"
    UNKNOWNS = "unknowns"
    WARNINGS = "warnings"
    SOURCE_REFERENCES = "sourceReferences"
    FRESHNESS_DISCLOSURES = "freshnessDisclosures"
    SAFETY_DISCLOSURES = "safetyDisclosures"
    UNKNOWN_OR_UNEXPECTED = "UNKNOWN_OR_UNEXPECTED"


MissingResponseFields = Annotated[
    Tuple[ResponseContractField, ...],
    Field(max_length=11, strict=False),
]


class ResponseContractDiagnostic(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    parseSucceeded: Literal[False] = False
    validationCode: ResponseValidationCode
    topLevelType: ResponseTopLevelType
    invalidField: Optional[ResponseContractField] = None
    missingFields: MissingResponseFields = ()

    @model_validator(mode="after")
    def validate_diagnostic(self) -> "ResponseContractDiagnostic":
        if len(set(self.missingFields)) != len(self.missingFields):
            raise ValueError("missingFields must be unique")
        if ResponseContractField.UNKNOWN_OR_UNEXPECTED in self.missingFields:
            raise ValueError("missingFields must use known schema fields")
        schema_order = tuple(
            field
            for field in ResponseContractField
            if field is not ResponseContractField.UNKNOWN_OR_UNEXPECTED
        )
        if self.missingFields != tuple(
            field for field in schema_order if field in set(self.missingFields)
        ):
            raise ValueError("missingFields must use stable schema order")
        if (
            self.validationCode is ResponseValidationCode.REQUIRED_FIELD_MISSING
        ) != bool(self.missingFields):
            raise ValueError("missingFields must match validationCode")
        if (
            self.validationCode is ResponseValidationCode.UNEXPECTED_FIELD
            and self.invalidField
            is not ResponseContractField.UNKNOWN_OR_UNEXPECTED
        ):
            raise ValueError("unexpected fields must not expose their names")
        return self


class ProviderFailureObservation(AdvisorProviderContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )

    provider: Literal["OPENAI"] = "OPENAI"
    model: Optional[str] = Field(default=None, min_length=1, max_length=128)
    requestId: Optional[str] = Field(default=None, min_length=1, max_length=128)
    providerRequestId: Optional[str] = Field(default=None, min_length=1, max_length=128)
    category: ProviderFailureCategory = ProviderFailureCategory.UNKNOWN_PROVIDER_FAILURE
    safeReason: ProviderSafeReason
    failureStage: ProviderFailureStage
    httpStatus: Optional[int] = Field(default=None, ge=400, le=599)
    providerErrorType: Optional[ProviderErrorType] = None
    providerErrorCode: Optional[ProviderErrorCode] = None
    retryable: Optional[bool] = None
    durationMilliseconds: Optional[int] = Field(default=None, ge=0, le=120_000)
    observedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    providerRequestUpperBound: Literal[1] = 1
    retryPerformed: Literal[False] = False
    liveInvocationAttempted: bool
    invocationSucceeded: Literal[False] = False
    parseSucceeded: Optional[Literal[False]] = None
    validationCode: Optional[ResponseValidationCode] = None
    topLevelType: Optional[ResponseTopLevelType] = None
    invalidField: Optional[ResponseContractField] = None
    missingFields: MissingResponseFields = ()

    @model_validator(mode="after")
    def validate_response_diagnostic(self) -> "ProviderFailureObservation":
        diagnostic_values = (
            self.parseSucceeded,
            self.validationCode,
            self.topLevelType,
            self.invalidField,
        )
        has_diagnostic = any(value is not None for value in diagnostic_values) or bool(
            self.missingFields
        )
        if not has_diagnostic:
            return self
        if (
            self.safeReason
            is not ProviderSafeReason.LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED
            or self.failureStage is not ProviderFailureStage.RESPONSE_VALIDATION
            or self.parseSucceeded is not False
            or self.validationCode is None
            or self.topLevelType is None
        ):
            raise ValueError("response diagnostic requires contract failure")
        ResponseContractDiagnostic(
            parseSucceeded=False,
            validationCode=self.validationCode,
            topLevelType=self.topLevelType,
            invalidField=self.invalidField,
            missingFields=self.missingFields,
        )
        return self


class ProviderFailureObservationSink(Protocol):
    def observe(self, observation: ProviderFailureObservation) -> None:
        """Record one allowlisted failure without raw exception material."""


@dataclass(frozen=True)
class NoOpProviderFailureObservationSink:
    def observe(self, observation: ProviderFailureObservation) -> None:
        return None


@dataclass
class StructuredLoggingProviderFailureObservationSink:
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("TradingAI.AIAdvisor"))

    def observe(self, observation: ProviderFailureObservation) -> None:
        trusted = ProviderFailureObservation.model_validate(observation.model_dump(warnings=False))
        payload = trusted.model_dump(mode="json", exclude_none=True)
        self.logger.warning("ai_advisor_provider_failure %s", json.dumps(payload, sort_keys=True, separators=(",", ":")))


@dataclass
class RecordingProviderFailureObservationSink:
    _observation: ProviderFailureObservation | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def observe(self, observation: ProviderFailureObservation) -> None:
        trusted = ProviderFailureObservation.model_validate(
            observation.model_dump(warnings=False)
        )
        with self._lock:
            if self._observation is None:
                self._observation = trusted

    @property
    def observation(self) -> ProviderFailureObservation | None:
        with self._lock:
            return self._observation
