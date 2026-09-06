"""Pure construction of sanitized, read-only AI Advisor context envelopes."""

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Tuple

from pydantic import ConfigDict, Field

from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorContextEnvelope,
    AdvisorContractModel,
    AdvisorConversationMessage,
    AdvisorDataAccessScope,
    AdvisorFreshnessMetadata,
    AdvisorFreshnessState,
    AdvisorKnowledgeExcerpt,
    AdvisorMarketRuntimeContext,
    AdvisorMoneyManagementRuntimeContext,
    AdvisorPermissionContext,
    AdvisorRuntimeContext,
    AdvisorSourceAuthority,
    AdvisorSourceReference,
    AdvisorSourceType,
    AdvisorWarningCode,
    SensitiveClassification,
)
from backend.ai_advisor.models import AdvisorRuntimeResponse, Freshness

DEFAULT_RUNTIME_FRESHNESS_SECONDS = 10
MAX_BUILDER_SOURCES = 32

_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_ -]?key|api[_ -]?secret|kucoin[_ -]?key|"
        r"kucoin[_ -]?secret|kucoin[_ -]?passphrase|password|passphrase|"
        r"authorization|cookie|refresh[_ -]?token|token|secret|"
        r"private[_ -]?key|database[_ -]?(?:credential|url))\b"
        r"\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
        r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s]+"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@[^\s]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)
_ABSOLUTE_PATH = re.compile(r"(?<![\w.])/(?:home|root|etc|var|opt|srv|tmp)/[^\s]*")
_PROMPT_INJECTION = re.compile(
    r"(?i)\b(ignore\s+(?:all\s+|the\s+)?(?:previous|prior|system)"
    r"\s+(?:instructions|rules)|you\s+are\s+now\s+the\s+system|"
    r"reveal\s+(?:the\s+)?system\s+prompt|print\s+hidden\s+instructions|"
    r"disable\s+safety|elevate\s+permissions?|act\s+as\s+administrator|"
    r"override\s+governance|enable\s+live\s+trading|"
    r"(?:send|execute)\s+(?:an\s+|this\s+|the\s+)?order|"
    r"unlock\s+governance|(?:show|send)\s+(?:this\s+|the\s+)?secret|"
    r"call\s+(?:a\s+)?tool|use\s+openai\s+api|"
    r"(?:read|open)\s+(?:the\s+)?(?:local\s+)?files?)\b"
)


class BuilderInputModel(AdvisorContractModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SpecificationSourceInput(BuilderInputModel):
    sourceId: Annotated[str, Field(min_length=1, max_length=128)]
    sourceVersion: Annotated[str, Field(min_length=1, max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    documentPath: Annotated[str, Field(min_length=1, max_length=256)]
    loadedAt: datetime
    contentHash: Optional[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]] = (
        None
    )
    approved: Literal[True] = True
    authorityLevel: Literal[
        "CONSTITUTION", "ADR", "MASTER_SPEC", "FEATURE_SPEC"
    ] = "FEATURE_SPEC"
    topics: Annotated[
        Tuple[str, ...],
        Field(default_factory=tuple, max_length=12, strict=False),
    ]
    excerpt: Optional[Annotated[str, Field(min_length=1, max_length=8_000)]] = None


class SummarySourceInput(BuilderInputModel):
    sourceId: Annotated[str, Field(min_length=1, max_length=128)]
    sourceType: Literal[
        AdvisorSourceType.MARKET_INTELLIGENCE,
        AdvisorSourceType.MONEY_MANAGEMENT,
    ]
    sourceVersion: Annotated[str, Field(min_length=1, max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    capturedAt: datetime
    sourceUpdatedAt: Optional[datetime]
    freshnessState: AdvisorFreshnessState
    ageSeconds: Optional[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    validUntil: Optional[datetime] = None
    reason: Optional[Annotated[str, Field(min_length=1, max_length=256)]] = None
    approved: Literal[True] = True
    sanitized: Literal[True] = True


class SanitizedText(BuilderInputModel):
    value: Annotated[str, Field(min_length=1, max_length=8000)]
    changed: bool
    sensitiveRemoved: bool
    injectionRemoved: bool
    pathRemoved: bool


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, name: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be valid ISO-8601") from exc
    return _utc(parsed, name)


def sanitize_text(value: str) -> SanitizedText:
    """Redact only known unsafe material; never retain removed values."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("text must be a non-empty string")
    if "\x00" in value:
        raise ValueError("NUL is not allowed")
    sanitized = value
    sensitive_count = 0
    for pattern in _SENSITIVE_PATTERNS:
        sanitized, count = pattern.subn("[REMOVED:SENSITIVE]", sanitized)
        sensitive_count += count
    sanitized, path_count = _ABSOLUTE_PATH.subn("[REMOVED:PATH]", sanitized)
    sanitized, injection_count = _PROMPT_INJECTION.subn(
        "[REMOVED:PROMPT_INJECTION]", sanitized
    )
    return SanitizedText(
        value=sanitized,
        changed=bool(sensitive_count or path_count or injection_count),
        sensitiveRemoved=bool(sensitive_count),
        injectionRemoved=bool(injection_count),
        pathRemoved=bool(path_count),
    )


def build_freshness(
    *,
    state: AdvisorFreshnessState,
    captured_at: datetime,
    source_updated_at: Optional[datetime],
    age_seconds: Optional[float],
    valid_until: Optional[datetime] = None,
    reason: Optional[str] = None,
    last_good_at: Optional[datetime] = None,
    current_read_failed_at: Optional[datetime] = None,
    failure_reason: Optional[str] = None,
    stale_warning: Optional[str] = None,
) -> AdvisorFreshnessMetadata:
    captured = _utc(captured_at, "captured_at")
    updated = (
        _utc(source_updated_at, "source_updated_at")
        if source_updated_at is not None
        else None
    )
    return AdvisorFreshnessMetadata(
        state=state,
        capturedAt=captured,
        sourceUpdatedAt=updated,
        ageSeconds=age_seconds,
        isLastGood=state is AdvisorFreshnessState.LAST_GOOD,
        validUntil=(
            _utc(valid_until, "valid_until") if valid_until is not None else None
        ),
        reason=reason,
        lastGoodAt=(
            _utc(last_good_at, "last_good_at") if last_good_at is not None else None
        ),
        currentReadFailedAt=(
            _utc(current_read_failed_at, "current_read_failed_at")
            if current_read_failed_at is not None
            else None
        ),
        failureReason=failure_reason,
        staleWarning=stale_warning,
    )


def build_source_reference(
    *,
    source_id: str,
    source_type: AdvisorSourceType,
    source_version: str,
    captured_at: datetime,
    freshness: AdvisorFreshnessMetadata,
    authority: AdvisorSourceAuthority,
    display_label: str,
    content_hash: Optional[str] = None,
    document_path: Optional[str] = None,
    approved: bool = True,
) -> AdvisorSourceReference:
    label = sanitize_text(display_label)
    if label.changed:
        raise ValueError("source display label contains unsafe content")
    return AdvisorSourceReference(
        sourceId=source_id,
        sourceType=source_type,
        sourceVersion=source_version,
        capturedAt=_utc(captured_at, "captured_at"),
        freshness=freshness,
        authority=authority,
        contentHash=content_hash,
        displayLabel=label.value,
        documentPath=document_path,
        approved=approved,
        sanitized=True,
        sensitivity=SensitiveClassification.INTERNAL,
    )


def build_runtime_context(
    runtime: AdvisorRuntimeResponse,
    *,
    source_id: str,
    generated_at: datetime,
    source_version: str = "1.0",
    freshness_window_seconds: int = DEFAULT_RUNTIME_FRESHNESS_SECONDS,
) -> Tuple[
    AdvisorRuntimeContext, AdvisorSourceReference, Tuple[AdvisorWarningCode, ...]
]:
    if not isinstance(runtime, AdvisorRuntimeResponse):
        raise TypeError("typed AdvisorRuntimeResponse required")
    generated = _utc(generated_at, "generated_at")
    captured = _parse_utc(runtime.runtime.capturedAt, "runtime.capturedAt")
    if captured > generated:
        raise ValueError("runtime snapshot cannot be captured in the future")
    source_updated = (
        _parse_utc(runtime.runtime.sourceUpdatedAt, "runtime.sourceUpdatedAt")
        if runtime.runtime.sourceUpdatedAt is not None
        else None
    )
    mapped_state = {
        Freshness.FRESH: AdvisorFreshnessState.FRESH,
        Freshness.STALE: AdvisorFreshnessState.STALE,
        Freshness.UNKNOWN: AdvisorFreshnessState.UNKNOWN,
    }[runtime.runtime.freshness]
    if source_updated is None:
        mapped_state = AdvisorFreshnessState.UNKNOWN
    age = (
        (captured - source_updated).total_seconds()
        if source_updated is not None and source_updated <= captured
        else None
    )
    valid_until = (
        captured + timedelta(seconds=freshness_window_seconds)
        if mapped_state is AdvisorFreshnessState.FRESH
        else None
    )
    freshness = build_freshness(
        state=mapped_state,
        captured_at=captured,
        source_updated_at=source_updated,
        age_seconds=age,
        valid_until=valid_until,
        reason=(
            "RUNTIME_FRESHNESS_UNKNOWN"
            if mapped_state is AdvisorFreshnessState.UNKNOWN
            else None
        ),
    )
    exchange = (
        sanitize_text(runtime.bot.exchange).value if runtime.bot.exchange else None
    )
    symbol = sanitize_text(runtime.bot.symbol).value if runtime.bot.symbol else None
    runtime_position = getattr(runtime.operation, "positionState", None)
    runtime_pending = getattr(runtime.operation, "pendingOrderState", None)
    money_management = None
    if runtime.moneyManagement is not None:
        mm = runtime.moneyManagement
        money_management = AdvisorMoneyManagementRuntimeContext(
            regime=mm.regime,
            equity=mm.equity,
            availableCapital=mm.availableCapital,
            exposure=mm.exposure,
            remainingExposure=mm.remainingExposure,
            positionCapacity=mm.positionCapacity,
            remainingPositionCapacity=mm.remainingPositionCapacity,
            riskBudget=mm.riskBudget,
            drawdownPercent=mm.drawdownPercent,
            ruinGuardStatus=mm.ruinGuardStatus,
            compoundingEnabled=mm.compoundingEnabled,
            authorityFresh=mm.authorityFresh,
            capturedAt=mm.capturedAt,
        )
    market = None
    if runtime.market is not None:
        mk = runtime.market
        market = AdvisorMarketRuntimeContext(
            ready=mk.ready,
            stale=mk.stale,
            symbol=sanitize_text(mk.symbol).value if mk.symbol else None,
        )
    context = AdvisorRuntimeContext(
        schemaVersion="1.0",
        sourceId=source_id,
        state=runtime.bot.state,
        mode=runtime.bot.mode,
        exchange=exchange,
        symbol=symbol,
        loopEnabled=runtime.operation.loopEnabled,
        loopState=runtime.operation.loopState,
        autoTradeEnabled=runtime.operation.autoTradeEnabled,
        emergencyLocked=runtime.safety.emergencyLocked,
        emergencyState=runtime.safety.emergencyState,
        dryRun=runtime.safety.dryRun,
        realOrderAllowed=runtime.safety.realOrderAllowed,
        positionState=(
            runtime_position
            if runtime_position in {"FLAT", "OPEN", "UNKNOWN"}
            else None
        ),
        pendingOrderState=(
            runtime_pending
            if runtime_pending in {"NONE", "OPEN", "UNKNOWN"}
            else None
        ),
        moneyManagement=money_management,
        market=market,
    )
    source = build_source_reference(
        source_id=source_id,
        source_type=AdvisorSourceType.RUNTIME,
        source_version=source_version,
        captured_at=captured,
        freshness=freshness,
        authority=AdvisorSourceAuthority.RUNTIME_AUTHORITATIVE,
        display_label="Sanitized AI Advisor Runtime",
    )
    warnings = []
    if runtime.warnings:
        warnings.append(AdvisorWarningCode.SOURCE_OMITTED)
    if mapped_state is AdvisorFreshnessState.STALE:
        warnings.append(AdvisorWarningCode.STALE_SOURCE)
    if mapped_state is AdvisorFreshnessState.UNKNOWN:
        warnings.append(AdvisorWarningCode.SOURCE_OMITTED)
    return context, source, tuple(dict.fromkeys(warnings))


def build_specification_source(
    value: SpecificationSourceInput,
) -> AdvisorSourceReference:
    loaded_at = _utc(value.loadedAt, "loadedAt")
    freshness = build_freshness(
        state=AdvisorFreshnessState.NOT_APPLICABLE,
        captured_at=loaded_at,
        source_updated_at=None,
        age_seconds=None,
        reason="VERSIONED_SPECIFICATION",
    )
    return build_source_reference(
        source_id=value.sourceId,
        source_type=AdvisorSourceType.SPECIFICATION,
        source_version=value.sourceVersion,
        captured_at=loaded_at,
        freshness=freshness,
        authority=AdvisorSourceAuthority.SPECIFICATION_AUTHORITATIVE,
        display_label=value.title,
        content_hash=value.contentHash,
        document_path=value.documentPath,
        approved=value.approved,
    )


def build_summary_source(value: SummarySourceInput) -> AdvisorSourceReference:
    freshness = build_freshness(
        state=value.freshnessState,
        captured_at=value.capturedAt,
        source_updated_at=value.sourceUpdatedAt,
        age_seconds=value.ageSeconds,
        valid_until=value.validUntil,
        reason=value.reason,
    )
    return build_source_reference(
        source_id=value.sourceId,
        source_type=value.sourceType,
        source_version=value.sourceVersion,
        captured_at=value.capturedAt,
        freshness=freshness,
        authority=AdvisorSourceAuthority.APPROVED_DERIVED,
        display_label=value.title,
        approved=value.approved,
    )


def build_conversation_context(
    *,
    history: Tuple[AdvisorConversationMessage, ...],
    current_message: Optional[AdvisorConversationMessage],
) -> Tuple[Tuple[AdvisorConversationMessage, ...], Tuple[AdvisorWarningCode, ...]]:
    messages = history + ((current_message,) if current_message is not None else ())
    sanitized_messages = []
    changed = False
    for message in messages:
        cleaned = sanitize_text(message.content)
        changed = changed or cleaned.changed
        sanitized_messages.append(
            message.model_copy(update={"content": cleaned.value}, deep=True)
        )
    sanitized_messages.sort(key=lambda item: (item.createdAt, item.messageId))
    warning = (AdvisorWarningCode.SENSITIVE_CONTENT_REMOVED,) if changed else ()
    return tuple(sanitized_messages), warning


def build_advisor_context(
    *,
    generated_at: datetime,
    permission_context: AdvisorPermissionContext,
    runtime: Optional[AdvisorRuntimeResponse] = None,
    runtime_source_id: str = "advisor-runtime",
    specifications: Tuple[SpecificationSourceInput, ...] = (),
    market_intelligence_sources: Tuple[SummarySourceInput, ...] = (),
    money_management_sources: Tuple[SummarySourceInput, ...] = (),
    conversation_history: Tuple[AdvisorConversationMessage, ...] = (),
    current_message: Optional[AdvisorConversationMessage] = None,
) -> AdvisorContextEnvelope:
    """Build one validated envelope without accessing any external system."""

    captured = _utc(generated_at, "generated_at")
    if not permission_context.conversationAllowed:
        raise ValueError("trusted authenticated and authorized context required")
    sources = []
    warnings = []
    runtime_context = None
    scopes = set(permission_context.dataAccessScope)
    capabilities = set(permission_context.allowedCapabilities)
    if runtime is not None:
        if (
            AdvisorDataAccessScope.SANITIZED_RUNTIME_SUMMARY not in scopes
            or AdvisorCapability.RUNTIME_STATUS_EXPLAIN not in capabilities
        ):
            raise ValueError("runtime context is outside permission scope")
        runtime_context, runtime_source, runtime_warnings = build_runtime_context(
            runtime,
            source_id=runtime_source_id,
            generated_at=captured,
        )
        sources.append(runtime_source)
        warnings.extend(runtime_warnings)
    if specifications:
        if AdvisorDataAccessScope.APPROVED_LOCAL_SPECIFICATIONS not in scopes:
            raise ValueError("specifications are outside permission scope")
        sources.extend(build_specification_source(item) for item in specifications)
    knowledge_excerpts = []
    for item in specifications:
        if item.excerpt is None:
            continue
        cleaned = sanitize_text(item.excerpt)
        if cleaned.changed:
            raise ValueError("knowledge excerpt contains unsafe content")
        if not item.topics:
            raise ValueError("knowledge excerpt requires topics")
        knowledge_excerpts.append(
            AdvisorKnowledgeExcerpt(
                sourceId=item.sourceId,
                authorityLevel=item.authorityLevel,
                topics=item.topics,
                content=cleaned.value,
            )
        )
    if market_intelligence_sources:
        if AdvisorDataAccessScope.SANITIZED_MARKET_INTELLIGENCE_SUMMARY not in scopes:
            raise ValueError("Market Intelligence is outside permission scope")
        if any(
            item.sourceType is not AdvisorSourceType.MARKET_INTELLIGENCE
            for item in market_intelligence_sources
        ):
            raise ValueError("invalid Market Intelligence source type")
        sources.extend(
            build_summary_source(item) for item in market_intelligence_sources
        )
    if money_management_sources:
        if AdvisorDataAccessScope.SANITIZED_MONEY_MANAGEMENT_SUMMARY not in scopes:
            raise ValueError("Money Management is outside permission scope")
        if any(
            item.sourceType is not AdvisorSourceType.MONEY_MANAGEMENT
            for item in money_management_sources
        ):
            raise ValueError("invalid Money Management source type")
        sources.extend(build_summary_source(item) for item in money_management_sources)
    conversation, conversation_warnings = build_conversation_context(
        history=conversation_history,
        current_message=current_message,
    )
    warnings.extend(conversation_warnings)
    sources.sort(key=lambda item: item.sourceId)
    return AdvisorContextEnvelope(
        schemaVersion="1.0",
        capturedAt=captured,
        sources=sources,
        runtimeContext=runtime_context,
        knowledgeExcerpts=tuple(
            sorted(knowledge_excerpts, key=lambda item: item.sourceId)
        ),
        conversationHistory=list(conversation),
        warnings=sorted(set(warnings), key=lambda item: item.value),
        sensitivity=SensitiveClassification.INTERNAL,
    )
