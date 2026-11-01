"""Offline-first Bybit Demo V5 HTTP sender.

The sender is an explicit, injected object.  Importing the module or constructing
the sender never opens a socket; only an explicit ``send``/``get_public`` call can
do that, and only when the caller has explicitly enabled connectivity.  The
default is a disabled gate, so importing or wiring the class by accident cannot
start network traffic.

Implemented with the already-installed ``requests`` dependency.  The URL is built
from a fixed demo host plus the canonical, already-signed query string; the
``params`` argument is never used, so the bytes that were signed are the bytes
that are sent.  A pure prepared-request guard re-checks scheme/host/path/query
and the four authentication headers immediately before ``Session.send``.

Limitations recorded deliberately:
- ``requests``/``urllib3`` lower-level blocking calls cannot always be
  interrupted; the queue-inclusive total deadline is checked before and after a
  blocking call and between streamed chunks, not inside the socket call.  It is
  therefore a best-effort deadline, not a hard wall-clock interrupt guarantee.
- A ``Content-Length`` header is only a hint and is never trusted on its own.
- Compressed bodies are decoded by ``requests`` before the size cap is applied,
  so the cap applies to the decoded size (the compressed hint is also checked
  when present).
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

from backend.execution.bybit_server_time import BYBIT_SERVER_TIME_PATH
from backend.execution.bybit_v5_signed_transport import (
    SAFE_RESPONSE_HEADER_ALLOWLIST,
    HttpSenderError,
    HttpSenderFailureKind,
    HttpSenderResponse,
    SignedReadRequest,
)
from backend.execution.bybit_v5_signing import SigningError, require_prepared_query_matches
from backend.execution.read_only_policy import BYBIT_DEMO_HOST


_AUTH_HEADER_NAMES = frozenset(
    {"x-bapi-api-key", "x-bapi-timestamp", "x-bapi-recv-window", "x-bapi-sign"}
)
_AUTOMATIC_REQUEST_HEADER_ALLOWLIST = frozenset(
    {"accept", "accept-encoding", "connection", "user-agent"}
)
_ALLOWED_PUBLIC_PATHS = frozenset({BYBIT_SERVER_TIME_PATH})
_FORBIDDEN_PATH_TOKENS = ("://", "?", "#", "\\", "..", "%")
_MAX_SAFE_HEADER_VALUE = 256


def _fixed_sender_rejected() -> HttpSenderError:
    return HttpSenderError(HttpSenderFailureKind.SENDER_REJECTED)


class BybitDemoHttpSender:
    """Fixed-host, GET-only, redirect/proxy-free sender for the demo profile.

    The instance is not registered anywhere and is never constructed implicitly
    by an adapter.  ``allow_network`` must be explicitly set to ``True`` before
    any request can leave the process.  Tests inject a fake ``session`` and keep
    ``allow_network=True`` while a socket guard proves no real network is used.
    """

    def __init__(
        self,
        *,
        connect_timeout: float = 3.0,
        read_timeout: float = 5.0,
        total_timeout: float = 10.0,
        max_response_bytes: int = 1_000_000,
        session: Optional[object] = None,
        ca_bundle: Optional[str] = None,
        allow_network: bool = False,
        max_concurrency: int = 1,
        clock: Optional[Callable[[], datetime]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        chunk_size: int = 65536,
    ) -> None:
        for name, value in (
            ("connect_timeout", connect_timeout),
            ("read_timeout", read_timeout),
            ("total_timeout", total_timeout),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not 0 < float(value) <= 30.0:
                raise ValueError(f"{name} must be in (0, 30]")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int):
            raise ValueError("max_response_bytes must be an integer")
        if not 1 <= max_response_bytes <= 10_000_000:
            raise ValueError("max_response_bytes must be in [1, 10000000]")
        if type(allow_network) is not bool:
            raise TypeError("allow_network must be bool")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise ValueError("max_concurrency must be an integer")
        if not 1 <= max_concurrency <= 16:
            raise ValueError("max_concurrency must be in [1, 16]")
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise ValueError("chunk_size must be an integer")
        if not 1024 <= chunk_size <= 1_048_576:
            raise ValueError("chunk_size must be in [1024, 1048576]")
        if ca_bundle is not None and not isinstance(ca_bundle, str):
            raise ValueError("ca_bundle must be a path string or None")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")
        if monotonic is not None and not callable(monotonic):
            raise TypeError("monotonic must be callable or None")

        self._connect_timeout = float(connect_timeout)
        self._read_timeout = float(read_timeout)
        self._total_timeout = float(total_timeout)
        self._max_response_bytes = max_response_bytes
        self._allow_network = allow_network
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._chunk_size = chunk_size
        self._verify = ca_bundle if ca_bundle is not None else True
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._lock = threading.Lock()
        self._closed = False

        if session is None:
            session = requests.Session()
            self._configure_session(session, mount_adapters=True)
        else:
            self._configure_session(session, mount_adapters=False)
        self._session = session

    @staticmethod
    def _configure_session(session: object, *, mount_adapters: bool) -> None:
        # Disable ambient configuration: no proxy env, no .netrc read, no
        # inherited authorization, no cookies.
        try:
            session.trust_env = False
        except Exception:
            pass
        try:
            session.proxies = {}
        except Exception:
            pass
        try:
            session.auth = None
        except Exception:
            pass
        headers = getattr(session, "headers", None)
        if headers is not None and hasattr(headers, "pop"):
            try:
                headers.pop("Authorization", None)
                headers.pop("Cookie", None)
            except Exception:
                pass
        cookies = getattr(session, "cookies", None)
        if cookies is not None and hasattr(cookies, "clear"):
            try:
                cookies.clear()
            except Exception:
                pass
        if mount_adapters:
            # Explicitly disable hidden urllib3 retries.
            adapter = requests.adapters.HTTPAdapter(max_retries=0)
            for prefix in ("https://", "http://"):
                try:
                    session.mount(prefix, adapter)
                except Exception:
                    pass

    @property
    def enabled(self) -> bool:
        return self._allow_network and not self._closed

    @property
    def max_response_bytes(self) -> int:
        return self._max_response_bytes

    def __repr__(self) -> str:
        return (
            "BybitDemoHttpSender("
            f"enabled={self.enabled!r}, host={BYBIT_DEMO_HOST!r}, "
            f"max_response_bytes={self._max_response_bytes!r})"
        )

    def __enter__(self) -> "BybitDemoHttpSender":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        session = self._session
        closer = getattr(session, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    # -- request construction -------------------------------------------------

    def _deadline(self, request: SignedReadRequest) -> float:
        return min(self._total_timeout, float(request.timeout_seconds))

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            value = datetime.now(timezone.utc)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            return datetime.now(timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_path(path: object) -> str:
        if not isinstance(path, str) or not path:
            raise _fixed_sender_rejected()
        if not path.startswith("/v5/"):
            raise _fixed_sender_rejected()
        if any(token in path for token in _FORBIDDEN_PATH_TOKENS):
            raise _fixed_sender_rejected()
        if any(ord(char) > 126 or ord(char) < 33 for char in path):
            raise _fixed_sender_rejected()
        return path

    def _verify_prepared(self, request: SignedReadRequest, prepared: object) -> None:
        method = getattr(prepared, "method", None)
        if method != "GET" or method != request.method:
            raise _fixed_sender_rejected()
        url = getattr(prepared, "url", None)
        if not isinstance(url, str):
            raise _fixed_sender_rejected()
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise _fixed_sender_rejected()
        if parts.hostname != BYBIT_DEMO_HOST:
            raise _fixed_sender_rejected()
        if parts.port is not None:
            raise _fixed_sender_rejected()
        if parts.username is not None or parts.password is not None:
            raise _fixed_sender_rejected()
        if parts.fragment:
            raise _fixed_sender_rejected()
        if parts.path != request.path:
            raise _fixed_sender_rejected()
        try:
            require_prepared_query_matches(request.query, url)
        except SigningError:
            raise _fixed_sender_rejected() from None

        headers = getattr(prepared, "headers", None)
        if headers is None or not hasattr(headers, "items"):
            raise _fixed_sender_rejected()
        normalized: dict[str, object] = {}
        for name, value in headers.items():
            if not isinstance(name, str):
                raise _fixed_sender_rejected()
            normalized[name.lower()] = value
        if "authorization" in normalized or "cookie" in normalized:
            raise _fixed_sender_rejected()
        expected: dict[str, str] = {}
        for name, value in request.headers:
            lowered = name.lower()
            if lowered in expected:
                raise _fixed_sender_rejected()
            expected[lowered] = value
        for name in _AUTH_HEADER_NAMES:
            if normalized.get(name) != expected.get(name):
                raise _fixed_sender_rejected()
        for name in expected:
            if name not in _AUTH_HEADER_NAMES and normalized.get(name) != expected[name]:
                raise _fixed_sender_rejected()
        allowed = _AUTOMATIC_REQUEST_HEADER_ALLOWLIST | frozenset(expected)
        if not set(normalized) <= allowed:
            raise _fixed_sender_rejected()

    def _prepare(self, url: str, headers: dict[str, str]) -> object:
        prepared_headers = None
        if headers:
            prepared_headers = dict(headers)
        request = requests.Request(method="GET", url=url, headers=prepared_headers)
        preparer = getattr(self._session, "prepare_request", None)
        if callable(preparer):
            return preparer(request)
        return request.prepare()

    # -- response handling ----------------------------------------------------

    @staticmethod
    def _header_value(headers: object, name: str) -> Optional[str]:
        if headers is None:
            return None
        getter = getattr(headers, "get", None)
        if callable(getter):
            try:
                value = getter(name)
            except Exception:
                value = None
            if isinstance(value, str):
                return value
        items = getattr(headers, "items", None)
        if callable(items):
            try:
                for key, value in items():
                    if isinstance(key, str) and key.lower() == name.lower():
                        return value if isinstance(value, str) else None
            except Exception:
                return None
        return None

    def _safe_headers(self, headers: object) -> tuple[tuple[str, str], ...]:
        out: list[tuple[str, str]] = []
        for name in sorted(SAFE_RESPONSE_HEADER_ALLOWLIST):
            value = self._header_value(headers, name)
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text or len(text) > _MAX_SAFE_HEADER_VALUE:
                continue
            if any(ord(char) < 32 or ord(char) > 126 for char in text):
                continue
            out.append((name, text))
        return tuple(out)

    def _content_length(self, headers: object) -> Optional[int]:
        raw = self._header_value(headers, "Content-Length")
        if raw is None:
            return None
        text = raw.strip()
        if not text.isdigit():
            return None
        try:
            value = int(text)
        except ValueError:
            return None
        return value if value >= 0 else None

    def _map_exception(self, exc: BaseException) -> HttpSenderError:
        if isinstance(exc, requests.exceptions.Timeout):
            return HttpSenderError(HttpSenderFailureKind.TIMEOUT)
        if isinstance(exc, requests.exceptions.SSLError):
            return HttpSenderError(HttpSenderFailureKind.TLS_FAILED)
        if isinstance(exc, requests.exceptions.ProxyError):
            return HttpSenderError(HttpSenderFailureKind.PROXY_FAILED)
        if isinstance(exc, requests.exceptions.ConnectionError):
            return HttpSenderError(HttpSenderFailureKind.CONNECTION_FAILED)
        return HttpSenderError(HttpSenderFailureKind.CONNECTION_FAILED)

    def _read_streamed(
        self,
        response: object,
        *,
        started_at: float,
        deadline: float,
        cap: int,
    ) -> bytes:
        iter_content = getattr(response, "iter_content", None)
        if not callable(iter_content):
            raise HttpSenderError(HttpSenderFailureKind.INVALID_RESPONSE)
        body = bytearray()
        try:
            for chunk in iter_content(chunk_size=self._chunk_size):
                if self._monotonic() - started_at > deadline:
                    raise HttpSenderError(HttpSenderFailureKind.TIMEOUT)
                if not isinstance(chunk, (bytes, bytearray)):
                    raise HttpSenderError(HttpSenderFailureKind.INVALID_RESPONSE)
                if chunk:
                    body.extend(chunk)
                    if len(body) > cap:
                        raise HttpSenderError(HttpSenderFailureKind.RESPONSE_TOO_LARGE)
        except HttpSenderError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from None
        return bytes(body)

    def _remaining(self, *, started_at: float, deadline: float) -> float:
        try:
            remaining = deadline - (float(self._monotonic()) - started_at)
        except Exception:
            raise HttpSenderError(HttpSenderFailureKind.TIMEOUT) from None
        if remaining <= 0:
            raise HttpSenderError(HttpSenderFailureKind.TIMEOUT)
        return remaining

    def _execute(
        self,
        *,
        path: str,
        query: str,
        headers: dict[str, str],
        max_response_bytes: int,
        require_query_match: bool,
        request: Optional[SignedReadRequest] = None,
    ) -> HttpSenderResponse:
        if not self.enabled:
            raise _fixed_sender_rejected()
        try:
            started_at = float(self._monotonic())
        except Exception:
            raise HttpSenderError(HttpSenderFailureKind.TIMEOUT) from None
        path = self._validate_path(path)
        if require_query_match and request is None:
            raise _fixed_sender_rejected()

        cap = min(max_response_bytes, self._max_response_bytes)
        url = f"https://{BYBIT_DEMO_HOST}{path}"
        if query:
            url = f"{url}?{query}"

        deadline = (
            self._deadline(request) if request is not None else self._total_timeout
        )
        remaining = self._remaining(started_at=started_at, deadline=deadline)
        try:
            acquired = self._semaphore.acquire(timeout=remaining)
        except Exception:
            raise HttpSenderError(HttpSenderFailureKind.TIMEOUT) from None
        if not acquired:
            raise HttpSenderError(HttpSenderFailureKind.TIMEOUT)
        response = None
        try:
            remaining = self._remaining(started_at=started_at, deadline=deadline)
            prepared = self._prepare(url, headers)
            if require_query_match:
                self._verify_prepared(request, prepared)
            else:
                self._verify_public_prepared(path, prepared)
            remaining = self._remaining(started_at=started_at, deadline=deadline)
            connect_timeout = min(self._connect_timeout, remaining)
            read_timeout = min(self._read_timeout, remaining)
            try:
                response = self._session.send(
                    prepared,
                    allow_redirects=False,
                    timeout=(connect_timeout, read_timeout),
                    stream=True,
                    verify=self._verify,
                    proxies={},
                    cert=None,
                )
            except Exception as exc:
                raise self._map_exception(exc) from None

            try:
                status_code = getattr(response, "status_code", None)
                if isinstance(status_code, bool) or not isinstance(status_code, int):
                    raise HttpSenderError(HttpSenderFailureKind.INVALID_RESPONSE)
                if not 100 <= status_code <= 599:
                    raise HttpSenderError(HttpSenderFailureKind.INVALID_RESPONSE)
                self._remaining(started_at=started_at, deadline=deadline)

                response_headers = getattr(response, "headers", None)
                content_length = self._content_length(response_headers)
                if content_length is not None and content_length > cap:
                    raise HttpSenderError(HttpSenderFailureKind.RESPONSE_TOO_LARGE)

                body = self._read_streamed(
                    response, started_at=started_at, deadline=deadline, cap=cap
                )
                self._remaining(started_at=started_at, deadline=deadline)
                safe_headers = self._safe_headers(response_headers)
                received_at = self._now()
            finally:
                closer = getattr(response, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        pass
            self._remaining(started_at=started_at, deadline=deadline)
        finally:
            self._semaphore.release()
        return HttpSenderResponse(
            status_code=status_code,
            body=body,
            received_at=received_at,
            headers=safe_headers,
        )

    def _verify_public_prepared(self, path: str, prepared: object) -> None:
        method = getattr(prepared, "method", None)
        if method != "GET":
            raise _fixed_sender_rejected()
        url = getattr(prepared, "url", None)
        if not isinstance(url, str):
            raise _fixed_sender_rejected()
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise _fixed_sender_rejected()
        if parts.hostname != BYBIT_DEMO_HOST:
            raise _fixed_sender_rejected()
        if parts.port is not None:
            raise _fixed_sender_rejected()
        if parts.username is not None or parts.password is not None:
            raise _fixed_sender_rejected()
        if parts.fragment or parts.query:
            raise _fixed_sender_rejected()
        if parts.path != path:
            raise _fixed_sender_rejected()
        headers = getattr(prepared, "headers", None)
        if headers is None or not hasattr(headers, "items"):
            raise _fixed_sender_rejected()
        normalized: set[str] = set()
        for name, _value in headers.items():
            if not isinstance(name, str):
                raise _fixed_sender_rejected()
            normalized.add(name.lower())
        if not normalized <= _AUTOMATIC_REQUEST_HEADER_ALLOWLIST:
            raise _fixed_sender_rejected()

    # -- public API -----------------------------------------------------------

    def send(self, request: SignedReadRequest) -> HttpSenderResponse:
        if not isinstance(request, SignedReadRequest):
            raise _fixed_sender_rejected()
        if request.method != "GET":
            raise _fixed_sender_rejected()
        if request.host != BYBIT_DEMO_HOST:
            raise _fixed_sender_rejected()
        if request.allow_redirects is not False or request.allow_proxy is not False:
            raise _fixed_sender_rejected()
        if not 0 < float(request.timeout_seconds) <= 30:
            raise _fixed_sender_rejected()
        if not 1 <= int(request.max_response_bytes) <= 10_000_000:
            raise _fixed_sender_rejected()
        self._validate_path(request.path)
        return self._execute(
            path=request.path,
            query=request.query,
            headers=request.header_dict(),
            max_response_bytes=request.max_response_bytes,
            require_query_match=True,
            request=request,
        )

    def get_public(self, path: str) -> HttpSenderResponse:
        """Unauthenticated GET restricted to the fixed server-time endpoint."""

        if not isinstance(path, str) or path not in _ALLOWED_PUBLIC_PATHS:
            raise _fixed_sender_rejected()
        return self._execute(
            path=path,
            query="",
            headers={},
            max_response_bytes=self._max_response_bytes,
            require_query_match=False,
            request=None,
        )
