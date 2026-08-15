"""Pure, deterministic assembly and rendering of AI Advisor prompts."""

import re
from typing import Iterable, Tuple

from pydantic import ValidationError

from backend.ai_advisor.context_builder import sanitize_text
from backend.ai_advisor.conversation_models import (
    AdvisorContextEnvelope,
    AdvisorFreshnessState,
    AdvisorRequest,
    AdvisorRole,
    AdvisorSourceAuthority,
    AdvisorSourceReference,
    AdvisorSourceType,
    SensitiveClassification,
)
from backend.ai_advisor.prompt_models import (
    MAX_PROMPT_SECTIONS,
    MAX_RENDERED_PROMPT_CHARACTERS,
    PROMPT_VERSION,
    PERMISSION_INSTRUCTION,
    RESPONSE_INSTRUCTION,
    ROLE_INSTRUCTION,
    SOURCE_INSTRUCTION,
    SYSTEM_INSTRUCTION,
    AdvisorPromptEnvelope,
    AdvisorPromptPolicy,
    AdvisorPromptSection,
    AdvisorPromptSectionType,
    build_response_instruction,
)

_SECTION_ORDER = (
    AdvisorPromptSectionType.SAFETY,
    AdvisorPromptSectionType.ROLE,
    AdvisorPromptSectionType.PERMISSION,
    AdvisorPromptSectionType.RESPONSE,
    AdvisorPromptSectionType.SOURCE_POLICY,
    AdvisorPromptSectionType.RUNTIME_CONTEXT,
    AdvisorPromptSectionType.SPECIFICATION_REFERENCE,
    AdvisorPromptSectionType.CONVERSATION_CONTEXT,
    AdvisorPromptSectionType.CURRENT_REQUEST,
)
_UNSAFE_PATH = re.compile(
    r"(?ix)"
    r"(?:\bfile://)"
    r"|(?:(?:^|[\s\"'(])/(?:[^/\s]+/)+[^/\s]*)"
    r"|(?:[a-z]:[\\/])"
    r"|(?:\\\\[^\\\s]+\\[^\\\s]+)"
    r"|(?:^|[\\/])\.\.(?:[\\/]|$)"
    r"|(?:%2e%2e(?:%2f|%5c|/|\\|$))"
)


def _escape_data_delimiters(value: str) -> str:
    """Idempotently prevent ASCII bracketed data from becoming a delimiter."""

    return value.replace("[", "&#91;").replace("]", "&#93;")


def _safe_data(value: str) -> str:
    if _UNSAFE_PATH.search(value):
        raise ValueError("prompt data failed path validation")
    checked = sanitize_text(value)
    if checked.sensitiveRemoved or checked.pathRemoved:
        raise ValueError("prompt data failed sensitive-content validation")
    return _escape_data_delimiters(checked.value)


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    rendered = getattr(value, "value", str(value))
    return _safe_data(rendered)


def _lines(values: Iterable[Tuple[str, object]]) -> str:
    return "\n".join(f"{name}={_scalar(value)}" for name, value in values)


def _section(
    section_type: AdvisorPromptSectionType,
    title: str,
    content: str,
    *,
    authority: AdvisorSourceAuthority = AdvisorSourceAuthority.UNKNOWN,
    source_ids: Tuple[str, ...] = (),
    freshness: AdvisorFreshnessState = AdvisorFreshnessState.NOT_APPLICABLE,
) -> AdvisorPromptSection:
    return AdvisorPromptSection(
        sectionId=section_type.value.lower(),
        sectionType=section_type,
        title=title,
        content=content,
        authority=authority,
        sourceIds=tuple(_safe_data(source_id) for source_id in source_ids),
        freshness=freshness,
        sensitivity=SensitiveClassification.INTERNAL,
    )


def _runtime_section(context: AdvisorContextEnvelope) -> AdvisorPromptSection:
    runtime = context.runtimeContext
    if runtime is None:
        return _section(
            AdvisorPromptSectionType.RUNTIME_CONTEXT,
            "Runtime Context",
            "status=NOT_AVAILABLE",
            freshness=AdvisorFreshnessState.UNKNOWN,
        )
    source = next(item for item in context.sources if item.sourceId == runtime.sourceId)
    content = _lines(
        (
            ("botState", runtime.state),
            ("mode", runtime.mode),
            ("exchange", runtime.exchange),
            ("symbol", runtime.symbol),
            ("loopEnabled", runtime.loopEnabled),
            ("loopState", runtime.loopState),
            ("autoTradeEnabled", runtime.autoTradeEnabled),
            ("emergencyLocked", runtime.emergencyLocked),
            ("emergencyState", runtime.emergencyState),
            ("dryRun", runtime.dryRun),
            ("realOrderAllowed", runtime.realOrderAllowed),
            ("freshness", source.freshness.state),
        )
    )
    return _section(
        AdvisorPromptSectionType.RUNTIME_CONTEXT,
        "Runtime Context (trusted typed scalars only)",
        content,
        authority=source.authority,
        source_ids=(source.sourceId,),
        freshness=source.freshness.state,
    )


def _source_line(source: AdvisorSourceReference) -> str:
    values = [
        ("sourceId", source.sourceId),
        ("sourceType", source.sourceType),
        ("title", _safe_data(source.displayLabel)),
        ("logicalPath", source.documentPath),
        ("version", source.sourceVersion),
        ("authority", source.authority),
        ("freshness", source.freshness.state),
        ("contentHash", source.contentHash),
    ]
    return _lines(values)


def _knowledge_line(context: AdvisorContextEnvelope, source_id: str) -> str:
    excerpt = next(
        (item for item in context.knowledgeExcerpts if item.sourceId == source_id),
        None,
    )
    if excerpt is None:
        return "approvedKnowledge=METADATA_ONLY"
    return _lines(
        (
            ("knowledgeKind", excerpt.knowledgeKind),
            ("authorityLevel", excerpt.authorityLevel),
            ("topics", ",".join(excerpt.topics)),
            ("approvedKnowledge", excerpt.content),
        )
    )


def _specification_section(context: AdvisorContextEnvelope) -> AdvisorPromptSection:
    sources = tuple(
        sorted(
            (
                source
                for source in context.sources
                if source.sourceType
                in {
                    AdvisorSourceType.SPECIFICATION,
                    AdvisorSourceType.MARKET_INTELLIGENCE,
                    AdvisorSourceType.MONEY_MANAGEMENT,
                }
                and source.approved is True
                and source.sanitized is True
            ),
            key=lambda item: item.sourceId,
        )
    )
    content = "\n---\n".join(
        _source_line(source) + "\n" + _knowledge_line(context, source.sourceId)
        for source in sources
    )
    return _section(
        AdvisorPromptSectionType.SPECIFICATION_REFERENCE,
        "Approved Static Knowledge (validated excerpts and source metadata)",
        content or "status=NOT_AVAILABLE",
        authority=(
            AdvisorSourceAuthority.SPECIFICATION_AUTHORITATIVE
            if sources
            else AdvisorSourceAuthority.UNKNOWN
        ),
        source_ids=tuple(source.sourceId for source in sources),
    )


def _conversation_section(
    context: AdvisorContextEnvelope,
    current_message_id: str | None,
) -> AdvisorPromptSection:
    messages = tuple(
        sorted(
            (
                message
                for message in context.conversationHistory
                if message.messageId != current_message_id
            ),
            key=lambda item: (item.createdAt, item.messageId),
        )
    )
    if any(
        message.role not in {AdvisorRole.USER, AdvisorRole.ADVISOR}
        for message in messages
    ):
        raise ValueError("conversation contains an unsupported role")
    rendered = []
    for message in messages:
        rendered.append(
            _lines(
                (
                    ("messageId", message.messageId),
                    ("role", message.role),
                    ("createdAt", message.createdAt.isoformat().replace("+00:00", "Z")),
                    ("content", _safe_data(message.content)),
                )
            )
        )
    content = "classification=UNTRUSTED CONVERSATION DATA\n"
    content += "\n---\n".join(rendered) if rendered else "status=NOT_AVAILABLE"
    return _section(
        AdvisorPromptSectionType.CONVERSATION_CONTEXT,
        "Conversation Context (untrusted data)",
        content,
        source_ids=tuple(
            sorted(
                {
                    source_id
                    for message in messages
                    for source_id in message.sourceReferences
                }
            )
        ),
    )


def build_advisor_prompt(
    *,
    request: AdvisorRequest,
    context: AdvisorContextEnvelope,
    policy: AdvisorPromptPolicy,
) -> AdvisorPromptEnvelope:
    """Build a validated prompt envelope without I/O or state mutation."""

    if not isinstance(request, AdvisorRequest):
        raise TypeError("typed AdvisorRequest required")
    if not isinstance(context, AdvisorContextEnvelope):
        raise TypeError("typed AdvisorContextEnvelope required")
    if not isinstance(policy, AdvisorPromptPolicy):
        raise TypeError("typed AdvisorPromptPolicy required")
    try:
        request = AdvisorRequest.model_validate(request.model_dump())
        context = AdvisorContextEnvelope.model_validate(context.model_dump())
        policy = AdvisorPromptPolicy.model_validate(policy.model_dump())
    except ValidationError:
        raise ValueError("prompt input contract validation failed") from None
    if request.contextEnvelope != context:
        raise ValueError("request and context envelope must match")
    if not request.permissionContext.conversationAllowed:
        raise ValueError("trusted authenticated and authorized context required")
    current_request = _safe_data(request.message)
    response_instruction = build_response_instruction(
        request_id=request.requestId,
        prompt_version=PROMPT_VERSION,
    )
    warnings = tuple(sorted({warning.value for warning in context.warnings}))
    sections = (
        _section(
            AdvisorPromptSectionType.SAFETY, "System Safety Policy", SYSTEM_INSTRUCTION
        ),
        _section(AdvisorPromptSectionType.ROLE, "Advisor Role", ROLE_INSTRUCTION),
        _section(
            AdvisorPromptSectionType.PERMISSION,
            "Permission Boundary",
            PERMISSION_INSTRUCTION,
        ),
        _section(
            AdvisorPromptSectionType.RESPONSE,
            "Response Contract",
            response_instruction,
        ),
        _section(
            AdvisorPromptSectionType.SOURCE_POLICY,
            "Source and Freshness Policy",
            SOURCE_INSTRUCTION,
        ),
        _runtime_section(context),
        _specification_section(context),
        _conversation_section(context, request.messageId),
        _section(
            AdvisorPromptSectionType.CURRENT_REQUEST,
            "Current User Request (untrusted question data)",
            "classification=UNTRUSTED CURRENT REQUEST DATA\n"
            f"locale={request.locale}\n"
            f"requestType={request.requestType.value}\n"
            f"content={current_request}",
        ),
    )
    if len(sections) != MAX_PROMPT_SECTIONS:
        raise ValueError("invalid prompt section count")
    if tuple(section.sectionType for section in sections) != _SECTION_ORDER:
        raise ValueError("invalid prompt section order")
    preferences = request.responsePreferences
    envelope = AdvisorPromptEnvelope(
        promptVersion=PROMPT_VERSION,
        requestId=request.requestId,
        assembledAt=request.requestedAt,
        systemInstruction=SYSTEM_INSTRUCTION,
        roleInstruction=ROLE_INSTRUCTION,
        permissionInstruction=PERMISSION_INSTRUCTION,
        responseInstruction=response_instruction,
        sourceInstruction=SOURCE_INSTRUCTION,
        contextSections=sections,
        currentRequest=current_request,
        warnings=warnings,
        locale=request.locale,
        responseDetail=(
            preferences.detailLevel.value if preferences is not None else None
        ),
        responseFormat=preferences.format.value if preferences is not None else None,
    )
    if len(render_advisor_prompt(envelope)) > MAX_RENDERED_PROMPT_CHARACTERS:
        raise ValueError("rendered prompt exceeds character limit")
    return envelope


def render_advisor_prompt(envelope: AdvisorPromptEnvelope) -> str:
    """Render an already validated envelope with stable delimiters and newlines."""

    if not isinstance(envelope, AdvisorPromptEnvelope):
        raise TypeError("typed AdvisorPromptEnvelope required")
    try:
        envelope = AdvisorPromptEnvelope.model_validate(envelope.model_dump())
    except ValidationError:
        raise ValueError("prompt envelope contract validation failed") from None
    blocks = []
    for section in envelope.contextSections:
        name = section.sectionType.value
        blocks.append(
            f"[BEGIN_{name}]\n"
            f"title={section.title}\n"
            f"authority={section.authority.value}\n"
            f"freshness={section.freshness.value}\n"
            f"sourceIds={','.join(section.sourceIds) or 'none'}\n"
            f"{section.content}\n"
            f"[END_{name}]"
        )
    rendered = "\n\n".join(blocks) + "\n"
    if len(rendered) > MAX_RENDERED_PROMPT_CHARACTERS:
        raise ValueError("rendered prompt exceeds character limit")
    return rendered
