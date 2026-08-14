# -*- coding: utf-8 -*-
"""Safe error mapping for the read-only Market Recorder proxy.

All upstream/internal failures are normalized to a small allowlist of safe
error codes.  Paths, stack traces, credentials, and internal exception text
are never returned to callers.
"""

PROXY_DISABLED = "market_recorder_proxy_disabled"
CONFIGURATION_ERROR = "market_recorder_proxy_configuration_error"
QUERY_INVALID = "market_recorder_query_invalid"
UPSTREAM_UNAVAILABLE = "market_recorder_upstream_unavailable"
UPSTREAM_TIMEOUT = "market_recorder_upstream_timeout"
UPSTREAM_INVALID_RESPONSE = "market_recorder_upstream_invalid_response"
UPSTREAM_REJECTED = "market_recorder_upstream_rejected"
UPSTREAM_PROTOCOL_ERROR = "market_recorder_upstream_protocol_error"
UPSTREAM_BAD_REQUEST = "market_recorder_upstream_bad_request"
UPSTREAM_CLIENT_IDENTITY_INVALID = "market_recorder_client_identity_invalid"
UPSTREAM_CONFLICT = "market_recorder_upstream_conflict"
UPSTREAM_LOCKED = "market_recorder_upstream_locked"
UPSTREAM_RATE_LIMITED = "market_recorder_upstream_rate_limited"
INTERNAL = "market_recorder_internal_error"

SAFE_MESSAGES = {
    PROXY_DISABLED: "Market recorder proxy is disabled.",
    CONFIGURATION_ERROR: "Market recorder proxy is not configured.",
    QUERY_INVALID: "Market recorder request is invalid.",
    UPSTREAM_UNAVAILABLE: "Market recorder upstream is unavailable.",
    UPSTREAM_TIMEOUT: "Market recorder upstream request timed out.",
    UPSTREAM_INVALID_RESPONSE: "Market recorder upstream returned an invalid response.",
    UPSTREAM_REJECTED: "Market recorder upstream rejected the request.",
    UPSTREAM_PROTOCOL_ERROR: "Market recorder upstream returned a protocol error.",
    UPSTREAM_BAD_REQUEST: "Market recorder upstream rejected the request as invalid.",
    UPSTREAM_CLIENT_IDENTITY_INVALID: "Market recorder client identity was rejected.",
    UPSTREAM_CONFLICT: "Market recorder upstream rejected the request due to a state conflict.",
    UPSTREAM_LOCKED: "Market recorder upstream is locked.",
    UPSTREAM_RATE_LIMITED: "Market recorder upstream rate limit exceeded.",
    INTERNAL: "Market recorder proxy failed.",
}

STATUS_CODES = {
    PROXY_DISABLED: 503,
    CONFIGURATION_ERROR: 503,
    QUERY_INVALID: 400,
    UPSTREAM_UNAVAILABLE: 503,
    UPSTREAM_TIMEOUT: 504,
    UPSTREAM_INVALID_RESPONSE: 502,
    UPSTREAM_REJECTED: 502,
    UPSTREAM_PROTOCOL_ERROR: 502,
    UPSTREAM_BAD_REQUEST: 400,
    UPSTREAM_CLIENT_IDENTITY_INVALID: 401,
    UPSTREAM_CONFLICT: 409,
    UPSTREAM_LOCKED: 423,
    UPSTREAM_RATE_LIMITED: 429,
    INTERNAL: 500,
}

RETRYABLE = {
    PROXY_DISABLED: False,
    CONFIGURATION_ERROR: False,
    QUERY_INVALID: False,
    UPSTREAM_UNAVAILABLE: True,
    UPSTREAM_TIMEOUT: True,
    UPSTREAM_INVALID_RESPONSE: False,
    UPSTREAM_REJECTED: False,
    UPSTREAM_PROTOCOL_ERROR: False,
    UPSTREAM_BAD_REQUEST: False,
    UPSTREAM_CLIENT_IDENTITY_INVALID: False,
    UPSTREAM_CONFLICT: False,
    UPSTREAM_LOCKED: True,
    UPSTREAM_RATE_LIMITED: True,
    INTERNAL: False,
}


def safe_error_payload(code):
    """Return the safe error envelope body for a known code.

    Falls back to a generic internal error for any unknown code so that no
    internal detail can ever leak.
    """
    normalized = code if code in SAFE_MESSAGES else INTERNAL
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": normalized,
            "message": SAFE_MESSAGES[normalized],
            "retryable": RETRYABLE[normalized],
        },
    }


def error_status_code(code):
    return STATUS_CODES.get(code, STATUS_CODES[INTERNAL])


_CONTROL_STATUS_MAP = {
    400: UPSTREAM_BAD_REQUEST,
    401: UPSTREAM_CLIENT_IDENTITY_INVALID,
    403: UPSTREAM_REJECTED,
    409: UPSTREAM_CONFLICT,
    423: UPSTREAM_LOCKED,
    429: UPSTREAM_RATE_LIMITED,
}


def map_control_status(status_code):
    return _CONTROL_STATUS_MAP.get(status_code)
