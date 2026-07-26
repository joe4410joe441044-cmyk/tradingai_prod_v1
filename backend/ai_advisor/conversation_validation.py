"""Cross-envelope validation helpers for AI Advisor conversation contracts."""

from datetime import datetime, timedelta, timezone

from backend.ai_advisor.conversation_models import (
    AdvisorClientRequest,
    AdvisorPermissionContext,
    AdvisorRefusalCode,
    AdvisorRequest,
    AdvisorResponse,
)

MAX_REQUEST_FUTURE_SKEW_SECONDS = 300

REFUSAL_PRIORITY = (
    AdvisorRefusalCode.AUTHENTICATION_REQUIRED,
    AdvisorRefusalCode.AUTHORIZATION_DENIED,
    AdvisorRefusalCode.SENSITIVE_DATA_REQUEST,
    AdvisorRefusalCode.ORDER_OPERATION_NOT_ALLOWED,
    AdvisorRefusalCode.GOVERNANCE_OVERRIDE_NOT_ALLOWED,
    AdvisorRefusalCode.MONEY_MANAGEMENT_OVERRIDE_NOT_ALLOWED,
    AdvisorRefusalCode.STRATEGY_OVERRIDE_NOT_ALLOWED,
    AdvisorRefusalCode.CONFIGURATION_CHANGE_NOT_ALLOWED,
    AdvisorRefusalCode.MUTATION_NOT_ALLOWED,
    AdvisorRefusalCode.TRADING_INSTRUCTION_NOT_ALLOWED,
    AdvisorRefusalCode.PROMPT_INJECTION_SUSPECTED,
    AdvisorRefusalCode.EXTERNAL_SEND_NOT_ALLOWED,
    AdvisorRefusalCode.PERSISTENCE_NOT_ALLOWED,
)


def select_refusal_code(
    candidates: tuple[AdvisorRefusalCode, ...],
) -> AdvisorRefusalCode:
    """Return a stable safety-first reason without inspecting raw input."""

    if not candidates:
        raise ValueError("at least one refusal reason is required")
    unique = set(candidates)
    for code in REFUSAL_PRIORITY:
        if code in unique:
            return code
    raise ValueError("unsupported refusal reason")


def parse_untrusted_client_request(
    payload: str | bytes | bytearray,
) -> AdvisorClientRequest:
    """Parse JSON while rejecting permission self-assertion and extra fields."""

    return AdvisorClientRequest.model_validate_json(payload)


def attach_trusted_permission_context(
    client_request: AdvisorClientRequest,
    permission_context: AdvisorPermissionContext,
) -> AdvisorRequest:
    """Create the internal envelope after a separate server Auth layer."""

    return AdvisorRequest(
        schemaVersion=client_request.schemaVersion,
        requestId=client_request.requestId,
        conversationId=client_request.conversationId,
        messageId=client_request.messageId,
        message=client_request.message,
        requestType=client_request.requestType,
        locale=client_request.locale,
        requestedAt=client_request.requestedAt,
        contextEnvelope=client_request.contextEnvelope,
        responsePreferences=client_request.responsePreferences,
        permissionContext=permission_context,
    )


def validate_request_time(
    request: AdvisorRequest,
    *,
    now: datetime,
    max_future_skew_seconds: int = MAX_REQUEST_FUTURE_SKEW_SECONDS,
) -> None:
    """Validate caller-supplied time without reading a clock implicitly."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    normalized_now = now.astimezone(timezone.utc)
    maximum = normalized_now + timedelta(seconds=max_future_skew_seconds)
    if request.requestedAt > maximum:
        raise ValueError("requestedAt exceeds allowed future clock skew")


def validate_trusted_request(request: AdvisorRequest) -> None:
    """Fail closed unless trusted server authentication permits conversation."""

    if not request.permissionContext.conversationAllowed:
        raise ValueError("authenticated and authorized server context is required")


def validate_request_response_pair(
    request: AdvisorRequest,
    response: AdvisorResponse,
) -> None:
    """Validate correlation without mutating either envelope."""

    if response.requestId != request.requestId:
        raise ValueError("response requestId does not match request")
    if response.conversationId != request.conversationId:
        raise ValueError("response conversationId does not match request")
