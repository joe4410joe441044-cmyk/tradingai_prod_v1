"""Fail-closed same-origin browser gateway for the read-only AI Advisor."""

import asyncio
import ipaddress
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional, Tuple
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from backend.ai_advisor.api_models import AdvisorHTTPError, AdvisorHTTPResponse
from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.context_builder import (
    SpecificationSourceInput,
    build_advisor_context,
)
from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorConversationMessage,
    AdvisorContractModel,
    AdvisorDataAccessScope,
    AdvisorDetailLevel,
    AdvisorPermissionContext,
    AdvisorRequest,
    AdvisorResponseFormat,
    AdvisorResponsePreferences,
    AdvisorRole,
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceContextInput,
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceResult,
    AdvisorServiceStatus,
)
from backend.ai_advisor.observability import (
    AdvisorObservation,
    AdvisorObservationSink,
    AdvisorSecurityEventCategory,
    NoOpAdvisorObservationSink,
)
from backend.ai_advisor.models import (
    AdvisorBotStatus,
    AdvisorOperationStatus,
    AdvisorRuntimeMetadata,
    AdvisorRuntimeResponse,
    AdvisorSafetyStatus,
    Freshness,
)
from backend.ai_advisor.request_safety import evaluate_advisor_request
from backend.ai_advisor.response_models import (
    REJECTED_SUMMARY,
    AdvisorForbiddenClaim,
    AdvisorResponseEnvelope,
    AdvisorResponseStatus,
    AdvisorSafetyDisclosure,
)
from backend.api.ai_advisor import AdvisorServiceDependency

MAX_BROWSER_PROMPT_BYTES = 12_000
MAX_BROWSER_BODY_BYTES = 12_128
IDENTITY_HEADER = b"x-tradingai-authenticated-user"
CLIENT_HEADER = b"x-tradingai-client"
ORIGIN_HEADER = b"origin"
SEC_FETCH_SITE_HEADER = b"sec-fetch-site"
SAFE_GET_METHODS = frozenset({"GET", "HEAD"})
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")


class AdvisorBrowserRequest(AdvisorContractModel):
    prompt: str = Field(min_length=1, max_length=12_000)


class AdvisorBrowserGatewayConfig(AdvisorContractModel):
    enabled: bool = False
    trustedProxyPeers: Tuple[str, ...] = ()
    allowedOrigins: Tuple[str, ...] = ()
    identityHeaderName: Literal["x-tradingai-authenticated-user"] = (
        "x-tradingai-authenticated-user"
    )
    clientHeaderValue: Literal["web"] = "web"
    requestSizeLimitBytes: int = Field(
        default=MAX_BROWSER_BODY_BYTES,
        ge=1024,
        le=65_536,
    )
    endpointTimeoutSeconds: float = Field(default=35.0, gt=0, le=120)


class AdvisorBrowserStatus(AdvisorContractModel):
    status: Literal[
        "AVAILABLE",
        "OFFLINE",
        "UNAVAILABLE",
        "AUTHENTICATION_REQUIRED",
    ]


@dataclass(frozen=True)
class AdvisorBrowserGatewayComposition:
    config: AdvisorBrowserGatewayConfig
    service: AdvisorServiceDependency
    rateLimiter: AdvisorRateLimiter
    concurrencyLimiter: AdvisorConcurrencyLimiter
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    externalStatus: Literal["AVAILABLE", "OFFLINE", "UNAVAILABLE"] = "OFFLINE"
    observationSink: AdvisorObservationSink = NoOpAdvisorObservationSink()
    approvedSpecifications: Tuple[SpecificationSourceInput, ...] = ()
    requestIdFactory: Callable[[], str] = lambda: str(uuid4())


class BrowserGatewayAuthenticationError(Exception):
    pass


class AdvisorGatewayPreflightDenyMiddleware:
    """Keep the gateway closed even when application-wide CORS is permissive."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        gateway_path = scope.get("type") == "http" and scope.get("path") in {
            "/api/ai-advisor/conversation",
            "/api/ai-advisor/conversation/status",
            "/api/ai-advisor/conversation/runtime",
        }
        if gateway_path and scope.get("method") == "OPTIONS":
            response = _error(403, "AUTHORIZATION_DENIED")
            await response(scope, receive, send)
            return
        if not gateway_path:
            await self.app(scope, receive, send)
            return

        async def send_without_cors(message):
            if message.get("type") == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (name, value)
                    for name, value in message.get("headers", ())
                    if not name.lower().startswith(b"access-control-")
                ]
            await send(message)

        await self.app(scope, receive, send_without_cors)


def load_browser_gateway_config() -> AdvisorBrowserGatewayConfig:
    """Load explicit non-secret gateway policy; malformed values fail closed."""

    enabled = os.environ.get("AI_ADVISOR_BROWSER_GATEWAY_ENABLED") == "true"
    peers = tuple(
        value.strip()
        for value in os.environ.get("AI_ADVISOR_BROWSER_TRUSTED_PROXY_PEERS", "").split(
            ","
        )
        if value.strip()
    )
    origins = tuple(
        value.strip()
        for value in os.environ.get("AI_ADVISOR_BROWSER_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    )
    try:
        for peer in peers:
            ipaddress.ip_address(peer)
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
    except ValueError:
        enabled = False
        peers = ()
        origins = ()
    if not peers or not origins:
        enabled = False
    return AdvisorBrowserGatewayConfig(
        enabled=enabled,
        trustedProxyPeers=peers,
        allowedOrigins=origins,
    )


def _header_values(request: Request, name: bytes) -> list[str]:
    return [
        value.decode("latin-1")
        for header, value in request.scope.get("headers", ())
        if header.lower() == name
    ]


def _trusted_identity(request: Request, config: AdvisorBrowserGatewayConfig) -> str:
    client = request.scope.get("client")
    peer = client[0] if isinstance(client, (tuple, list)) and client else None
    try:
        peer_value = str(ipaddress.ip_address(peer))
        trusted = {
            str(ipaddress.ip_address(value)) for value in config.trustedProxyPeers
        }
    except (TypeError, ValueError):
        raise BrowserGatewayAuthenticationError from None
    if peer_value not in trusted:
        raise BrowserGatewayAuthenticationError
    values = _header_values(request, IDENTITY_HEADER)
    if len(values) != 1:
        raise BrowserGatewayAuthenticationError
    identity = values[0]
    if identity != identity.strip() or not _IDENTITY.fullmatch(identity):
        raise BrowserGatewayAuthenticationError
    return identity


def _session_identity(request: Request) -> str | None:
    session_data = request.scope.get("operator_session")
    if isinstance(session_data, dict):
        identity = session_data.get("identity")
        if isinstance(identity, str) and identity:
            return identity
    return None


def _valid_client(
    request: Request,
    config: AdvisorBrowserGatewayConfig,
) -> bool:
    clients = _header_values(request, CLIENT_HEADER)
    return clients == [config.clientHeaderValue]


def _exact_allowed_origin(
    request: Request,
    config: AdvisorBrowserGatewayConfig,
) -> bool:
    """A present Origin must be a single, well-formed, exact allowed origin."""
    values = _header_values(request, ORIGIN_HEADER)
    if len(values) != 1:
        return False
    origin = values[0]
    try:
        parsed = urlsplit(origin)
        valid_shape = (
            parsed.scheme in {"http", "https"}
            and parsed.netloc
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
        )
    except ValueError:
        return False
    return bool(valid_shape and origin in config.allowedOrigins)


def _browser_same_origin_fetch_metadata(request: Request) -> bool:
    """Browsers omit Origin on same-origin GET/HEAD but attach Fetch Metadata.

    ``Sec-Fetch-Site: same-origin`` is the browser-controlled same-origin proof
    for the session path. Any other value, a missing header, or a duplicate
    header fails closed.
    """
    values = _header_values(request, SEC_FETCH_SITE_HEADER)
    if len(values) != 1:
        return False
    return values[0] == "same-origin"


def _authorized_request(
    request: Request,
    config: AdvisorBrowserGatewayConfig,
    *,
    via_session: bool,
) -> bool:
    """Fail-closed browser authorization for the conversation gateway.

    - Every request must present the exact web client header.
    - If Origin is present, it must exactly match an allowed origin (all
      methods, including the trusted-proxy identity path).
    - For session-authenticated GET/HEAD, a missing Origin is accepted only
      when the browser Fetch Metadata proves same-origin
      (``Sec-Fetch-Site: same-origin``).
    - POST (and any trusted-proxy or non-browser request) with a missing Origin
      fails closed. There is no internal-client contract that permits it.
    """
    if not _valid_client(request, config):
        return False
    method = (request.method or "GET").upper()
    if _header_values(request, ORIGIN_HEADER):
        return _exact_allowed_origin(request, config)
    if method in SAFE_GET_METHODS and via_session:
        return _browser_same_origin_fetch_metadata(request)
    return False


def _load_json_strict(body: bytes):
    def reject_constant(_value):
        raise ValueError("non-finite number")

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    return json.loads(
        body,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def assemble_browser_service_input(
    *,
    prompt: str,
    principal_id: str,
    now: datetime,
    request_id: Optional[str] = None,
    approved_specifications: Tuple[SpecificationSourceInput, ...] = (),
) -> AdvisorServiceInput:
    """Construct the complete trusted input without runtime or client authority."""

    request_id = request_id or str(uuid4())
    message_id = str(uuid4())
    permission = AdvisorPermissionContext(
        principalId=principal_id,
        authenticationState=AuthenticationState.AUTHENTICATED,
        authorizationState=AuthorizationState.AUTHORIZED,
        role="USER",
        permissionLevel="READ_ONLY",
        allowedCapabilities=(
            AdvisorCapability.SYSTEM_GUIDANCE,
            AdvisorCapability.SPECIFICATION_EXPLAIN,
        ),
        dataAccessScope=(
            AdvisorDataAccessScope.PUBLIC_UI_NAVIGATION,
            AdvisorDataAccessScope.APPROVED_LOCAL_SPECIFICATIONS,
        ),
        policyVersion="browser-gateway/v1",
        trustedServerContext=True,
    )
    current_message = AdvisorConversationMessage(
        messageId=message_id,
        role=AdvisorRole.USER,
        content=prompt,
        createdAt=now,
        sourceReferences=(),
    )
    context = build_advisor_context(
        generated_at=now,
        permission_context=permission,
        specifications=approved_specifications,
        current_message=current_message,
    )
    request = AdvisorRequest(
        schemaVersion="1.0",
        requestId=request_id,
        messageId=message_id,
        message=prompt,
        locale="ja-JP",
        requestedAt=now,
        permissionContext=permission,
        contextEnvelope=context,
        responsePreferences=AdvisorResponsePreferences(
            locale="ja-JP",
            detailLevel=AdvisorDetailLevel.STANDARD,
            includeSources=True,
            includeWarnings=True,
            format=AdvisorResponseFormat.STRUCTURED,
        ),
    )
    return AdvisorServiceInput(
        request=request,
        contextInput=AdvisorServiceContextInput(
            generatedAt=now,
            specifications=approved_specifications,
            conversationHistory=(),
            currentMessage=current_message,
        ),
        providerRequestId=request_id,
        receivedAt=now,
    )


_SAFE_MESSAGES = {
    "AUTHENTICATION_REQUIRED": "Authentication required.",
    "AUTHORIZATION_DENIED": "Advisor access is not allowed.",
    "ENDPOINT_DISABLED": "Advisor endpoint is unavailable.",
    "UNSUPPORTED_MEDIA_TYPE": "Content-Type must be application/json.",
    "REQUEST_TOO_LARGE": "Advisor request is too large.",
    "REQUEST_INVALID": "Advisor request validation failed.",
    "RATE_LIMIT_EXCEEDED": "Advisor request rate limit exceeded.",
    "CONCURRENCY_LIMIT_EXCEEDED": "Advisor concurrency limit exceeded.",
    "ENDPOINT_TIMEOUT": "Advisor request timed out.",
    "ADVISOR_UNAVAILABLE": "Advisor service is unavailable.",
    "INTERNAL_ERROR": "Advisor request failed.",
}


def _error(status: int, code: str, retryable: bool = False):
    value = AdvisorHTTPError(
        errorCode=code,
        safeMessage=_SAFE_MESSAGES[code],
        retryable=retryable,
    )
    return JSONResponse(status_code=status, content=value.model_dump(mode="json"))


def _failure_status(code: AdvisorServiceFailureCode) -> int:
    if code in {
        AdvisorServiceFailureCode.ADVISOR_INVALID_CONVERSATION,
        AdvisorServiceFailureCode.ADVISOR_CONTEXT_INVALID,
        AdvisorServiceFailureCode.ADVISOR_PROMPT_INVALID,
        AdvisorServiceFailureCode.ADVISOR_PROVIDER_REQUEST_INVALID,
    }:
        return 422
    if code is AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE:
        return 503
    if code in {
        AdvisorServiceFailureCode.ADVISOR_PROVIDER_RESPONSE_INVALID,
        AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE,
        AdvisorServiceFailureCode.ADVISOR_RESPONSE_INVALID,
    }:
        return 502
    return 500


def _safety_refusal(request_id: str, category: str, now: datetime):
    response = AdvisorResponseEnvelope(
        responseVersion="1.0",
        requestId=request_id,
        promptVersion="browser-safety/v1",
        receivedAt=now,
        status=AdvisorResponseStatus.REJECTED,
        summary=REJECTED_SUMMARY,
        facts=(),
        inferences=(),
        unknowns=(),
        warnings=(),
        sourceReferences=(),
        freshnessDisclosures=(),
        safetyDisclosures=(
            AdvisorSafetyDisclosure.READ_ONLY,
            AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
            AdvisorSafetyDisclosure.NO_STATE_CHANGED,
            AdvisorSafetyDisclosure.NO_TOOL_USED,
            AdvisorSafetyDisclosure.USER_REVIEW_REQUIRED,
        ),
        forbiddenClaims=(AdvisorForbiddenClaim.AUTHORITY_ESCALATION_CLAIM,),
        validationWarnings=(),
        primaryRejectionReason=AdvisorForbiddenClaim.AUTHORITY_ESCALATION_CLAIM,
        responseCategory="SAFETY_REFUSAL",
        conclusion="This request is outside the read-only advisor boundary.",
        limitations=("AI Advisor cannot execute or authorize system changes.",),
        safeAlternative=(
            "Ask for a read-only explanation of an approved recorded state "
            "or specification."
        ),
        refusalCategory=category,
    )
    return AdvisorHTTPResponse(
        status=AdvisorServiceStatus.SUCCEEDED,
        advisorResponse=response,
    )


def create_browser_gateway_router(
    composition: AdvisorBrowserGatewayComposition,
) -> APIRouter:
    router = APIRouter(prefix="/api/ai-advisor/conversation")

    def authorize(request: Request):
        if composition.config.enabled is not True:
            return None, _error(503, "ENDPOINT_DISABLED")

        identity: str | None = None
        try_trusted = False
        try:
            identity = _trusted_identity(request, composition.config)
        except BrowserGatewayAuthenticationError:
            try_trusted = True

        via_session = False
        if identity is None:
            identity = _session_identity(request)
            via_session = identity is not None

        if identity is None:
            if try_trusted:
                composition.observationSink.record(
                    AdvisorObservation(
                        requestId=composition.requestIdFactory(),
                        status="FAILED",
                        failureCode="AUTHENTICATION_REQUIRED",
                        securityEventCategory=AdvisorSecurityEventCategory.AUTHN_FAILED,
                    )
                )
            return None, _error(401, "AUTHENTICATION_REQUIRED")

        if not _authorized_request(
            request,
            composition.config,
            via_session=via_session,
        ):
            composition.observationSink.record(
                AdvisorObservation(
                    requestId=composition.requestIdFactory(),
                    status="FAILED",
                    failureCode="AUTHORIZATION_DENIED",
                    securityEventCategory=AdvisorSecurityEventCategory.AUTHZ_DENIED,
                )
            )
            return None, _error(403, "AUTHORIZATION_DENIED")
        return identity, None

    @router.get("/status", response_model=AdvisorBrowserStatus)
    async def browser_status(request: Request):
        _identity, failure = authorize(request)
        if failure is not None:
            return failure
        return AdvisorBrowserStatus(status=composition.externalStatus)

    @router.get("/runtime", response_model=AdvisorRuntimeResponse)
    async def browser_runtime(request: Request):
        _identity, failure = authorize(request)
        if failure is not None:
            return failure
        return AdvisorRuntimeResponse(
            bot=AdvisorBotStatus(
                state="UNKNOWN",
                mode=None,
                exchange=None,
                symbol=None,
            ),
            operation=AdvisorOperationStatus(
                loopEnabled=False,
                loopState="UNKNOWN",
                autoTradeEnabled=False,
            ),
            safety=AdvisorSafetyStatus(
                emergencyLocked=False,
                emergencyState="UNKNOWN",
                dryRun=False,
                realOrderAllowed=False,
            ),
            runtime=AdvisorRuntimeMetadata(
                capturedAt=composition.clock().astimezone(timezone.utc).isoformat(),
                sourceUpdatedAt=None,
                freshness=Freshness.UNKNOWN,
            ),
            warnings=["RUNTIME_DETAIL_NOT_APPROVED"],
        )

    @router.options("")
    async def reject_preflight():
        return _error(403, "AUTHORIZATION_DENIED")

    @router.post("")
    async def browser_conversation(request: Request):
        identity, failure = authorize(request)
        if failure is not None:
            return failure
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type.strip() != "application/json":
            return _error(415, "UNSUPPORTED_MEDIA_TYPE")
        try:
            declared = request.headers.get("content-length")
            if declared is not None:
                declared_size = int(declared)
                if declared_size < 0:
                    raise ValueError
                if declared_size > composition.config.requestSizeLimitBytes:
                    return _error(413, "REQUEST_TOO_LARGE")
            body = await request.body()
            if len(body) > composition.config.requestSizeLimitBytes:
                return _error(413, "REQUEST_TOO_LARGE")
            parsed = _load_json_strict(body)
            browser_request = AdvisorBrowserRequest.model_validate(parsed)
            if not browser_request.prompt.strip():
                raise ValueError
            if len(browser_request.prompt.encode("utf-8")) > MAX_BROWSER_PROMPT_BYTES:
                return _error(413, "REQUEST_TOO_LARGE")
        except (
            UnicodeError,
            ValueError,
            TypeError,
            ValidationError,
            json.JSONDecodeError,
        ):
            return _error(422, "REQUEST_INVALID")

        safety = evaluate_advisor_request(browser_request.prompt)
        if safety.allowed is not True:
            now = composition.clock().astimezone(timezone.utc)
            request_id = composition.requestIdFactory()
            composition.observationSink.record(
                AdvisorObservation(
                    requestId=request_id,
                    status="REFUSED",
                    responseCategory="SAFETY_REFUSAL",
                    refusalReason=safety.refusalCategory.value,
                    securityEventCategory=AdvisorSecurityEventCategory.POLICY_REFUSAL,
                )
            )
            refused = _safety_refusal(
                request_id,
                safety.refusalCategory.value,
                now,
            )
            return JSONResponse(
                status_code=200,
                content=refused.model_dump(mode="json"),
            )

        if not composition.rateLimiter.allow(identity):
            return _error(429, "RATE_LIMIT_EXCEEDED", retryable=True)
        if not await composition.concurrencyLimiter.acquire():
            return _error(429, "CONCURRENCY_LIMIT_EXCEEDED", retryable=True)
        task = None
        release_later = False
        try:
            now = composition.clock().astimezone(timezone.utc)
            service_input = assemble_browser_service_input(
                prompt=browser_request.prompt,
                principal_id=identity,
                now=now,
                request_id=composition.requestIdFactory(),
                approved_specifications=composition.approvedSpecifications,
            )
            task = asyncio.create_task(
                asyncio.to_thread(composition.service.generate_response, service_input)
            )
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=composition.config.endpointTimeoutSeconds,
            )
        except TimeoutError:
            release_later = True

            def release_when_done(completed):
                try:
                    completed.exception()
                except BaseException:
                    pass
                composition.concurrencyLimiter.release()

            task.add_done_callback(release_when_done)
            return _error(504, "ENDPOINT_TIMEOUT")
        except Exception:
            return _error(500, "INTERNAL_ERROR")
        finally:
            if not release_later:
                composition.concurrencyLimiter.release()
        if not isinstance(result, AdvisorServiceResult):
            return _error(500, "INTERNAL_ERROR")
        if result.status is AdvisorServiceStatus.SUCCEEDED:
            response = AdvisorHTTPResponse(
                status=result.status,
                advisorResponse=result.response,
            )
            return JSONResponse(
                status_code=200, content=response.model_dump(mode="json")
            )
        response = AdvisorHTTPResponse(
            status=result.status,
            failureCode=result.failure.code,
            safeMessage=result.failure.safeMessage,
        )
        return JSONResponse(
            status_code=_failure_status(result.failure.code),
            content=response.model_dump(mode="json"),
        )

    return router
