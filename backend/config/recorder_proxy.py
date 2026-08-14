# -*- coding: utf-8 -*-
"""Configuration contract for the read-only Market Recorder proxy.

The proxy never hard-codes an upstream host.  The upstream Base URL is taken
exclusively from the process environment (``RECORDER_API_BASE_URL``) and is
validated before use.  When configuration is missing or invalid the proxy
fails closed (disabled) so that no request is ever forwarded.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

RECORDER_API_ENABLED = "RECORDER_API_ENABLED"
RECORDER_API_BASE_URL = "RECORDER_API_BASE_URL"
RECORDER_API_TIMEOUT = "RECORDER_API_TIMEOUT"
RECORDER_API_VERIFY_TLS = "RECORDER_API_VERIFY_TLS"

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_VERIFY_TLS = True


class RecorderProxyConfigError(Exception):
    """Raised when the recorder proxy configuration is invalid.

    The message is intentionally generic: raw configuration values (hosts,
    credentials, paths) must never leak into logs or responses.
    """


def _parse_bool(value, name):
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    raise RecorderProxyConfigError(f"invalid boolean for {name}")


def _validate_base_url(value):
    """Validate and normalize an upstream Base URL.

    Rejects any scheme other than http/https, embedded credentials, query
    strings, fragments, empty hosts, and non-empty path segments.  A trailing
    slash is normalized away.  This is the single trusted source for the
    upstream origin: client input never reaches the URL builder.
    """
    if value is None:
        raise RecorderProxyConfigError("RECORDER_API_BASE_URL not set")
    text = value.strip()
    if not text:
        raise RecorderProxyConfigError("RECORDER_API_BASE_URL empty")

    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        raise RecorderProxyConfigError("unsupported scheme")
    if parsed.username or parsed.password:
        raise RecorderProxyConfigError("credentials not allowed in base URL")
    if parsed.query:
        raise RecorderProxyConfigError("query not allowed in base URL")
    if parsed.fragment:
        raise RecorderProxyConfigError("fragment not allowed in base URL")
    if not parsed.hostname:
        raise RecorderProxyConfigError("host missing in base URL")

    path = parsed.path.rstrip("/")
    if path:
        raise RecorderProxyConfigError("path not allowed in base URL")

    normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return normalized


def _parse_timeout(value):
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(value.strip())
    except (TypeError, ValueError):
        raise RecorderProxyConfigError("invalid timeout") from None
    if timeout <= 0:
        raise RecorderProxyConfigError("invalid timeout")
    return timeout


@dataclass(frozen=True)
class RecorderProxyConfig:
    """Validated read-only recorder proxy configuration."""

    enabled: bool
    base_url: str
    timeout_seconds: float
    verify_tls: bool


def load_recorder_proxy_config(environ=None):
    """Load recorder proxy configuration from the process environment.

    Fail-closed behaviour: unless ``RECORDER_API_ENABLED`` is explicitly
    ``true`` the proxy is disabled and no upstream URL is required.  When
    enabled, a missing or invalid Base URL raises ``RecorderProxyConfigError``.
    """
    if environ is None:
        environ = os.environ

    enabled = _parse_bool(environ.get(RECORDER_API_ENABLED), RECORDER_API_ENABLED)
    if enabled is not True:
        return RecorderProxyConfig(
            enabled=False,
            base_url="",
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            verify_tls=DEFAULT_VERIFY_TLS,
        )

    base_url = _validate_base_url(environ.get(RECORDER_API_BASE_URL))
    timeout = _parse_timeout(environ.get(RECORDER_API_TIMEOUT))
    verify = _parse_bool(environ.get(RECORDER_API_VERIFY_TLS), RECORDER_API_VERIFY_TLS)
    if verify is None:
        verify = DEFAULT_VERIFY_TLS

    return RecorderProxyConfig(
        enabled=True,
        base_url=base_url,
        timeout_seconds=timeout,
        verify_tls=verify,
    )
