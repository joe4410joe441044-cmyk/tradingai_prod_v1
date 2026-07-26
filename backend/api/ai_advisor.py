from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.ai_advisor.api_models import (
    AdvisorAPIConfig,
    AdvisorHTTPError,
    AdvisorHTTPRequest,
    AdvisorHTTPResponse,
)
from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.api_security import (
    AdvisorAPIAuthenticator,
    AdvisorAuthenticationError,
    AdvisorAuthorizationError,
)
from backend.ai_advisor.conversation_models import (
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.models import (
    AdvisorErrorDetail,
    AdvisorErrorResponse,
    AdvisorRuntimeResponse,
)
from backend.ai_advisor.service import build_runtime_response
from backend.ai_advisor.service_models import (
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceResult,
    AdvisorServiceStatus,
)


def _occurred_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def advisor_runtime():
    try:
        return build_runtime_response()
    except Exception:
        error = AdvisorErrorResponse(
            error=AdvisorErrorDetail(
                code="ADVISOR_RUNTIME_UNAVAILABLE",
                message="Runtime status is unavailable.",
                retryable=True,
                requestId=str(uuid4()),
                occurredAt=_occurred_at(),
            )
        )
        return JSONResponse(
            status_code=500,
            content=error.model_dump(mode="json"),
        )


def create_runtime_router(composition: AdvisorAPIComposition) -> APIRouter:
    """Create the authenticated read-only runtime route."""

    runtime_router = APIRouter()

    @runtime_router.get(
        "/runtime",
        response_model=AdvisorRuntimeResponse,
        responses={
            401: {"model": AdvisorHTTPError},
            403: {"model": AdvisorHTTPError},
            503: {"model": AdvisorHTTPError},
            500: {"model": AdvisorErrorResponse},
        },
    )
    def authenticated_advisor_runtime(request: Request):
        if composition.config.enabled is not True:
            return _error(503, "ENDPOINT_DISABLED", retryable=False)
        try:
            composition.authenticator.authenticate(_authorization_headers(request))
        except AdvisorAuthenticationError:
            return _error(401, "AUTHENTICATION_REQUIRED", retryable=False)
        except AdvisorAuthorizationError:
            return _error(403, "AUTHORIZATION_DENIED", retryable=False)
        except Exception:
            return _error(401, "AUTHENTICATION_REQUIRED", retryable=False)
        return advisor_runtime()

    return runtime_router


class AdvisorServiceDependency(Protocol):
    def generate_response(
        self, service_input: AdvisorServiceInput
    ) -> AdvisorServiceResult:
        """Generate one advisor result."""


class UnavailableAdvisorService:
    def generate_response(
        self, service_input: AdvisorServiceInput
    ) -> AdvisorServiceResult:
        raise RuntimeError("advisor service unavailable")


@dataclass(frozen=True)
class AdvisorAPIComposition:
    config: AdvisorAPIConfig
    authenticator: AdvisorAPIAuthenticator
    service: AdvisorServiceDependency
    rateLimiter: AdvisorRateLimiter
    concurrencyLimiter: AdvisorConcurrencyLimiter


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


def _error(
    status_code: int,
    error_code: str,
    *,
    retryable: bool,
    headers=None,
) -> JSONResponse:
    value = AdvisorHTTPError(
        errorCode=error_code,
        safeMessage=_SAFE_MESSAGES[error_code],
        retryable=retryable,
    )
    return JSONResponse(
        status_code=status_code,
        content=value.model_dump(mode="json"),
        headers=headers,
    )


def _load_json_strict(body: bytes):
    def reject_constant(value):
        raise ValueError("non-finite JSON number")

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        body,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def _authorization_headers(request: Request):
    return [
        value.decode("latin-1")
        for name, value in request.scope.get("headers", ())
        if name.lower() == b"authorization"
    ]


def _domain_status(code: AdvisorServiceFailureCode) -> int:
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


def create_advice_router(composition: AdvisorAPIComposition) -> APIRouter:
    advice_router = APIRouter()

    @advice_router.post("/advice")
    async def advisor_advice(request: Request):
        if composition.config.enabled is not True:
            return _error(503, "ENDPOINT_DISABLED", retryable=False)

        try:
            principal = composition.authenticator.authenticate(
                _authorization_headers(request)
            )
        except AdvisorAuthenticationError:
            return _error(401, "AUTHENTICATION_REQUIRED", retryable=False)
        except AdvisorAuthorizationError:
            return _error(403, "AUTHORIZATION_DENIED", retryable=False)
        except Exception:
            return _error(401, "AUTHENTICATION_REQUIRED", retryable=False)

        content_type = request.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return _error(415, "UNSUPPORTED_MEDIA_TYPE", retryable=False)

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
                if declared_length < 0:
                    raise ValueError
            except ValueError:
                return _error(400, "REQUEST_INVALID", retryable=False)
            if declared_length > composition.config.maxRequestBytes:
                return _error(413, "REQUEST_TOO_LARGE", retryable=False)

        try:
            body = await request.body()
        except Exception:
            return _error(400, "REQUEST_INVALID", retryable=False)
        if len(body) > composition.config.maxRequestBytes:
            return _error(413, "REQUEST_TOO_LARGE", retryable=False)
        try:
            _load_json_strict(body)
            http_request = AdvisorHTTPRequest.model_validate_json(body)
            service_input = AdvisorServiceInput.model_validate(
                http_request.serviceInput.model_dump(warnings=False)
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
            return _error(422, "REQUEST_INVALID", retryable=False)

        permission = service_input.request.permissionContext
        if (
            principal.authenticated is not True
            or principal.advisorAccessAllowed is not True
            or permission.principalId != principal.principalId
            or permission.authenticationState is not AuthenticationState.AUTHENTICATED
            or permission.authorizationState is not AuthorizationState.AUTHORIZED
        ):
            return _error(403, "AUTHORIZATION_DENIED", retryable=False)

        if not composition.rateLimiter.allow(principal.principalId):
            return _error(
                429,
                "RATE_LIMIT_EXCEEDED",
                retryable=True,
                headers={"Retry-After": str(composition.rateLimiter.retryAfterSeconds)},
            )
        if not await composition.concurrencyLimiter.acquire():
            return _error(
                429,
                "CONCURRENCY_LIMIT_EXCEEDED",
                retryable=True,
            )

        released = False
        task = asyncio.create_task(
            asyncio.to_thread(
                composition.service.generate_response,
                service_input,
            )
        )

        def release_when_done(completed_task):
            try:
                completed_task.exception()
            except BaseException:
                pass
            composition.concurrencyLimiter.release()

        try:
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=composition.config.endpointTimeoutSeconds,
            )
        except TimeoutError:
            task.add_done_callback(release_when_done)
            released = True
            return _error(504, "ENDPOINT_TIMEOUT", retryable=False)
        except asyncio.CancelledError:
            task.add_done_callback(release_when_done)
            released = True
            raise
        except Exception:
            return _error(500, "INTERNAL_ERROR", retryable=False)
        finally:
            if not released:
                composition.concurrencyLimiter.release()

        if not isinstance(result, AdvisorServiceResult):
            return _error(500, "INTERNAL_ERROR", retryable=False)
        if result.status is AdvisorServiceStatus.SUCCEEDED:
            response = AdvisorHTTPResponse(
                status=result.status,
                advisorResponse=result.response,
            )
            return JSONResponse(
                status_code=200,
                content=response.model_dump(mode="json"),
            )
        response = AdvisorHTTPResponse(
            status=result.status,
            failureCode=result.failure.code,
            safeMessage=result.failure.safeMessage,
        )
        return JSONResponse(
            status_code=_domain_status(result.failure.code),
            content=response.model_dump(mode="json"),
        )

    return advice_router
