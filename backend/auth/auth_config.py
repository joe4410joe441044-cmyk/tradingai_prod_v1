import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OperatorAuthConfig:
    credential_hash: str | None = None
    session_secret: str | None = None
    session_ttl_seconds: int = 28800
    secure_cookie: bool = False
    cookie_path: str = "/"
    cookie_samesite: str = "lax"
    auth_rate_limit: int = 10
    auth_rate_window_seconds: int = 300


def load_operator_auth_config() -> OperatorAuthConfig:
    credential_hash = os.environ.get("TRADINGAI_OPERATOR_CREDENTIAL_HASH")
    session_secret = os.environ.get("TRADINGAI_SESSION_SECRET")
    ttl_str = os.environ.get("TRADINGAI_SESSION_TTL_SECONDS", "28800")
    secure_str = os.environ.get("TRADINGAI_SECURE_COOKIE", "false")
    samesite = os.environ.get("TRADINGAI_COOKIE_SAMESITE", "lax")

    try:
        ttl = int(ttl_str)
    except ValueError:
        ttl = 28800

    if ttl < 60:
        ttl = 28800

    if samesite not in ("strict", "lax", "none"):
        samesite = "lax"

    rate_limit_str = os.environ.get("TRADINGAI_AUTH_RATE_LIMIT", "10")
    rate_window_str = os.environ.get("TRADINGAI_AUTH_RATE_WINDOW", "300")
    try:
        auth_rate_limit = int(rate_limit_str)
    except ValueError:
        auth_rate_limit = 10
    try:
        auth_rate_window = int(rate_window_str)
    except ValueError:
        auth_rate_window = 300

    return OperatorAuthConfig(
        credential_hash=credential_hash.strip() if credential_hash else None,
        session_secret=session_secret.strip() if session_secret else None,
        session_ttl_seconds=ttl,
        secure_cookie=secure_str.lower() == "true",
        cookie_path="/",
        cookie_samesite=samesite,
        auth_rate_limit=auth_rate_limit,
        auth_rate_window_seconds=auth_rate_window,
    )
