import secrets
from http.cookies import SimpleCookie
from typing import Callable

CSRF_TOKEN_COOKIE = "tradingai_csrf"
CSRF_TOKEN_HEADER = "X-TradingAI-CSRF"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_TOKEN_BYTES = 32


def generate_csrf_token() -> str:
    return secrets.token_hex(CSRF_TOKEN_BYTES)


class OperatorCsrfProtection:
    def __init__(self, app, csrf_required_paths: frozenset[str] | None = None):
        self.app = app
        self._protected = csrf_required_paths or frozenset()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = (scope.get("method", "GET") or "GET").upper()
        path = scope.get("path", "") or ""

        if method in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        if self._protected and path not in self._protected:
            await self.app(scope, receive, send)
            return

        if not self._protected:
            await self.app(scope, receive, send)
            return

        if not self._validate_csrf(scope):
            await self._forbidden(send)
            return

        await self.app(scope, receive, send)

    def _validate_csrf(self, scope) -> bool:
        headers = dict(scope.get("headers", ()))
        cookie_header = None
        for name, value in headers.items():
            if name.lower() == b"cookie":
                cookie_header = value.decode("latin-1", errors="replace")
                break
        if not cookie_header:
            return False

        cookie = SimpleCookie()
        cookie.load(cookie_header)
        csrf_cookie = cookie.get(CSRF_TOKEN_COOKIE)
        if not csrf_cookie or not csrf_cookie.value:
            return False

        header_value = None
        for name, value in headers.items():
            if name.lower() == CSRF_TOKEN_HEADER.lower().encode("latin-1"):
                header_value = value.decode("latin-1", errors="replace")
                break

        if not header_value:
            return False

        return secrets.compare_digest(csrf_cookie.value, header_value)

    @staticmethod
    async def _forbidden(send):
        body = b'{"status":"UNAUTHENTICATED"}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })
