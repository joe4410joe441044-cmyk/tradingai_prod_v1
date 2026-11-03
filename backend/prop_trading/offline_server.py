"""Loopback-only HTTP adapter for the CC-4A offline synthetic workflow."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from .offline_workflow import OfflinePropSession, OfflineWorkflowError


HOST = "127.0.0.1"
PORT = 4188
PREVIEW_ORIGIN = "http://127.0.0.1:4187"
MAX_BODY_BYTES = 32_768
BODY_READ_TIMEOUT_SECONDS = 1.0
_ROUTES = {
    "/offline/accounts": "create_account",
    "/offline/accounts/revise": "revise_account",
    "/offline/evaluate": "evaluate",
}


def _reject_duplicate_keys(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def make_handler(session: OfflinePropSession, *, preview_origin: str = PREVIEW_ORIGIN):
    class OfflineHandler(BaseHTTPRequestHandler):
        server_version = "TradingAI-CC4A-Offline/1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(BODY_READ_TIMEOUT_SECONDS)

        def send_error(self, _code: int, _message: str | None = None, _explain: str | None = None) -> None:
            self._reject(405, "METHOD_NOT_ALLOWED", "only documented offline methods are allowed")

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", preview_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _reject(self, status: int, code: str, message: str) -> None:
            self._send(status, {"ok": False, "error": {"code": code, "message": message, "fields": {}}})

        def _allowed_context(self) -> bool:
            host = self.headers.get("Host")
            origin = self.headers.get("Origin")
            return host in {f"{HOST}:{self.server.server_port}", f"localhost:{self.server.server_port}"} and origin == preview_origin

        def do_OPTIONS(self) -> None:  # noqa: N802
            if self.path not in _ROUTES or not self._allowed_context():
                self._reject(403, "REQUEST_CONTEXT_REJECTED", "request context is not allowed")
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", preview_origin)
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "300")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in _ROUTES:
                self._reject(404, "NOT_FOUND", "offline endpoint not found")
                return
            if not self._allowed_context():
                self._reject(403, "REQUEST_CONTEXT_REJECTED", "request context is not allowed")
                return
            if self.headers.get_content_type() != "application/json":
                self._reject(415, "JSON_REQUIRED", "Content-Type must be application/json")
                return
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "")
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self._reject(413, "PAYLOAD_TOO_LARGE", "request body exceeds the offline limit")
                return
            try:
                raw = self.rfile.read(length)
            except TimeoutError:
                self._reject(408, "BODY_READ_TIMEOUT", "request body was not received in time")
                return
            if len(raw) != length:
                self._reject(400, "INCOMPLETE_BODY", "request body length does not match Content-Length")
                return
            try:
                request = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self._reject(400, "INVALID_JSON", "request body must be valid JSON")
                return
            try:
                result = getattr(session, _ROUTES[self.path])(request)
            except OfflineWorkflowError as exc:
                status = 409 if exc.code in {"ACCOUNT_NOT_FOUND", "ACCOUNT_REVISION_MISMATCH"} else 400
                self._send(status, {"ok": False, "error": exc.to_dict()})
                return
            except Exception:
                self._reject(500, "OFFLINE_EVALUATION_FAILED", "offline evaluation failed safely")
                return
            self._send(200, {"ok": True, **result})

    return OfflineHandler


def create_server(*, session: OfflinePropSession | None = None, port: int = PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), make_handler(session or OfflinePropSession()))
