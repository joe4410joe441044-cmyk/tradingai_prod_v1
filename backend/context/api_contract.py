"""HTTP contract for the unmounted read-only context router.

These flags describe this phase. They are not evidence that Production is
serving the router or that the live runtime has been read.
"""

from __future__ import annotations

AUTH_REQUIRED = "AUTH_REQUIRED"
AUTH_FAILED = "AUTH_FAILED"
READER_NOT_INJECTED = "READER_NOT_INJECTED"
RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
PAYLOAD_LIMIT_EXCEEDED = "PAYLOAD_LIMIT_EXCEEDED"
CONTEXT_BUILD_FAILED = "CONTEXT_BUILD_FAILED"

# Existing OperatorSessionMiddleware plus require_operator_session.
# Missing, invalid, and expired sessions all surface as HTTP 401.
OPERATOR_AUTH_HTTP_STATUS = 401
OPERATOR_AUTH_BODY_STATUS = "UNAUTHENTICATED"

PAYLOAD_HTTP_STATUS = 413
CONTEXT_FAILURE_HTTP_STATUS = 500

# This phase does not register a public route and does not mount the router.
PUBLIC_ENDPOINT_ENABLED = False
PRODUCTION_API_AVAILABLE = False
PRODUCTION_RUNTIME_CONNECTED = False

OPERATOR_JSON_PATH = "/api/ai-context/operator"
OPERATOR_MARKDOWN_PATH = "/api/ai-context/operator.md"
