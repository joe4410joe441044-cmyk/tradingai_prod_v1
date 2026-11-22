"""Operator session enforcement dependency for Operation control routes.

The dependency reuses the session already validated and attached to the ASGI
scope by :class:`OperatorSessionMiddleware`. It grants access only when a
valid, non-expired operator session is present. It never trusts a cookie
presence, client IP, origin, or frontend state. Failure is closed (denied).
"""

import secrets

from fastapi import HTTPException, Request

from backend.auth.csrf import CSRF_TOKEN_COOKIE, CSRF_TOKEN_HEADER


def operator_session_identity(request: Request) -> str | None:
    """Return the validated operator identity or ``None``.

    Only an identity injected by :class:`OperatorSessionMiddleware` is
    accepted. A forged or invalid signature, an expired session, a missing
    session, or a spoofed header all resolve to ``None``.
    """
    session_data = request.scope.get("operator_session")
    if isinstance(session_data, dict):
        identity = session_data.get("identity")
        if isinstance(identity, str) and identity:
            return identity
    return None


def require_operator_session(request: Request) -> str:
    """FastAPI dependency: require a valid operator session (fail closed).

    Returns the verified operator identity on success. Raises HTTP 401 for a
    missing session, a forged/invalid session, or an expired session, so the
    caller can distinguish an authentication problem from a normal BOT
    lifecycle rejection.
    """
    identity = operator_session_identity(request)
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail={"status": "UNAUTHENTICATED"},
        )
    return identity


def require_operator_session_context(request: Request) -> dict:
    """Return the validated session context (identity + session id).

    The context originates only from :class:`OperatorSessionMiddleware`. A
    missing, forged, or expired session fails closed with HTTP 401.
    """
    session_data = request.scope.get("operator_session")
    if not isinstance(session_data, dict):
        raise HTTPException(
            status_code=401,
            detail={"status": "UNAUTHENTICATED"},
        )
    identity = session_data.get("identity")
    session_id = session_data.get("session_id")
    if not isinstance(identity, str) or not identity:
        raise HTTPException(
            status_code=401,
            detail={"status": "UNAUTHENTICATED"},
        )
    if not isinstance(session_id, str) or not session_id:
        raise HTTPException(
            status_code=401,
            detail={"status": "UNAUTHENTICATED"},
        )
    return {
        "identity": identity,
        "session_id": session_id,
        "created_at": session_data.get("created_at"),
        "expires_at": session_data.get("expires_at"),
    }


def require_csrf(request: Request) -> None:
    """Enforce the CSRF double-submit contract for a mutating route.

    The token must be present both as the CSRF cookie and in the
    ``X-TradingAI-CSRF`` header, and both values must match. This complements
    the ASGI CSRF middleware and keeps the guarantee even if a route is mounted
    without the middleware's path allowlist.
    """
    cookie_value = request.cookies.get(CSRF_TOKEN_COOKIE)
    header_value = request.headers.get(CSRF_TOKEN_HEADER)
    if not cookie_value or not header_value:
        raise HTTPException(
            status_code=403,
            detail={"status": "UNAUTHENTICATED", "code": "CSRF_REQUIRED"},
        )
    if not secrets.compare_digest(cookie_value, header_value):
        raise HTTPException(
            status_code=403,
            detail={"status": "UNAUTHENTICATED", "code": "CSRF_INVALID"},
        )
