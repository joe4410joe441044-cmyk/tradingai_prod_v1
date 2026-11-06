"""Authenticated same-origin HTTP boundary for isolated synthetic PROP evaluation.

The boundary is process-local and session-scoped. It has no credential,
persistence, exchange, runtime, order, or background-task access.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.auth.dependencies import require_operator_session
from backend.prop_trading.offline_workflow import OfflinePropSession, OfflineWorkflowError
from backend.prop_trading.synthetic_feature import prop_isolated_demo_enabled

MAX_REQUEST_BYTES = 32 * 1024
MAX_SYNTHETIC_SESSIONS = 64
DISABLED_RESPONSE = {
    "ok": False,
    "error": {
        "code": "PROP_DEMO_DISABLED",
        "message": "isolated PROP demo is disabled",
        "fields": {},
    },
}


@dataclass
class _Entry:
    workflow: OfflinePropSession
    expires_at: float


class SyntheticPropSessionStore:
    """Bounded in-memory workflow registry keyed by validated session ID."""

    def __init__(self, *, limit: int = MAX_SYNTHETIC_SESSIONS, clock: Callable[[], float] = time.monotonic):
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be positive")
        self._limit = limit
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = RLock()

    def get(self, session_id: str, expires_at: float) -> OfflinePropSession:
        if not session_id or not isinstance(expires_at, (int, float)):
            raise RuntimeError("validated operator session scope is unavailable")
        with self._lock:
            now = self._clock()
            for key in [key for key, entry in self._entries.items() if entry.expires_at <= now]:
                self._entries.pop(key, None)
            entry = self._entries.pop(session_id, None)
            if entry is None:
                entry = _Entry(OfflinePropSession(), float(expires_at))
            else:
                entry.expires_at = float(expires_at)
            self._entries[session_id] = entry
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)
            return entry.workflow

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)


def _safe_error(code: str, message: str, *, status: int, fields: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": {"code": code, "message": message, "fields": fields or {}}},
    )


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == host
        and parsed.scheme == request.url.scheme
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
    )


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON key")
        output[key] = value
    return output


async def _read_json(request: Request) -> Any:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise OfflineWorkflowError("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            parsed_length = int(content_length)
        except ValueError as exc:
            raise OfflineWorkflowError("INVALID_REQUEST", "Content-Length is invalid") from exc
        if parsed_length < 0 or parsed_length > MAX_REQUEST_BYTES:
            raise OfflineWorkflowError("REQUEST_TOO_LARGE", "request body exceeds the allowed size")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            raise OfflineWorkflowError("REQUEST_TOO_LARGE", "request body exceeds the allowed size")
    try:
        text = bytes(body).decode("utf-8", errors="strict")
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OfflineWorkflowError("INVALID_JSON", "request body must be strict UTF-8 JSON") from exc


def _status_for(error: OfflineWorkflowError) -> int:
    if error.code == "REQUEST_TOO_LARGE":
        return 413
    if error.code == "UNSUPPORTED_MEDIA_TYPE":
        return 415
    if error.code == "ACCOUNT_NOT_FOUND":
        return 404
    if error.code == "ACCOUNT_REVISION_MISMATCH":
        return 409
    return 422


def create_prop_synthetic_router(
    *,
    enabled: Callable[[], bool] = prop_isolated_demo_enabled,
    store: SyntheticPropSessionStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/prop-accounts/synthetic", tags=["prop-synthetic"])
    session_store = store or SyntheticPropSessionStore()

    async def execute(request: Request, operation: str) -> JSONResponse:
        if not enabled():
            return JSONResponse(status_code=404, content=DISABLED_RESPONSE)
        if not _same_origin(request):
            return _safe_error("ORIGIN_REJECTED", "same-origin request required", status=403)
        try:
            payload = await _read_json(request)
            scope = request.scope.get("operator_session")
            if not isinstance(scope, dict):
                return _safe_error("UNAUTHENTICATED", "validated operator session required", status=401)
            workflow = session_store.get(scope.get("session_id"), scope.get("expires_at"))
            result = getattr(workflow, operation)(payload)
            return JSONResponse(status_code=200, content={"ok": True, **result})
        except OfflineWorkflowError as error:
            return _safe_error(error.code, error.message, status=_status_for(error), fields=error.fields)
        except RuntimeError:
            return _safe_error("SESSION_SCOPE_UNAVAILABLE", "validated operator session scope is unavailable", status=401)

    @router.post("/accounts")
    async def create_account(request: Request, _identity: str = Depends(require_operator_session)):
        return await execute(request, "create_account")

    @router.post("/accounts/revise")
    async def revise_account(request: Request, _identity: str = Depends(require_operator_session)):
        return await execute(request, "revise_account")

    @router.post("/evaluate")
    async def evaluate(request: Request, _identity: str = Depends(require_operator_session)):
        return await execute(request, "evaluate")

    return router
