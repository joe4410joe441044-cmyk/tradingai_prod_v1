"""Minimal Bybit V5 GET signing and canonical query construction.

Only the GET/HMAC-SHA256 form documented by Bybit is implemented.  Query pairs
are encoded once with RFC3986 percent-encoding and kept in the exact order the
caller supplied; duplicate keys are rejected.  The same encoded string is used
for both the signature and the transmitted request, so there is no second
encoding step.

References (checked 2026-10-31 JST):
- https://bybit-exchange.github.io/docs/v5/guide (authentication / GET string)
- https://bybit-exchange.github.io/docs/v5/demo (demo host)
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
from typing import Iterable, Tuple
from urllib.parse import quote, quote_from_bytes, unquote_to_bytes

from backend.execution.read_only_transport import ReadOnlyClock


MIN_RECV_WINDOW_MS = 1_000
MAX_RECV_WINDOW_MS = 60_000
DEFAULT_RECV_WINDOW_MS = 5_000

_ALLOWED_QUERY_SAFE = "-_.~"
_PRE_ENCODED_TOKEN = re.compile(r"(?:[A-Za-z0-9\-_.~]|%[0-9A-Fa-f]{2})+")
# Bybit returns ``nextPageCursor`` already URL-encoded (for example
# ``page_args%3D...%26symbol%3D6%26``).  Treat only this key as an opaque
# pre-encoded token so it is not double-encoded; reject raw delimiters rather
# than guessing.  The token is canonicalised once, before signing, to the exact
# form ``requests`` will send (uppercase percent hex, ``%7E`` -> ``~``), so the
# signed and transmitted query bytes agree.
_PRE_ENCODED_KEYS = frozenset({"cursor"})


class SigningError(ValueError):
    """Stable signing validation failure; no secret or signature is included."""


def percent_encode(value: str) -> str:
    if not isinstance(value, str):
        raise SigningError("query component must be text")
    return quote(value, safe=_ALLOWED_QUERY_SAFE, encoding="utf-8", errors="strict")


def canonicalize_pre_encoded_token(value: str) -> str:
    """Return the canonical transmitted form of a pre-encoded query token.

    The input must consist only of unreserved ASCII characters and ``%HH``
    triplets.  It is decoded exactly once and re-encoded exactly once.  This is
    deterministic and matches ``requests`` URL normalisation: lowercase hex is
    uppercased and an encoded unreserved byte such as ``%7E`` becomes ``~``.
    Malformed input fails closed instead of being guessed.
    """

    if not isinstance(value, str) or not value:
        raise SigningError("pre-encoded query value is malformed")
    if _PRE_ENCODED_TOKEN.fullmatch(value) is None:
        raise SigningError("pre-encoded query value is malformed")
    try:
        raw = unquote_to_bytes(value)
    except Exception:
        raise SigningError("pre-encoded query value is malformed") from None
    return quote_from_bytes(raw, safe=b"-_.~")


def _query_from_url(url: str) -> str:
    if not isinstance(url, str):
        raise SigningError("prepared url must be text")
    if "?" not in url:
        return ""
    return url.split("?", 1)[1]


def require_prepared_query_matches(signed_query: str, prepared_url: str) -> None:
    """Fail closed unless the prepared URL carries the signed query verbatim.

    This is a pure guard used by an offline test or a future sender.  It does not
    perform I/O and does not normalise the prepared URL; the caller must pass the
    exact URL string that would be transmitted.
    """

    if not isinstance(signed_query, str):
        raise SigningError("signed query must be text")
    sent_query = _query_from_url(prepared_url)
    if sent_query != signed_query:
        raise SigningError("signed and transmitted query bytes do not match")


def canonical_query(
    pairs: Iterable[Tuple[str, str]],
    *,
    pre_encoded_keys: frozenset[str] = _PRE_ENCODED_KEYS,
) -> str:
    """Encode ordered ``(key, value)`` pairs exactly once.

    Ordering is preserved (not sorted) so the signature input and the transmitted
    query can be byte-for-byte identical.  Duplicate keys are rejected rather
    than merged or resolved by precedence.  Values whose key is in
    ``pre_encoded_keys`` must already be canonical encoded tokens and are used
    verbatim; they are never encoded a second time.
    """

    if not isinstance(pre_encoded_keys, frozenset) or not pre_encoded_keys <= set(_PRE_ENCODED_KEYS):
        raise SigningError("pre-encoded query keys are not allowed")
    try:
        entries = tuple(pairs)
    except TypeError as exc:
        raise SigningError("query parameters must be iterable") from exc
    seen: set[str] = set()
    encoded: list[str] = []
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise SigningError("query entries must be (key, value) tuples")
        key, value = entry
        if not isinstance(key, str) or not isinstance(value, str):
            raise SigningError("query keys and values must be text")
        if not key:
            raise SigningError("query keys must be non-empty")
        if key in seen:
            raise SigningError("query keys must not repeat")
        seen.add(key)
        if key in pre_encoded_keys:
            encoded_value = canonicalize_pre_encoded_token(value)
        else:
            encoded_value = percent_encode(value)
        encoded.append(f"{percent_encode(key)}={encoded_value}")
    return "&".join(encoded)


def validate_recv_window(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SigningError("recv_window must be an integer number of milliseconds")
    if not MIN_RECV_WINDOW_MS <= value <= MAX_RECV_WINDOW_MS:
        raise SigningError("recv_window is outside the supported range")
    return value


def utc_timestamp_ms(clock: ReadOnlyClock) -> int:
    if clock is None or not callable(getattr(clock, "now", None)):
        raise SigningError("an explicit clock is required")
    value = clock.now()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SigningError("clock must return a timezone-aware datetime")
    utc = value.astimezone(timezone.utc)
    return int(utc.timestamp() * 1000)


def sign_get(
    *,
    api_secret: str,
    api_key: str,
    timestamp_ms: int,
    recv_window_ms: int,
    encoded_query: str,
) -> str:
    """HMAC-SHA256 over ``timestamp + api_key + recv_window + queryString``."""

    if not isinstance(api_secret, str) or not api_secret:
        raise SigningError("api secret is missing")
    if not isinstance(api_key, str) or not api_key:
        raise SigningError("api key is missing")
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
        raise SigningError("timestamp must be a nonnegative integer")
    window = validate_recv_window(recv_window_ms)
    if not isinstance(encoded_query, str):
        raise SigningError("encoded query must be text")

    message = f"{timestamp_ms}{api_key}{window}{encoded_query}"
    digest = hmac.new(
        api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return digest
