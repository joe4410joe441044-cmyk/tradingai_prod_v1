# -*- coding: utf-8 -*-
"""SSRF-safe upstream URL builder for the read-only recorder proxy.

The Base URL comes exclusively from validated configuration, and the endpoint
path is drawn from a fixed allowlist.  Client input (url/host/port/scheme/
path/upstream/target) is never concatenated into an upstream URL.
"""

from urllib.parse import urlparse

ENDPOINT_PATHS = {
    "health": "/api/recorder/health",
    "status": "/api/recorder/status",
    "storage": "/api/recorder/storage",
    "archives": "/api/recorder/archives",
    "start": "/api/recorder/start",
    "stop": "/api/recorder/stop",
}

READ_ENDPOINTS = {"health", "status", "storage", "archives"}


class RecorderProxyURLBuilderError(Exception):
    """Raised when an upstream URL cannot be built safely."""


def normalize_base_url(base_url):
    """Validate a configured Base URL and return it with a trailing slash
    removed.  Only http/https schemes are accepted."""
    if not isinstance(base_url, str) or not base_url:
        raise RecorderProxyURLBuilderError("base url missing")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise RecorderProxyURLBuilderError("unsupported scheme")
    if parsed.username or parsed.password:
        raise RecorderProxyURLBuilderError("credentials not allowed")
    if parsed.query or parsed.fragment:
        raise RecorderProxyURLBuilderError("query or fragment not allowed")
    if not parsed.hostname:
        raise RecorderProxyURLBuilderError("host missing")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def build_upstream_url(base_url, endpoint_key):
    """Build the full upstream URL from a trusted Base URL and a fixed
    endpoint allowlist entry.  Raises for any unknown endpoint key."""
    if endpoint_key not in ENDPOINT_PATHS:
        raise RecorderProxyURLBuilderError("unknown endpoint")
    normalized = normalize_base_url(base_url)
    return normalized + ENDPOINT_PATHS[endpoint_key]
