import json
import time
from http.cookies import SimpleCookie
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.ai_advisor.api_rate_limit import AdvisorRateLimiter
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    generate_csrf_token,
)
from backend.auth.operator_auth import OperatorAuthenticator
from backend.auth.operator_session import (
    COOKIE_NAME,
    OperatorSessionManager,
)


class LoginRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=256)


class AuthStatusResponse(BaseModel):
    status: Literal["AUTHENTICATED", "UNAUTHENTICATED", "SESSION_EXPIRED"]


SESSION_STALE_RATIO = 0.5


def _session_cookie(
    signed: str,
    config: OperatorAuthConfig,
    max_age: int | None = None,
) -> tuple[str, str]:
    cookie = SimpleCookie()
    cookie[COOKIE_NAME] = signed
    cookie[COOKIE_NAME]["httponly"] = True
    cookie[COOKIE_NAME]["path"] = config.cookie_path
    cookie[COOKIE_NAME]["samesite"] = config.cookie_samesite
    if config.secure_cookie:
        cookie[COOKIE_NAME]["secure"] = True
    if max_age is not None:
        cookie[COOKIE_NAME]["max-age"] = str(max_age)
    return COOKIE_NAME, cookie[COOKIE_NAME].OutputString()


def _csrf_cookie(token: str, config: OperatorAuthConfig) -> tuple[str, str]:
    cookie = SimpleCookie()
    cookie[CSRF_TOKEN_COOKIE] = token
    cookie[CSRF_TOKEN_COOKIE]["httponly"] = False
    cookie[CSRF_TOKEN_COOKIE]["path"] = config.cookie_path
    cookie[CSRF_TOKEN_COOKIE]["samesite"] = config.cookie_samesite
    if config.secure_cookie:
        cookie[CSRF_TOKEN_COOKIE]["secure"] = True
    return CSRF_TOKEN_COOKIE, cookie[CSRF_TOKEN_COOKIE].OutputString()


def _delete_cookie(name: str, config: OperatorAuthConfig) -> tuple[str, str]:
    cookie = SimpleCookie()
    cookie[name] = ""
    cookie[name]["path"] = config.cookie_path
    cookie[name]["max-age"] = "0"
    if config.secure_cookie:
        cookie[name]["secure"] = True
    return name, cookie[name].OutputString()


def create_operator_auth_router(
    authenticator: OperatorAuthenticator,
    session_manager: OperatorSessionManager,
    config: OperatorAuthConfig,
) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    auth_rate_limiter = AdvisorRateLimiter(
        limit=config.auth_rate_limit,
        window_seconds=config.auth_rate_window_seconds,
        clock=time.monotonic,
    )

    def _extract_session_id_from_scope(scope: dict) -> str | None:
        session_data = scope.get("operator_session")
        if isinstance(session_data, dict):
            return session_data.get("session_id")
        return None

    def _read_json_strict(body: bytes) -> dict:
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

    @router.post("/login")
    async def login(request: Request):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type.strip() != "application/json":
            return JSONResponse(
                status_code=415,
                content={"status": "UNAUTHENTICATED"},
            )

        try:
            declared = request.headers.get("content-length")
            if declared is not None:
                declared_size = int(declared)
                if declared_size < 0 or declared_size > 4096:
                    return JSONResponse(
                        status_code=413,
                        content={"status": "UNAUTHENTICATED"},
                    )
            body = await request.body()
            if len(body) > 4096:
                return JSONResponse(
                    status_code=413,
                    content={"status": "UNAUTHENTICATED"},
                )
            parsed = _read_json_strict(body)
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeError):
            return JSONResponse(
                status_code=400,
                content={"status": "UNAUTHENTICATED"},
            )

        credential = parsed.get("credential")
        if not isinstance(credential, str) or not credential:
            return JSONResponse(
                status_code=400,
                content={"status": "UNAUTHENTICATED"},
            )

        if not auth_rate_limiter.allow("__login__"):
            return JSONResponse(
                status_code=429,
                content={"status": "UNAUTHENTICATED"},
                headers={"Retry-After": str(int(auth_rate_limiter.retryAfterSeconds))},
            )

        if not authenticator.authenticate(credential):
            return JSONResponse(
                status_code=401,
                content={"status": "UNAUTHENTICATED"},
            )

        existing_session_id = _extract_session_id_from_scope(request.scope)
        if existing_session_id:
            session_manager.revoke_session(existing_session_id)

        operator_identity = "operator"

        session = session_manager.create_session(operator_identity)
        signed = session_manager.sign(session.session_id)
        csrf_token = generate_csrf_token()

        response = JSONResponse(
            status_code=200,
            content={"status": "AUTHENTICATED", "identity": operator_identity},
        )

        session_cookie_name, session_cookie_value = _session_cookie(
            signed,
            config,
            max_age=config.session_ttl_seconds,
        )
        response.headers.append("Set-Cookie", session_cookie_value)

        csrf_cookie_name, csrf_cookie_value = _csrf_cookie(csrf_token, config)
        response.headers.append("Set-Cookie", csrf_cookie_value)

        response.headers[CSRF_TOKEN_HEADER] = csrf_token

        return response

    @router.post("/logout")
    async def logout(request: Request):
        session_id = _extract_session_id_from_scope(request.scope)
        if session_id:
            session_manager.revoke_session(session_id)

        response = JSONResponse(
            status_code=200,
            content={"status": "UNAUTHENTICATED"},
        )

        _, session_cookie = _delete_cookie(COOKIE_NAME, config)
        response.headers.append("Set-Cookie", session_cookie)

        _, csrf_cookie = _delete_cookie(CSRF_TOKEN_COOKIE, config)
        response.headers.append("Set-Cookie", csrf_cookie)

        return response

    @router.get("/status")
    async def status(request: Request):
        session_data = request.scope.get("operator_session")
        if isinstance(session_data, dict):
            identity = session_data.get("identity")
            if identity:
                return AuthStatusResponse(status="AUTHENTICATED")
            created_at = session_data.get("created_at")
            if isinstance(created_at, (int, float)):
                return AuthStatusResponse(status="SESSION_EXPIRED")
        return AuthStatusResponse(status="UNAUTHENTICATED")

    return router
