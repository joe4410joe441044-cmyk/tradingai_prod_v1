"""Pure, read-only contracts for future AI Advisor conversation processing."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, List, Literal, Optional, Tuple

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.ai_advisor.models import AdvisorErrorDetail

SCHEMA_VERSION = "1.0"
MAX_USER_MESSAGE_LENGTH = 8_000
MAX_CONVERSATION_MESSAGES = 20
MAX_CONVERSATION_CHARACTERS = 40_000
MAX_SOURCES = 32
MAX_SOURCE_REFERENCES_PER_ITEM = 16
MAX_WARNINGS = 32
MAX_CLAIMS = 64
MAX_EVIDENCE = 64
MAX_RESPONSE_SECTIONS = 16
MAX_RESPONSE_CHARACTERS = 32_000

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
VersionText = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=256)]
MessageText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_USER_MESSAGE_LENGTH),
]
BodyText = Annotated[str, StringConstraints(min_length=1, max_length=8_000)]
SummaryText = Annotated[str, StringConstraints(min_length=1, max_length=4_000)]


class AdvisorContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _reject_control_characters(value: str, *, multiline: bool = False) -> str:
    if not value.strip():
        raise ValueError("value must contain non-whitespace characters")
    allowed = {"\n", "\r", "\t"} if multiline else set()
    if any(ord(character) < 32 and character not in allowed for character in value):
        raise ValueError("control characters are not allowed")
    return value


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


class AuthenticationState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


class AuthorizationState(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"
    NOT_EVALUATED = "NOT_EVALUATED"


class AdvisorRequestType(str, Enum):
    EXPLAIN = "EXPLAIN"
    SUMMARIZE = "SUMMARIZE"
    COMPARE = "COMPARE"
    DIAGNOSE = "DIAGNOSE"
    NAVIGATE = "NAVIGATE"
    CLARIFY = "CLARIFY"
    STATUS_EXPLANATION = "STATUS_EXPLANATION"
    SPECIFICATION_QUESTION = "SPECIFICATION_QUESTION"


class AdvisorDataAccessScope(str, Enum):
    APPROVED_LOCAL_SPECIFICATIONS = "APPROVED_LOCAL_SPECIFICATIONS"
    SANITIZED_RUNTIME_SUMMARY = "SANITIZED_RUNTIME_SUMMARY"
    SANITIZED_MARKET_INTELLIGENCE_SUMMARY = "SANITIZED_MARKET_INTELLIGENCE_SUMMARY"
    SANITIZED_MONEY_MANAGEMENT_SUMMARY = "SANITIZED_MONEY_MANAGEMENT_SUMMARY"
    PUBLIC_UI_NAVIGATION = "PUBLIC_UI_NAVIGATION"


class SensitiveClassification(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"
    UNKNOWN = "UNKNOWN"


class AdvisorDetailLevel(str, Enum):
    BRIEF = "BRIEF"
    STANDARD = "STANDARD"
    DETAILED = "DETAILED"


class AdvisorResponseFormat(str, Enum):
    PLAIN_TEXT = "PLAIN_TEXT"
    STRUCTURED = "STRUCTURED"


class AdvisorRole(str, Enum):
    USER = "USER"
    ADVISOR = "ADVISOR"


class AdvisorCapability(str, Enum):
    RUNTIME_STATUS_EXPLAIN = "RUNTIME_STATUS_EXPLAIN"
    SPECIFICATION_EXPLAIN = "SPECIFICATION_EXPLAIN"
    MARKET_INTELLIGENCE_EXPLAIN = "MARKET_INTELLIGENCE_EXPLAIN"
    TRADING_DECISION_EXPLAIN = "TRADING_DECISION_EXPLAIN"
    MONEY_MANAGEMENT_EXPLAIN = "MONEY_MANAGEMENT_EXPLAIN"
    GOVERNANCE_EXPLAIN = "GOVERNANCE_EXPLAIN"
    EXECUTION_RESULT_EXPLAIN = "EXECUTION_RESULT_EXPLAIN"
    SYSTEM_GUIDANCE = "SYSTEM_GUIDANCE"


class AdvisorSourceType(str, Enum):
    RUNTIME = "RUNTIME"
    SPECIFICATION = "SPECIFICATION"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    TRADING_DECISION = "TRADING_DECISION"
    MONEY_MANAGEMENT = "MONEY_MANAGEMENT"
    GOVERNANCE = "GOVERNANCE"
    EXECUTION_RESULT = "EXECUTION_RESULT"
    CONVERSATION = "CONVERSATION"


class AdvisorSourceAuthority(str, Enum):
    RUNTIME_AUTHORITATIVE = "RUNTIME_AUTHORITATIVE"
    SPECIFICATION_AUTHORITATIVE = "SPECIFICATION_AUTHORITATIVE"
    APPROVED_DERIVED = "APPROVED_DERIVED"
    CONVERSATION_CONTEXT = "CONVERSATION_CONTEXT"
    UNKNOWN = "UNKNOWN"


class AdvisorFreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    LAST_GOOD = "LAST_GOOD"
    EXPIRED = "EXPIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AdvisorResponseStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    REFUSED = "REFUSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR = "ERROR"


class AdvisorResponseCategory(str, Enum):
    STATUS_EXPLANATION = "STATUS_EXPLANATION"
    DECISION_EXPLANATION = "DECISION_EXPLANATION"
    RISK_EXPLANATION = "RISK_EXPLANATION"
    SYSTEM_GUIDANCE = "SYSTEM_GUIDANCE"
    SPECIFICATION_LOOKUP = "SPECIFICATION_LOOKUP"
    TROUBLESHOOTING = "TROUBLESHOOTING"
    SAFETY_REFUSAL = "SAFETY_REFUSAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AdvisorClaimType(str, Enum):
    FACT = "FACT"
    INTERPRETATION = "INTERPRETATION"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


class AdvisorSectionType(str, Enum):
    SUMMARY = "SUMMARY"
    CURRENT_STATUS = "CURRENT_STATUS"
    EXPLANATION = "EXPLANATION"
    EVIDENCE = "EVIDENCE"
    LIMITATION = "LIMITATION"
    SAFETY_NOTICE = "SAFETY_NOTICE"
    NEXT_SAFE_STEP = "NEXT_SAFE_STEP"


class AdvisorRefusalCode(str, Enum):
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    MUTATION_NOT_ALLOWED = "MUTATION_NOT_ALLOWED"
    TRADING_INSTRUCTION_NOT_ALLOWED = "TRADING_INSTRUCTION_NOT_ALLOWED"
    ORDER_OPERATION_NOT_ALLOWED = "ORDER_OPERATION_NOT_ALLOWED"
    GOVERNANCE_OVERRIDE_NOT_ALLOWED = "GOVERNANCE_OVERRIDE_NOT_ALLOWED"
    MONEY_MANAGEMENT_OVERRIDE_NOT_ALLOWED = "MONEY_MANAGEMENT_OVERRIDE_NOT_ALLOWED"
    STRATEGY_OVERRIDE_NOT_ALLOWED = "STRATEGY_OVERRIDE_NOT_ALLOWED"
    CONFIGURATION_CHANGE_NOT_ALLOWED = "CONFIGURATION_CHANGE_NOT_ALLOWED"
    SENSITIVE_DATA_REQUEST = "SENSITIVE_DATA_REQUEST"
    PROMPT_INJECTION_SUSPECTED = "PROMPT_INJECTION_SUSPECTED"
    EXTERNAL_SEND_NOT_ALLOWED = "EXTERNAL_SEND_NOT_ALLOWED"
    PERSISTENCE_NOT_ALLOWED = "PERSISTENCE_NOT_ALLOWED"


class AdvisorWarningCode(str, Enum):
    STALE_SOURCE = "STALE_SOURCE"
    LAST_GOOD_SOURCE = "LAST_GOOD_SOURCE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    SOURCE_OMITTED = "SOURCE_OMITTED"
    CONTEXT_TRUNCATED = "CONTEXT_TRUNCATED"
    UNSUPPORTED_LOCALE = "UNSUPPORTED_LOCALE"
    SENSITIVE_CONTENT_REMOVED = "SENSITIVE_CONTENT_REMOVED"


class SensitiveFilterStatus(str, Enum):
    CLEAN = "CLEAN"
    MODIFIED = "MODIFIED"
    BLOCKED = "BLOCKED"


class SensitiveCategory(str, Enum):
    API_CREDENTIAL = "API_CREDENTIAL"
    AUTHORIZATION_HEADER = "AUTHORIZATION_HEADER"
    COOKIE_OR_SESSION = "COOKIE_OR_SESSION"
    PERSONAL_DATA = "PERSONAL_DATA"
    ACCOUNT_IDENTIFIER = "ACCOUNT_IDENTIFIER"
    FILESYSTEM_PATH = "FILESYSTEM_PATH"
    STACK_TRACE = "STACK_TRACE"
    RAW_RUNTIME = "RAW_RUNTIME"
    RAW_EXCHANGE_DATA = "RAW_EXCHANGE_DATA"


class AdvisorPermissionContext(AdvisorContractModel):
    principalId: Optional[Identifier]
    authenticationState: AuthenticationState
    authorizationState: AuthorizationState
    role: Literal["USER"]
    permissionLevel: Literal["READ_ONLY"]
    allowedCapabilities: Annotated[
        Tuple[AdvisorCapability, ...],
        Field(max_length=8, strict=False),
    ]
    dataAccessScope: Annotated[
        Tuple[AdvisorDataAccessScope, ...],
        Field(default_factory=tuple, max_length=5, strict=False),
    ]
    policyVersion: VersionText
    trustedServerContext: Literal[True]
    readOnly: Literal[True] = True
    explanationOnly: Literal[True] = True
    runtimeMutationAllowed: Literal[False] = False
    configurationMutationAllowed: Literal[False] = False
    executionAllowed: Literal[False] = False
    governanceOverrideAllowed: Literal[False] = False
    moneyManagementOverrideAllowed: Literal[False] = False
    strategyOverrideAllowed: Literal[False] = False

    @field_validator("principalId", "role", "policyVersion")
    @classmethod
    def validate_safe_text(cls, value: Optional[str]) -> Optional[str]:
        return _reject_control_characters(value) if value is not None else None

    @model_validator(mode="after")
    def validate_auth_invariants(self) -> "AdvisorPermissionContext":
        if (
            self.authenticationState is AuthenticationState.AUTHENTICATED
            and self.principalId is None
        ):
            raise ValueError("authenticated context requires principalId")
        if (
            self.authorizationState is AuthorizationState.AUTHORIZED
            and self.authenticationState is not AuthenticationState.AUTHENTICATED
        ):
            raise ValueError("authorization requires authentication")
        if len(set(self.allowedCapabilities)) != len(self.allowedCapabilities):
            raise ValueError("allowedCapabilities must be unique")
        if len(set(self.dataAccessScope)) != len(self.dataAccessScope):
            raise ValueError("dataAccessScope must be unique")
        return self

    @property
    def conversationAllowed(self) -> bool:
        return (
            self.trustedServerContext is True
            and self.authenticationState is AuthenticationState.AUTHENTICATED
            and self.authorizationState is AuthorizationState.AUTHORIZED
            and self.principalId is not None
        )


class AdvisorAuthenticationContext(AdvisorContractModel):
    state: AuthenticationState
    principalId: Optional[Identifier] = None
    sessionId: Optional[Identifier] = None
    authenticatedAt: Optional[datetime] = None
    expiresAt: Optional[datetime] = None
    provider: Optional[ShortText] = None
    reason: Optional[ShortText] = None

    @field_validator("authenticatedAt", "expiresAt")
    @classmethod
    def normalize_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _utc_datetime(value) if value is not None else None

    @field_serializer("authenticatedAt", "expiresAt", when_used="json")
    def serialize_timestamp(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat().replace("+00:00", "Z") if value else None

    @model_validator(mode="after")
    def validate_authentication(self) -> "AdvisorAuthenticationContext":
        if self.state is AuthenticationState.AUTHENTICATED:
            if self.principalId is None or self.authenticatedAt is None:
                raise ValueError("authenticated context requires principal and time")
            if self.expiresAt is not None and self.expiresAt <= self.authenticatedAt:
                raise ValueError("authentication expiry must follow authentication")
        elif self.reason is None:
            raise ValueError("non-authenticated state requires reason")
        return self


class AdvisorAuthorizationContext(AdvisorContractModel):
    state: AuthorizationState
    principalId: Optional[Identifier]
    allowedCapabilities: Annotated[
        Tuple[AdvisorCapability, ...],
        Field(max_length=8, strict=False),
    ]
    dataAccessScope: Annotated[
        Tuple[AdvisorDataAccessScope, ...],
        Field(max_length=5, strict=False),
    ]
    evaluatedAt: datetime
    reason: Optional[ShortText] = None

    @field_validator("evaluatedAt")
    @classmethod
    def normalize_evaluated_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("evaluatedAt", when_used="json")
    def serialize_evaluated_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_authorization(self) -> "AdvisorAuthorizationContext":
        if self.state is AuthorizationState.AUTHORIZED and self.principalId is None:
            raise ValueError("authorized context requires principal")
        if self.state is not AuthorizationState.AUTHORIZED and self.reason is None:
            raise ValueError("non-authorized state requires reason")
        if len(set(self.allowedCapabilities)) != len(self.allowedCapabilities):
            raise ValueError("allowedCapabilities must be unique")
        if len(set(self.dataAccessScope)) != len(self.dataAccessScope):
            raise ValueError("dataAccessScope must be unique")
        return self


class AdvisorFreshnessMetadata(AdvisorContractModel):
    state: AdvisorFreshnessState
    capturedAt: datetime
    sourceUpdatedAt: Optional[datetime]
    ageSeconds: Optional[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    isLastGood: bool
    validUntil: Optional[datetime] = None
    reason: Optional[ShortText] = None
    lastGoodAt: Optional[datetime] = None
    currentReadFailedAt: Optional[datetime] = None
    failureReason: Optional[ShortText] = None
    staleWarning: Optional[ShortText] = None

    @field_validator(
        "capturedAt",
        "sourceUpdatedAt",
        "validUntil",
        "lastGoodAt",
        "currentReadFailedAt",
    )
    @classmethod
    def normalize_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _utc_datetime(value) if value is not None else None

    @field_serializer(
        "capturedAt",
        "sourceUpdatedAt",
        "validUntil",
        "lastGoodAt",
        "currentReadFailedAt",
        when_used="json",
    )
    def serialize_timestamp(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat().replace("+00:00", "Z") if value else None

    @model_validator(mode="after")
    def validate_freshness(self) -> "AdvisorFreshnessMetadata":
        if self.sourceUpdatedAt is not None and self.sourceUpdatedAt > self.capturedAt:
            if self.state is not AdvisorFreshnessState.UNKNOWN:
                raise ValueError("future source timestamp requires UNKNOWN freshness")
            if self.ageSeconds is not None:
                raise ValueError("future source timestamp cannot have ageSeconds")
        if self.state is AdvisorFreshnessState.LAST_GOOD:
            if (
                not self.isLastGood
                or self.sourceUpdatedAt is None
                or self.lastGoodAt is None
                or self.currentReadFailedAt is None
                or self.failureReason is None
                or self.staleWarning is None
            ):
                raise ValueError("LAST_GOOD requires failure and stale metadata")
        elif self.isLastGood:
            raise ValueError("isLastGood requires LAST_GOOD state")
        if self.sourceUpdatedAt is None and self.state in {
            AdvisorFreshnessState.FRESH,
            AdvisorFreshnessState.STALE,
            AdvisorFreshnessState.LAST_GOOD,
        }:
            raise ValueError("known freshness requires sourceUpdatedAt")
        if (
            self.state
            in {
                AdvisorFreshnessState.FRESH,
                AdvisorFreshnessState.STALE,
                AdvisorFreshnessState.LAST_GOOD,
            }
            and self.ageSeconds is None
        ):
            raise ValueError("known freshness requires ageSeconds")
        if (
            self.sourceUpdatedAt is not None
            and self.sourceUpdatedAt <= self.capturedAt
            and self.ageSeconds is not None
        ):
            actual_age = (self.capturedAt - self.sourceUpdatedAt).total_seconds()
            if abs(self.ageSeconds - actual_age) > 0.001:
                raise ValueError("ageSeconds does not match source timestamps")
        if self.validUntil is not None and self.capturedAt > self.validUntil:
            raise ValueError("validUntil cannot precede capturedAt")
        if self.state is AdvisorFreshnessState.FRESH and self.validUntil is None:
            raise ValueError("FRESH requires validUntil")
        if self.state is AdvisorFreshnessState.UNKNOWN and self.reason is None:
            raise ValueError("UNKNOWN requires reason")
        return self


class AdvisorSourceReference(AdvisorContractModel):
    sourceId: Identifier
    sourceType: AdvisorSourceType
    sourceVersion: VersionText
    capturedAt: datetime
    freshness: AdvisorFreshnessMetadata
    authority: AdvisorSourceAuthority
    contentHash: Optional[
        Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
    ] = None
    displayLabel: ShortText
    documentPath: Optional[ShortText] = None
    approved: bool = True
    sanitized: Literal[True] = True
    sensitivity: Literal[
        SensitiveClassification.PUBLIC,
        SensitiveClassification.INTERNAL,
    ] = SensitiveClassification.INTERNAL

    @field_validator("sourceId", "sourceVersion", "displayLabel")
    @classmethod
    def validate_safe_text(cls, value: str) -> str:
        return _reject_control_characters(value)

    @field_validator("documentPath")
    @classmethod
    def validate_document_path(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _reject_control_characters(value)
        if value.startswith(("/", "\\")) or ".." in value.split("/"):
            raise ValueError("documentPath must be a safe logical relative path")
        if not value.startswith("docs/"):
            raise ValueError("documentPath must be under approved docs root")
        return value

    @field_validator("capturedAt")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("capturedAt", when_used="json")
    def serialize_captured_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_timestamps(self) -> "AdvisorSourceReference":
        if self.capturedAt != self.freshness.capturedAt:
            raise ValueError("source and freshness capturedAt must match")
        if self.sourceType is AdvisorSourceType.SPECIFICATION:
            if self.documentPath is None or not self.approved:
                raise ValueError(
                    "specification source must be approved and path-scoped"
                )
        elif self.documentPath is not None:
            raise ValueError("documentPath is only valid for specification sources")
        return self


class AdvisorRuntimeContext(AdvisorContractModel):
    schemaVersion: Literal["1.0"]
    sourceId: Identifier
    state: Literal["NOT_CONNECTED", "STOPPED", "RUNNING", "UNKNOWN"]
    mode: Optional[Literal["PAPER", "LIVE"]]
    exchange: Optional[ShortText]
    symbol: Optional[ShortText]
    loopEnabled: bool
    loopState: Literal[
        "NOT_CONNECTED",
        "STOPPED",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "UNKNOWN",
    ]
    autoTradeEnabled: bool
    emergencyLocked: bool
    emergencyState: Literal[
        "READY",
        "PROCESSING",
        "LOCKED",
        "ACTION_REQUIRED",
        "UNKNOWN",
    ]
    dryRun: bool
    realOrderAllowed: bool


class AdvisorConversationMessage(AdvisorContractModel):
    messageId: Identifier
    role: AdvisorRole
    content: MessageText
    createdAt: datetime
    sourceReferences: Annotated[
        Tuple[Identifier, ...],
        Field(
            default_factory=tuple,
            max_length=MAX_SOURCE_REFERENCES_PER_ITEM,
            strict=False,
        ),
    ]
    safetyClassification: Optional[ShortText] = None

    @field_validator("messageId", "safetyClassification")
    @classmethod
    def validate_safe_text(cls, value: Optional[str]) -> Optional[str]:
        return _reject_control_characters(value) if value is not None else None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)

    @field_validator("createdAt")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("createdAt", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")


class AdvisorContextEnvelope(AdvisorContractModel):
    schemaVersion: Literal["1.0"]
    capturedAt: datetime
    sources: Annotated[
        Tuple[AdvisorSourceReference, ...],
        Field(max_length=MAX_SOURCES, strict=False),
    ]
    runtimeContext: Optional[AdvisorRuntimeContext] = None
    conversationHistory: Annotated[
        Tuple[AdvisorConversationMessage, ...],
        Field(
            default_factory=tuple,
            max_length=MAX_CONVERSATION_MESSAGES,
            strict=False,
        ),
    ]
    warnings: Annotated[
        Tuple[AdvisorWarningCode, ...],
        Field(default_factory=tuple, max_length=MAX_WARNINGS, strict=False),
    ]
    sensitivity: Literal[
        SensitiveClassification.PUBLIC,
        SensitiveClassification.INTERNAL,
    ] = SensitiveClassification.INTERNAL

    @field_validator("capturedAt")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("capturedAt", when_used="json")
    def serialize_captured_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_context(self) -> "AdvisorContextEnvelope":
        source_ids = [source.sourceId for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("source IDs must be unique")
        message_ids = [message.messageId for message in self.conversationHistory]
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("message IDs must be unique")
        timestamps = [message.createdAt for message in self.conversationHistory]
        if timestamps != sorted(timestamps):
            raise ValueError("conversation history must be chronological")
        if any(timestamp > self.capturedAt for timestamp in timestamps):
            raise ValueError("conversation message cannot be newer than context")
        if sum(len(message.content) for message in self.conversationHistory) > (
            MAX_CONVERSATION_CHARACTERS
        ):
            raise ValueError("conversation history exceeds total character limit")
        known_sources = set(source_ids)
        for message in self.conversationHistory:
            if len(set(message.sourceReferences)) != len(message.sourceReferences):
                raise ValueError("message source references must be unique")
            if not set(message.sourceReferences) <= known_sources:
                raise ValueError("conversation message has unknown source reference")
        if (
            self.runtimeContext is not None
            and self.runtimeContext.sourceId not in known_sources
        ):
            raise ValueError("runtimeContext has unknown source reference")
        return self


class AdvisorResponsePreferences(AdvisorContractModel):
    locale: Literal["ja-JP", "en-US"]
    detailLevel: AdvisorDetailLevel
    includeSources: bool
    includeWarnings: bool
    format: AdvisorResponseFormat


class AdvisorRequest(AdvisorContractModel):
    schemaVersion: Literal["1.0"]
    requestId: Identifier
    conversationId: Optional[Identifier] = None
    messageId: Optional[Identifier] = None
    message: MessageText
    requestType: AdvisorRequestType = AdvisorRequestType.EXPLAIN
    locale: Literal["ja-JP", "en-US"]
    requestedAt: datetime
    permissionContext: AdvisorPermissionContext
    contextEnvelope: AdvisorContextEnvelope
    responsePreferences: Optional[AdvisorResponsePreferences] = None

    @field_validator("requestId", "conversationId", "messageId")
    @classmethod
    def validate_identifier(cls, value: Optional[str]) -> Optional[str]:
        return _reject_control_characters(value) if value is not None else None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)

    @field_validator("requestedAt")
    @classmethod
    def normalize_requested_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("requestedAt", when_used="json")
    def serialize_requested_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_request(self) -> "AdvisorRequest":
        if self.contextEnvelope.capturedAt > self.requestedAt:
            raise ValueError("context cannot be captured after requestedAt")
        return self


class AdvisorClientRequest(AdvisorContractModel):
    """Untrusted client fields; permissionContext is intentionally absent."""

    schemaVersion: Literal["1.0"]
    requestId: Identifier
    conversationId: Optional[Identifier] = None
    messageId: Optional[Identifier] = None
    message: MessageText
    requestType: AdvisorRequestType = AdvisorRequestType.EXPLAIN
    locale: Literal["ja-JP", "en-US"]
    requestedAt: datetime
    contextEnvelope: AdvisorContextEnvelope
    responsePreferences: Optional[AdvisorResponsePreferences] = None

    @field_validator("requestId", "conversationId", "messageId")
    @classmethod
    def validate_identifier(cls, value: Optional[str]) -> Optional[str]:
        return _reject_control_characters(value) if value is not None else None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)

    @field_validator("requestedAt")
    @classmethod
    def normalize_requested_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("requestedAt", when_used="json")
    def serialize_requested_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_request(self) -> "AdvisorClientRequest":
        if self.contextEnvelope.capturedAt > self.requestedAt:
            raise ValueError("context cannot be captured after requestedAt")
        return self


class AdvisorEvidence(AdvisorContractModel):
    evidenceId: Identifier
    sourceId: Identifier
    description: BodyText

    @field_validator("evidenceId", "sourceId")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _reject_control_characters(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)


class AdvisorClaim(AdvisorContractModel):
    claimId: Identifier
    claimType: AdvisorClaimType
    text: BodyText
    confidence: Optional[
        Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    ] = None
    sourceIds: Annotated[
        List[Identifier],
        Field(default_factory=list, max_length=MAX_SOURCE_REFERENCES_PER_ITEM),
    ]
    evidenceIds: Annotated[
        List[Identifier],
        Field(default_factory=list, max_length=MAX_SOURCE_REFERENCES_PER_ITEM),
    ]
    freshnessState: AdvisorFreshnessState

    @field_validator("claimId")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _reject_control_characters(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)

    @field_serializer("confidence", when_used="json")
    def serialize_confidence(self, value: Optional[Decimal]) -> Optional[str]:
        return format(value, "f") if value is not None else None

    @model_validator(mode="after")
    def validate_claim(self) -> "AdvisorClaim":
        if self.claimType is AdvisorClaimType.FACT and not self.sourceIds:
            raise ValueError("FACT requires at least one source")
        if (
            self.claimType
            in {AdvisorClaimType.INTERPRETATION, AdvisorClaimType.INFERENCE}
            and not self.sourceIds
        ):
            raise ValueError("interpretation and inference require sources")
        if self.claimType is AdvisorClaimType.INFERENCE and self.confidence is None:
            raise ValueError("INFERENCE requires explicit confidence")
        if (
            self.claimType is not AdvisorClaimType.INFERENCE
            and self.confidence is not None
        ):
            raise ValueError("confidence is only allowed for INFERENCE")
        return self


class AdvisorResponseSection(AdvisorContractModel):
    sectionType: AdvisorSectionType
    title: ShortText
    body: BodyText
    claimIds: Annotated[
        List[Identifier],
        Field(default_factory=list, max_length=MAX_CLAIMS),
    ]
    sourceIds: Annotated[
        List[Identifier],
        Field(default_factory=list, max_length=MAX_SOURCE_REFERENCES_PER_ITEM),
    ]

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _reject_control_characters(value)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)


class AdvisorRefusal(AdvisorContractModel):
    code: AdvisorRefusalCode
    message: SummaryText
    policyRule: VersionText
    safeAlternative: Optional[SummaryText] = None
    retryable: bool

    @field_validator("message", "safeAlternative")
    @classmethod
    def validate_safe_response_text(cls, value: Optional[str]) -> Optional[str]:
        return (
            _reject_control_characters(value, multiline=True)
            if value is not None
            else None
        )

    @field_validator("safeAlternative")
    @classmethod
    def reject_mutating_alternative(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = " ".join(value.casefold().split())
        prohibited = (
            "start the bot",
            "stop the bot",
            "send the order",
            "cancel the order",
            "unlock emergency",
            "unlock governance",
            "bypass governance",
            "toggle auto trade",
            "run this command",
            "call the api",
            "deploy the",
        )
        if any(fragment in normalized for fragment in prohibited):
            raise ValueError("safeAlternative cannot direct a mutation")
        return value


class AdvisorValidationIssue(AdvisorContractModel):
    path: Annotated[List[ShortText], Field(min_length=1, max_length=16)]
    code: VersionText
    message: ShortText


class AdvisorValidationErrorDetail(AdvisorErrorDetail):
    issues: Annotated[
        List[AdvisorValidationIssue],
        Field(min_length=1, max_length=32),
    ]


class AdvisorValidationErrorResponse(AdvisorContractModel):
    error: AdvisorValidationErrorDetail


class AdvisorSensitiveDataFilterResult(AdvisorContractModel):
    status: SensitiveFilterStatus
    removedCategoryCodes: Annotated[
        List[SensitiveCategory],
        Field(default_factory=list, max_length=16),
    ]
    contentModified: bool
    blocked: bool
    inputClassification: SensitiveClassification = SensitiveClassification.INTERNAL
    outputClassification: SensitiveClassification = SensitiveClassification.INTERNAL
    reason: Optional[ShortText] = None

    @model_validator(mode="after")
    def validate_result(self) -> "AdvisorSensitiveDataFilterResult":
        if self.status is SensitiveFilterStatus.CLEAN:
            if self.removedCategoryCodes or self.contentModified or self.blocked:
                raise ValueError("CLEAN filter result cannot report modifications")
        elif not self.removedCategoryCodes:
            raise ValueError("modified or blocked result requires category codes")
        if self.status is SensitiveFilterStatus.MODIFIED:
            if not self.contentModified or self.blocked:
                raise ValueError("MODIFIED requires contentModified only")
        if self.status is SensitiveFilterStatus.BLOCKED and not self.blocked:
            raise ValueError("BLOCKED requires blocked=true")
        if (
            self.inputClassification is SensitiveClassification.SECRET
            and not self.blocked
        ):
            raise ValueError("SECRET input must be blocked")
        if self.outputClassification in {
            SensitiveClassification.CONFIDENTIAL,
            SensitiveClassification.SECRET,
            SensitiveClassification.UNKNOWN,
        }:
            raise ValueError("output classification exceeds Advisor allowance")
        return self


class AdvisorAuthorityNotice(AdvisorContractModel):
    authoritative: Literal[False] = False
    executionAuthority: Literal[False] = False
    governanceAuthority: Literal[False] = False
    moneyManagementAuthority: Literal[False] = False
    strategyAuthority: Literal[False] = False


class AdvisorResponse(AdvisorContractModel):
    schemaVersion: Literal["1.0"]
    requestId: Identifier
    responseId: Identifier
    conversationId: Optional[Identifier] = None
    status: AdvisorResponseStatus
    category: AdvisorResponseCategory
    summary: SummaryText
    sections: Annotated[
        List[AdvisorResponseSection],
        Field(default_factory=list, max_length=MAX_RESPONSE_SECTIONS),
    ]
    claims: Annotated[
        List[AdvisorClaim],
        Field(default_factory=list, max_length=MAX_CLAIMS),
    ]
    evidence: Annotated[
        List[AdvisorEvidence],
        Field(default_factory=list, max_length=MAX_EVIDENCE),
    ]
    sourceReferences: Annotated[
        List[AdvisorSourceReference],
        Field(default_factory=list, max_length=MAX_SOURCES),
    ]
    warnings: Annotated[
        List[AdvisorWarningCode],
        Field(default_factory=list, max_length=MAX_WARNINGS),
    ]
    refusal: Optional[AdvisorRefusal] = None
    error: Optional[AdvisorErrorDetail] = None
    sensitiveDataFilter: AdvisorSensitiveDataFilterResult
    createdAt: datetime
    policyVersion: VersionText
    authorityNotice: AdvisorAuthorityNotice = Field(
        default_factory=AdvisorAuthorityNotice
    )
    sensitivity: Literal[
        SensitiveClassification.PUBLIC,
        SensitiveClassification.INTERNAL,
    ] = SensitiveClassification.INTERNAL

    @field_validator("requestId", "responseId", "conversationId", "policyVersion")
    @classmethod
    def validate_identifier(cls, value: Optional[str]) -> Optional[str]:
        return _reject_control_characters(value) if value is not None else None

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _reject_control_characters(value, multiline=True)

    @field_validator("createdAt")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @field_serializer("createdAt", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_response(self) -> "AdvisorResponse":
        if self.status is AdvisorResponseStatus.REFUSED:
            if self.refusal is None or self.error is not None:
                raise ValueError("REFUSED requires refusal and forbids error")
        elif self.refusal is not None:
            raise ValueError("refusal is only valid for REFUSED status")
        if self.status is AdvisorResponseStatus.ERROR:
            if self.error is None:
                raise ValueError("ERROR requires error")
        elif self.error is not None:
            raise ValueError("error is only valid for ERROR status")
        if self.sensitiveDataFilter.blocked and self.status not in {
            AdvisorResponseStatus.REFUSED,
            AdvisorResponseStatus.ERROR,
        }:
            raise ValueError("blocked sensitive input forbids normal response")
        source_ids = [source.sourceId for source in self.sourceReferences]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("response source IDs must be unique")
        claim_ids = [claim.claimId for claim in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim IDs must be unique")
        evidence_ids = [item.evidenceId for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence IDs must be unique")
        known_sources = set(source_ids)
        source_freshness = {
            source.sourceId: source.freshness.state for source in self.sourceReferences
        }
        known_claims = set(claim_ids)
        known_evidence = set(evidence_ids)
        for claim in self.claims:
            if len(set(claim.sourceIds)) != len(claim.sourceIds):
                raise ValueError("claim source references must be unique")
            if len(set(claim.evidenceIds)) != len(claim.evidenceIds):
                raise ValueError("claim evidence references must be unique")
            if not set(claim.sourceIds) <= known_sources:
                raise ValueError("claim has unknown source reference")
            if not set(claim.evidenceIds) <= known_evidence:
                raise ValueError("claim has unknown evidence reference")
            if claim.claimType is AdvisorClaimType.FACT:
                if claim.freshnessState is AdvisorFreshnessState.UNKNOWN:
                    raise ValueError("FACT cannot claim UNKNOWN freshness")
                if any(
                    source_freshness[source_id] is not claim.freshnessState
                    for source_id in claim.sourceIds
                ):
                    raise ValueError("FACT freshness must match its sources")
        for item in self.evidence:
            if item.sourceId not in known_sources:
                raise ValueError("evidence has unknown source reference")
        for section in self.sections:
            if not set(section.claimIds) <= known_claims:
                raise ValueError("section has unknown claim reference")
            if not set(section.sourceIds) <= known_sources:
                raise ValueError("section has unknown source reference")
        if (
            any(
                source.freshness.state is AdvisorFreshnessState.LAST_GOOD
                for source in self.sourceReferences
            )
            and AdvisorWarningCode.LAST_GOOD_SOURCE not in self.warnings
        ):
            raise ValueError("LAST_GOOD source requires warning")
        character_count = (
            len(self.summary)
            + sum(len(section.title) + len(section.body) for section in self.sections)
            + sum(len(claim.text) for claim in self.claims)
            + sum(len(item.description) for item in self.evidence)
            + (len(self.refusal.message) if self.refusal else 0)
            + (len(self.refusal.safeAlternative or "") if self.refusal else 0)
        )
        if character_count > MAX_RESPONSE_CHARACTERS:
            raise ValueError("response exceeds total character limit")
        return self
