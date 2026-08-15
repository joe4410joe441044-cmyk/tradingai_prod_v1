"""Pure validation of parsed AI Advisor responses against trusted context."""

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import unquote

from pydantic import ValidationError

from backend.ai_advisor.context_builder import sanitize_text
from backend.ai_advisor.actionable_unknown import project_actionable_unknown
from backend.ai_advisor.conversation_models import (
    AdvisorContextEnvelope,
    AdvisorFreshnessState,
    AdvisorRequest,
    AdvisorSourceType,
)
from backend.ai_advisor.prompt_models import AdvisorPromptEnvelope
from backend.ai_advisor.response_models import (
    MAX_SERIALIZED_RESPONSE_CHARACTERS,
    REJECTED_SUMMARY,
    AdvisorForbiddenClaim,
    AdvisorCitation,
    AdvisorFreshnessDisclosure,
    AdvisorGroundedClaim,
    AdvisorRawResponse,
    AdvisorResponseCandidate,
    AdvisorResponseEnvelope,
    AdvisorResponseIntegrityDiagnostic,
    AdvisorResponseIntegrityField,
    AdvisorResponseIntegrityViolationCode,
    AdvisorResponseStatus,
    AdvisorUncertainty,
    AdvisorResponseWarningCode,
    AdvisorSafetyDisclosure,
)
from backend.ai_advisor.response_parser import parse_advisor_response

FORBIDDEN_CLAIM_PRIORITY = (
    AdvisorForbiddenClaim.SECRET_DISCLOSURE_CLAIM,
    AdvisorForbiddenClaim.UNGROUNDED_CURRENT_MARKET_CLAIM,
    AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM,
    AdvisorForbiddenClaim.EXECUTION_CLAIM,
    AdvisorForbiddenClaim.ORDER_ACTION_CLAIM,
    AdvisorForbiddenClaim.POSITION_ACTION_CLAIM,
    AdvisorForbiddenClaim.GOVERNANCE_OVERRIDE_CLAIM,
    AdvisorForbiddenClaim.AUTHORITY_ESCALATION_CLAIM,
    AdvisorForbiddenClaim.TOOL_USE_CLAIM,
    AdvisorForbiddenClaim.FILESYSTEM_ACCESS_CLAIM,
    AdvisorForbiddenClaim.NETWORK_ACCESS_CLAIM,
    AdvisorForbiddenClaim.BOT_CONTROL_CLAIM,
    AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,
)
REQUIRED_SAFETY_DISCLOSURES = (
    AdvisorSafetyDisclosure.READ_ONLY,
    AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
    AdvisorSafetyDisclosure.NO_STATE_CHANGED,
    AdvisorSafetyDisclosure.NO_TOOL_USED,
)

_UNSAFE_PATH = re.compile(
    r"(?ix)"
    r"(?:\bfile://)"
    r"|(?://[^/\s]+/[^/\s]+)"
    r"|(?:(?:^|[\s\"'(])/(?:[^/\s]+/)+[^/\s]*)"
    r"|(?:[a-z]:[\\/])"
    r"|(?:\\\\[^\\\s]+\\[^\\\s]+)"
    r"|(?:^|[\\/])\.\.(?:[\\/]|$)"
    r"|(?:%2e%2e(?:%2f|%5c|/|\\|$))"
)
_SECRET_CLAIM = re.compile(
    r"(?i)\b(?:your\s+api\s+key\s+is|your\s+password\s+is|" r"the\s+token\s+is)\b"
)
_CLAIM_PATTERNS = (
    (
        AdvisorForbiddenClaim.EXECUTION_CLAIM,
        re.compile(
            r"(?i)\b(?:i\s+(?:have\s+)?ex[\s-]*e[\s-]*cuted\s+(?:the\s+)?trade|"
            r"the\s+trade\s+was\s+ex[\s-]*e[\s-]*cuted\s+by\s+me)\b"
            r"|取引を実行しました"
        ),
    ),
    (
        AdvisorForbiddenClaim.ORDER_ACTION_CLAIM,
        re.compile(
            r"(?i)\b(?:order\s+(?:has\s+been\s+)?sub[\s-]*mitted"
            r"(?:\s+successfully)?|the\s+order\s+is\s+now\s+live|"
            r"(?:i\s+)?cancelled\s+(?:the\s+)?order|submit\s+this\s+order)\b"
            r"|注文を送信しました"
        ),
    ),
    (
        AdvisorForbiddenClaim.POSITION_ACTION_CLAIM,
        re.compile(
            r"(?i)\b(?:(?:i\s+)?closed\s+(?:the\s+)?position|position\s+closed)\b"
            r"|ポジションを決済しました"
        ),
    ),
    (
        AdvisorForbiddenClaim.GOVERNANCE_OVERRIDE_CLAIM,
        re.compile(
            r"(?i)\b(?:governance\s+approved|overrode\s+governance|"
            r"governance\s+overridden|safety\s+lock\s+was\s+removed|"
            r"execution\s+is\s+authorized)\b"
            r"|ガバナンスを(?:上書き|解除)しました"
        ),
    ),
    (
        AdvisorForbiddenClaim.AUTHORITY_ESCALATION_CLAIM,
        re.compile(
            r"(?i)\b(?:i\s+am\s+authorized\s+to\s+execute|"
            r"i\s+have\s+administrator\s+permission|"
            r"i\s+can\s+change\s+risk\s+settings)\b"
        ),
    ),
    (
        AdvisorForbiddenClaim.TOOL_USE_CLAIM,
        re.compile(
            r"(?i)\b(?:i\s+(?:used\s+the\s+shell|accessed\s+the\s+database)|"
            r"tool\s+used|run\s+this\s+shell\s+command|"
            r"invoke\s+openai\s+tools?)\b"
        ),
    ),
    (
        AdvisorForbiddenClaim.FILESYSTEM_ACCESS_CLAIM,
        re.compile(
            r"(?i)\b(?:i\s+read\s+(?:the\s+)?local\s+file|"
            r"(?:write|delete)\s+this\s+file)\b"
            r"|ファイルを読みました"
        ),
    ),
    (
        AdvisorForbiddenClaim.NETWORK_ACCESS_CLAIM,
        re.compile(
            r"(?i)\b(?:i\s+(?:called\s+the\s+api|queried\s+the\s+exchange)|"
            r"call\s+this\s+endpoint)\b"
            r"|APIを呼び出しました"
        ),
    ),
    (
        AdvisorForbiddenClaim.BOT_CONTROL_CLAIM,
        re.compile(
            r"(?i)\b(?:i\s+(?:enabled\s+auto\s+trade|started\s+the\s+loop)|"
            r"auto\s+trade\s+enabled|loop\s+started|enable\s+live\s+trading|"
            r"set\s+executionenabled\s*=\s*true|change\s+risk_percent)\b"
            r"|自動売買を有効にしました|ループを開始しました|"
            r"LoopをONにしました"
        ),
    ),
)
_NEGATED_CLAIMS = (
    re.compile(r"(?i)\bi\s+did\s+not\s+execute\s+the\s+trade\b"),
    re.compile(r"(?i)\bno\s+order\s+was\s+submitted\b"),
    re.compile(
        r"(?i)\b(?:do\s+not|don't|never|avoid|should\s+not|must\s+not)\s+"
        r"(?:submit|send|place|execute|cancel)\s+"
        r"(?:(?:this|the|an?|any)\s+)?(?:order|trade)\b"
    ),
    re.compile(
        r"(?i)\b(?:do\s+not|don't|never|avoid|should\s+not|must\s+not)\s+"
        r"(?:enable|start|turn\s+on)\s+"
        r"(?:live\s+trading|auto\s+trade|the\s+loop|the\s+bot)\b"
    ),
    re.compile(r"取引は実行していません"),
    re.compile(r"(?:取引|注文)(?:を)?(?:実行|送信|発注)?(?:しない|しません|せず|しないで|見送る)"),
    re.compile(r"(?:自動売買|ライブ取引|ループ|Bot)(?:を)?(?:有効化|開始)?(?:しない|しません|せず|しないで)"),
)
_CURRENT_MARKET_CLAIM = re.compile(
    r"(?is)(?:\b[A-Z0-9]{5,20}\b.{0,80}\b(?:is\s+currently|is\s+now)\s+"
    r"(?:bullish|bearish|rising|falling|trending)|"
    r"\b(?:currently|right\s+now)\b.{0,80}\b[A-Z0-9]{5,20}\b.{0,80}"
    r"\b(?:bullish|bearish|rising|falling|trending)|"
    r"\b[A-Z0-9]{5,20}\b.{0,80}(?:現在|現時点).{0,40}"
    r"(?:強気|弱気|上昇|下落|トレンド))"
)
_CURRENT_RUNTIME_CLAIM = re.compile(
    r"(?is)(?:\b(?:current|currently|right\s+now)\b.{0,50}"
    r"\b(?:bot|loop|auto\s*trade|risk\s*state|runtime|execution\s*mode|"
    r"position|balance|recorder|governance|emergency)\b.{0,50}(?:\bis\b|=)|"
    r"\b(?:bot|loop|auto\s*trade|risk\s*state|runtime|execution\s*mode|"
    r"position|balance|recorder|governance|emergency)\b.{0,50}"
    r"\b(?:is\s+currently|is\s+now)\b|"
    r"(?:現在|現時点)(?:の)?(?:Bot|Loop|Auto\s*Trade|Risk\s*State|"
    r"リスク状態|Runtime|実行モード|Execution\s*Mode|ポジション|残高|"
    r"Market\s*Recorder|Recorder|Governance|Emergency).{0,60}(?:は|=|です))"
)
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_INVALID_UNICODE = re.compile("[\ud800-\udfff]")


def _normalized_security_text(value: str) -> str:
    normalized = html.unescape(html.unescape(value))
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = _ZERO_WIDTH.sub("", normalized)
    for negative in _NEGATED_CLAIMS:
        normalized = negative.sub("[NEGATED_SAFE_STATEMENT]", normalized)
    return normalized


def _decoded_path_text(value: str) -> str:
    decoded = html.unescape(html.unescape(value))
    decoded = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", decoded))
    decoded = re.sub(r"[\r\n\t]+", "", decoded)
    for _ in range(2):
        decoded = unquote(decoded)
    return decoded


def _text_values(candidate: AdvisorResponseCandidate) -> tuple[str, ...]:
    return (
        candidate.summary,
        *(item.statement for item in candidate.facts),
        *(item.statement for item in candidate.inferences),
        *(item.topic for item in candidate.unknowns),
        *(item.message for item in candidate.warnings if item.message is not None),
        *candidate.sourceReferences,
    )


def _detect_claims(
    candidate: AdvisorResponseCandidate,
) -> tuple[AdvisorForbiddenClaim, ...]:
    detected = set()
    for text in _text_values(candidate):
        normalized = _normalized_security_text(text)
        path_text = _decoded_path_text(text)
        sanitized = sanitize_text(normalized)
        compact = re.sub(r"[\s'\"_-]+", "", normalized).casefold()
        if (
            sanitized.sensitiveRemoved
            or _SECRET_CLAIM.search(normalized)
            or any(
                marker in compact
                for marker in (
                    "apikey",
                    "apisecret",
                    "kucoinkey",
                    "kucoinsecret",
                    "kucoinpassphrase",
                    "authorization:",
                    "bearer",
                    "password:",
                    "password=",
                )
            )
        ):
            detected.add(AdvisorForbiddenClaim.SECRET_DISCLOSURE_CLAIM)
        if (
            sanitized.pathRemoved
            or _UNSAFE_PATH.search(path_text)
            or _INVALID_UNICODE.search(text)
        ):
            detected.add(AdvisorForbiddenClaim.FILESYSTEM_ACCESS_CLAIM)
        for code, pattern in _CLAIM_PATTERNS:
            if pattern.search(normalized):
                detected.add(code)
    return tuple(code for code in FORBIDDEN_CLAIM_PRIORITY if code in detected)


def _has_ungrounded_current_market_claim(
    candidate: AdvisorResponseCandidate,
    context: AdvisorContextEnvelope,
) -> bool:
    if not any(_CURRENT_MARKET_CLAIM.search(text) for text in _text_values(candidate)):
        return False
    referenced = set(candidate.sourceReferences)
    return not any(
        source.sourceId in referenced
        and source.sourceType is AdvisorSourceType.MARKET_INTELLIGENCE
        and source.freshness.state is AdvisorFreshnessState.FRESH
        for source in context.sources
    )


def _has_ungrounded_current_runtime_claim(
    candidate: AdvisorResponseCandidate,
    context: AdvisorContextEnvelope,
) -> bool:
    if not any(_CURRENT_RUNTIME_CLAIM.search(text) for text in _text_values(candidate)):
        return False
    referenced = set(candidate.sourceReferences)
    current_source_types = {
        AdvisorSourceType.RUNTIME,
        AdvisorSourceType.MARKET_INTELLIGENCE,
        AdvisorSourceType.TRADING_DECISION,
        AdvisorSourceType.MONEY_MANAGEMENT,
        AdvisorSourceType.GOVERNANCE,
        AdvisorSourceType.EXECUTION_RESULT,
    }
    return not any(
        source.sourceId in referenced
        and source.sourceType in current_source_types
        and source.freshness.state is AdvisorFreshnessState.FRESH
        for source in context.sources
    )


def _duplicates(values: Iterable[str]) -> bool:
    materialized = tuple(values)
    return len(materialized) != len(set(materialized))


@dataclass(frozen=True)
class AdvisorResponseValidationOutcome:
    response: AdvisorResponseEnvelope
    integrityDiagnostic: AdvisorResponseIntegrityDiagnostic | None = None


def _diagnostic(
    code: AdvisorResponseIntegrityViolationCode,
    field: AdvisorResponseIntegrityField,
) -> AdvisorResponseIntegrityDiagnostic:
    return AdvisorResponseIntegrityDiagnostic(violationCode=code, field=field)


def _first_integrity_violation(
    *,
    raw_response: AdvisorRawResponse,
    request: AdvisorRequest,
    context: AdvisorContextEnvelope,
    prompt_envelope: AdvisorPromptEnvelope,
    candidate: AdvisorResponseCandidate,
) -> AdvisorResponseIntegrityDiagnostic | None:
    """Return the first violation in stable contract order without content."""

    if (
        raw_response.requestId != request.requestId
        or raw_response.requestId != candidate.requestId
        or prompt_envelope.requestId != request.requestId
    ):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.REQUEST_IDENTITY_MISMATCH,
            AdvisorResponseIntegrityField.REQUEST_ID,
        )
    if (
        raw_response.promptVersion != prompt_envelope.promptVersion
        or candidate.promptVersion != prompt_envelope.promptVersion
    ):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.PROMPT_IDENTITY_MISMATCH,
            AdvisorResponseIntegrityField.PROMPT_VERSION,
        )
    if request.contextEnvelope != context:
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.CONTEXT_IDENTITY_MISMATCH,
            AdvisorResponseIntegrityField.CONTEXT_ENVELOPE,
        )
    if _duplicates(fact.factId for fact in candidate.facts):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_FACT_ID,
            AdvisorResponseIntegrityField.FACT_ID,
        )
    if _duplicates(item.inferenceId for item in candidate.inferences):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_INFERENCE_ID,
            AdvisorResponseIntegrityField.INFERENCE_ID,
        )
    if _duplicates(item.unknownId for item in candidate.unknowns):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_UNKNOWN_ID,
            AdvisorResponseIntegrityField.UNKNOWN_ID,
        )
    if any(_duplicates(fact.sourceIds) for fact in candidate.facts):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_FACT_SOURCE_ID,
            AdvisorResponseIntegrityField.FACT_SOURCE_IDS,
        )
    if any(
        _duplicates(item.basedOnSourceIds) for item in candidate.inferences
    ):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_INFERENCE_SOURCE_ID,
            AdvisorResponseIntegrityField.INFERENCE_SOURCE_IDS,
        )
    referenced = tuple(candidate.sourceReferences)
    if _duplicates(referenced):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_SOURCE_REFERENCE,
            AdvisorResponseIntegrityField.SOURCE_REFERENCES,
        )
    if _duplicates(item.sourceId for item in candidate.freshnessDisclosures):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.DUPLICATE_FRESHNESS_DISCLOSURE,
            AdvisorResponseIntegrityField.FRESHNESS_DISCLOSURES,
        )
    known_sources = {source.sourceId: source for source in context.sources}
    if not set(referenced) <= set(known_sources):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.SOURCE_REFERENCE_NOT_TRUSTED,
            AdvisorResponseIntegrityField.SOURCE_REFERENCES,
        )
    used = tuple(
        source_id for fact in candidate.facts for source_id in fact.sourceIds
    ) + tuple(
        source_id
        for inference in candidate.inferences
        for source_id in inference.basedOnSourceIds
    )
    if set(used) != set(referenced):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.SOURCE_USAGE_REFERENCE_SET_MISMATCH,
            AdvisorResponseIntegrityField.SOURCE_REFERENCES,
        )
    disclosures = {item.sourceId: item for item in candidate.freshnessDisclosures}
    if set(disclosures) != set(referenced):
        return _diagnostic(
            AdvisorResponseIntegrityViolationCode.FRESHNESS_REFERENCE_SET_MISMATCH,
            AdvisorResponseIntegrityField.FRESHNESS_DISCLOSURES,
        )
    for source_id in referenced:
        if (
            disclosures[source_id].freshness
            is not known_sources[source_id].freshness.state
        ):
            return _diagnostic(
                AdvisorResponseIntegrityViolationCode.SOURCE_FRESHNESS_MISMATCH,
                AdvisorResponseIntegrityField.FRESHNESS_DISCLOSURES,
            )
    for fact in candidate.facts:
        states = {
            known_sources[source_id].freshness.state
            for source_id in fact.sourceIds
            if source_id in known_sources
        }
        if len(states) != 1:
            return _diagnostic(
                AdvisorResponseIntegrityViolationCode.FACT_SOURCE_FRESHNESS_AMBIGUOUS,
                AdvisorResponseIntegrityField.FACT_SOURCE_IDS,
            )
        if fact.freshness not in states:
            return _diagnostic(
                AdvisorResponseIntegrityViolationCode.FACT_FRESHNESS_MISMATCH,
                AdvisorResponseIntegrityField.FACT_FRESHNESS,
            )
    return None


def _fallback(
    raw: AdvisorRawResponse,
    claims: tuple[AdvisorForbiddenClaim, ...],
    *,
    request_id: str,
    prompt_version: str,
) -> AdvisorResponseEnvelope:
    ordered = tuple(code for code in FORBIDDEN_CLAIM_PRIORITY if code in set(claims))
    if not ordered:
        ordered = (AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,)
    return AdvisorResponseEnvelope(
        responseVersion="1.0",
        requestId=request_id,
        promptVersion=prompt_version,
        receivedAt=raw.receivedAt,
        status=AdvisorResponseStatus.REJECTED,
        summary=REJECTED_SUMMARY,
        facts=(),
        inferences=(),
        unknowns=(),
        warnings=(),
        sourceReferences=(),
        freshnessDisclosures=(),
        safetyDisclosures=REQUIRED_SAFETY_DISCLOSURES
        + (AdvisorSafetyDisclosure.USER_REVIEW_REQUIRED,),
        forbiddenClaims=ordered,
        validationWarnings=(),
        primaryRejectionReason=ordered[0],
    )


def validate_advisor_response_with_diagnostic(
    *,
    raw_response: AdvisorRawResponse,
    request: AdvisorRequest,
    context: AdvisorContextEnvelope,
    prompt_envelope: AdvisorPromptEnvelope,
) -> AdvisorResponseValidationOutcome:
    """Parse, compare, classify, and return a deterministic safe envelope."""

    if not isinstance(raw_response, AdvisorRawResponse):
        raise TypeError("typed AdvisorRawResponse required")
    if not isinstance(request, AdvisorRequest):
        raise TypeError("typed AdvisorRequest required")
    if not isinstance(context, AdvisorContextEnvelope):
        raise TypeError("typed AdvisorContextEnvelope required")
    if not isinstance(prompt_envelope, AdvisorPromptEnvelope):
        raise TypeError("typed AdvisorPromptEnvelope required")
    try:
        raw_response = AdvisorRawResponse.model_validate(raw_response.model_dump())
        request = AdvisorRequest.model_validate(request.model_dump())
        context = AdvisorContextEnvelope.model_validate(context.model_dump())
        prompt_envelope = AdvisorPromptEnvelope.model_validate(
            prompt_envelope.model_dump()
        )
    except ValidationError:
        raise ValueError("advisor response validation input failed") from None
    try:
        candidate = parse_advisor_response(raw_response)
    except ValueError:
        return AdvisorResponseValidationOutcome(
            response=_fallback(
                raw_response,
                (AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,),
                request_id=request.requestId,
                prompt_version=prompt_envelope.promptVersion,
            ),
            integrityDiagnostic=_diagnostic(
                AdvisorResponseIntegrityViolationCode.PARSE_CONTRACT_INVALID,
                AdvisorResponseIntegrityField.RESPONSE_TEXT,
            ),
        )
    claims = _detect_claims(candidate)
    if _has_ungrounded_current_market_claim(candidate, context):
        claims += (AdvisorForbiddenClaim.UNGROUNDED_CURRENT_MARKET_CLAIM,)
    if _has_ungrounded_current_runtime_claim(candidate, context):
        claims += (AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM,)
    integrity_diagnostic = _first_integrity_violation(
        raw_response=raw_response,
        request=request,
        context=context,
        prompt_envelope=prompt_envelope,
        candidate=candidate,
    )
    if integrity_diagnostic is not None:
        claims += (AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,)
    if claims:
        return AdvisorResponseValidationOutcome(
            response=_fallback(
                raw_response,
                tuple(set(claims)),
                request_id=request.requestId,
                prompt_version=prompt_envelope.promptVersion,
            ),
            integrityDiagnostic=integrity_diagnostic,
        )
    known_sources = {source.sourceId: source for source in context.sources}
    referenced = tuple(candidate.sourceReferences)
    facts = tuple(sorted(candidate.facts, key=lambda item: item.factId))
    inferences = tuple(sorted(candidate.inferences, key=lambda item: item.inferenceId))
    unknowns = tuple(sorted(candidate.unknowns, key=lambda item: item.unknownId))
    warnings = tuple(
        sorted(
            {
                (item.code.value, item.message or ""): item
                for item in candidate.warnings
            }.values(),
            key=lambda item: (item.code.value, item.message or ""),
        )
    )
    references = tuple(sorted(referenced))
    freshness = tuple(
        sorted(candidate.freshnessDisclosures, key=lambda item: item.sourceId)
    )
    safety = tuple(
        item
        for item in AdvisorSafetyDisclosure
        if item in set(candidate.safetyDisclosures) | set(REQUIRED_SAFETY_DISCLOSURES)
    )
    validation_warnings = set()
    if inferences:
        validation_warnings.add(AdvisorResponseWarningCode.INFERENCE_PRESENT)
    status = (
        AdvisorResponseStatus.VALID_WITH_WARNINGS
        if warnings or unknowns or validation_warnings
        else AdvisorResponseStatus.VALID
    )
    grounded_claims = (
        tuple(
            AdvisorGroundedClaim(
                claimId=item.factId,
                claimType=(
                    "INTERPRETATION"
                    if item.freshness
                    in {
                        AdvisorFreshnessState.STALE,
                        AdvisorFreshnessState.UNKNOWN,
                        AdvisorFreshnessState.LAST_GOOD,
                    }
                    else "FACT"
                ),
                text=item.statement,
                citationSourceIds=item.sourceIds,
                uncertainty=(
                    AdvisorUncertainty.HIGH
                    if item.freshness
                    in {
                        AdvisorFreshnessState.STALE,
                        AdvisorFreshnessState.UNKNOWN,
                        AdvisorFreshnessState.LAST_GOOD,
                    }
                    else AdvisorUncertainty.LOW
                ),
                freshness=item.freshness,
            )
            for item in facts
        )
        + tuple(
            AdvisorGroundedClaim(
                claimId=item.inferenceId,
                claimType="INFERENCE",
                text=item.statement,
                citationSourceIds=item.basedOnSourceIds,
                uncertainty=item.uncertainty,
                freshness=AdvisorFreshnessState.NOT_APPLICABLE,
            )
            for item in inferences
        )
        + tuple(
            AdvisorGroundedClaim(
                claimId=item.unknownId,
                claimType="UNKNOWN",
                text=item.topic,
                citationSourceIds=(),
                uncertainty=AdvisorUncertainty.HIGH,
                freshness=AdvisorFreshnessState.UNKNOWN,
            )
            for item in unknowns
        )
    )
    claim_sources = {
        claim.claimId: set(claim.citationSourceIds) for claim in grounded_claims
    }
    citations = tuple(
        AdvisorCitation(
            sourceId=source_id,
            sourceType=known_sources[source_id].sourceType,
            displayTitle=known_sources[source_id].displayLabel,
            version=known_sources[source_id].sourceVersion,
            claimIds=tuple(
                claim_id
                for claim_id, source_ids in claim_sources.items()
                if source_id in source_ids
            ),
            freshness=known_sources[source_id].freshness.state,
        )
        for source_id in references
    )
    result = AdvisorResponseEnvelope(
        responseVersion="1.0",
        requestId=request.requestId,
        promptVersion=prompt_envelope.promptVersion,
        receivedAt=raw_response.receivedAt,
        status=status,
        summary=candidate.summary,
        facts=facts,
        inferences=inferences,
        unknowns=unknowns,
        warnings=warnings,
        sourceReferences=references,
        freshnessDisclosures=freshness,
        safetyDisclosures=safety,
        forbiddenClaims=(),
        validationWarnings=tuple(
            sorted(validation_warnings, key=lambda item: item.value)
        ),
        primaryRejectionReason=None,
        responseCategory=(
            "INSUFFICIENT_DATA"
            if unknowns and not facts and not inferences
            else (
                "SPECIFICATION_LOOKUP"
                if any(
                    known_sources[source_id].sourceType
                    is AdvisorSourceType.SPECIFICATION
                    for source_id in references
                )
                else "SYSTEM_GUIDANCE"
            )
        ),
        conclusion=candidate.summary,
        groundedClaims=grounded_claims,
        actionableUnknowns=tuple(
            project_actionable_unknown(item) for item in unknowns
        ),
        citations=citations,
        limitations=(
            "Read-only explanation; no order execution or configuration changes.",
        ),
        safeAlternative=None,
        refusalCategory=None,
    )
    if len(result.model_dump_json()) > MAX_SERIALIZED_RESPONSE_CHARACTERS:
        return AdvisorResponseValidationOutcome(
            response=_fallback(
                raw_response,
                (AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,),
                request_id=request.requestId,
                prompt_version=prompt_envelope.promptVersion,
            ),
            integrityDiagnostic=_diagnostic(
                AdvisorResponseIntegrityViolationCode.SERIALIZED_RESPONSE_TOO_LARGE,
                AdvisorResponseIntegrityField.RESPONSE_ENVELOPE,
            ),
        )
    return AdvisorResponseValidationOutcome(response=result)


def validate_advisor_response(
    *,
    raw_response: AdvisorRawResponse,
    request: AdvisorRequest,
    context: AdvisorContextEnvelope,
    prompt_envelope: AdvisorPromptEnvelope,
) -> AdvisorResponseEnvelope:
    """Compatibility wrapper returning only the public response envelope."""

    return validate_advisor_response_with_diagnostic(
        raw_response=raw_response,
        request=request,
        context=context,
        prompt_envelope=prompt_envelope,
    ).response
