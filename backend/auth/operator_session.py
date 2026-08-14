import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field


SESSION_ID_BYTES = 32
COOKIE_NAME = "tradingai_session"


@dataclass(frozen=True)
class OperatorSession:
    session_id: str
    identity: str
    created_at: float
    expires_at: float


@dataclass
class _SessionEntry:
    identity: str
    created_at: float
    expires_at: float


class OperatorSessionManager:
    def __init__(self, session_secret: str, session_ttl_seconds: int = 28800):
        if not session_secret or len(session_secret) < 16:
            raise ValueError("session_secret must be at least 16 characters")
        self._secret = session_secret.encode("utf-8")
        self._ttl = session_ttl_seconds
        self._store: dict[str, _SessionEntry] = {}
        self._lock = threading.Lock()
        self._clock = time.monotonic

    def create_session(self, identity: str) -> OperatorSession:
        session_id = secrets.token_hex(SESSION_ID_BYTES)
        now = self._clock()
        entry = _SessionEntry(
            identity=identity,
            created_at=now,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._store[session_id] = entry
            self._evict_expired()
        return OperatorSession(
            session_id=session_id,
            identity=identity,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
        )

    def validate_session(self, session_id: str) -> OperatorSession | None:
        now = self._clock()
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._store[session_id]
                return None
            if entry.expires_at - now < (self._ttl / 2):
                entry.expires_at = now + self._ttl
            return OperatorSession(
                session_id=session_id,
                identity=entry.identity,
                created_at=entry.created_at,
                expires_at=entry.expires_at,
            )

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def sign(self, session_id: str) -> str:
        digest = hmac.digest(
            self._secret,
            session_id.encode("ascii"),
            hashlib.sha256,
        )
        return f"{session_id}.{digest.hex()}"

    def unsign(self, signed: str) -> str | None:
        if "." not in signed:
            return None
        session_id, _, sig_hex = signed.rpartition(".")
        if not session_id or not sig_hex:
            return None
        expected = hmac.digest(
            self._secret,
            session_id.encode("ascii"),
            hashlib.sha256,
        )
        try:
            provided = bytes.fromhex(sig_hex)
        except ValueError:
            return None
        if not hmac.compare_digest(expected, provided):
            return None
        return session_id

    def _evict_expired(self):
        now = self._clock()
        expired = [
            sid for sid, entry in self._store.items()
            if entry.expires_at <= now
        ]
        for sid in expired:
            del self._store[sid]

    @property
    def active_sessions(self) -> int:
        with self._lock:
            self._evict_expired()
            return len(self._store)
