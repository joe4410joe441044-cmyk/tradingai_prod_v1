"""Operator session enforcement dependency for Operation control routes.

The dependency reuses the session already validated and attached to the ASGI
scope by :class:`OperatorSessionMiddleware`. It grants access only when a
valid, non-expired operator session is present. It never trusts a cookie
presence, client IP, origin, or frontend state. Failure is closed (denied).
"""

from fastapi import HTTPException, Request


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
