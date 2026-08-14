from http.cookies import SimpleCookie

from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.operator_session import (
    COOKIE_NAME,
    OperatorSessionManager,
)


class OperatorSessionMiddleware:
    def __init__(
        self,
        app,
        session_manager: OperatorSessionManager,
        config: OperatorAuthConfig,
    ):
        self.app = app
        self._manager = session_manager
        self._config = config

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        operator_session = self._extract_session(scope)
        if operator_session is not None:
            scope["operator_session"] = {
                "identity": operator_session.identity,
                "session_id": operator_session.session_id,
                "created_at": operator_session.created_at,
                "expires_at": operator_session.expires_at,
            }

        await self.app(scope, receive, send)

    def _extract_session(self, scope):
        headers = dict(scope.get("headers", ()))
        cookie_header = None
        for name, value in headers.items():
            if name.lower() == b"cookie":
                cookie_header = value.decode("latin-1", errors="replace")
                break

        if not cookie_header:
            return None

        cookie = SimpleCookie()
        cookie.load(cookie_header)
        signed = cookie.get(COOKIE_NAME)
        if not signed or not signed.value:
            return None

        session_id = self._manager.unsign(signed.value)
        if not session_id:
            return None

        return self._manager.validate_session(session_id)
