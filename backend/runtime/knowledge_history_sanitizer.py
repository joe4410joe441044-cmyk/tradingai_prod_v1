"""Secret redaction/rejection for the shared knowledge/history query layer.

The policy is *reused*, never re-invented:

* secret-like mapping *keys* and the summary size cap come from the canonical
  :func:`backend.runtime.trading_trace.sanitize_metadata` scrubber;
* secret-like *text* (embedded ``token=...``, bearer tokens, URLs with
  credentials, private keys) is scrubbed by the Advisor redactor
  :func:`backend.ai_advisor.context_builder.sanitize_text`;
* secret-like *paths* are detected with
  :func:`backend.runtime.cycle_evidence.secret_fields`.

This module reads and writes nothing and has no authority.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from backend.ai_advisor.context_builder import sanitize_text
from backend.runtime.cycle_evidence import secret_fields
from backend.runtime.knowledge_history_models import KnowledgeHistorySecretError
from backend.runtime.trading_trace import sanitize_metadata


def _sanitize_string(value: str) -> str:
    if not value:
        return value
    if "\x00" in value:
        return "[REMOVED:INVALID]"
    try:
        result = sanitize_text(value)
    except ValueError:
        return value
    return result.value


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def sanitize_summary(value: Any) -> tuple[dict, bool]:
    """Return ``(sanitized_summary, redacted)`` for a small mapping.

    The result is bounded: the canonical scrubber replaces an oversized summary
    with a size sentinel.  Secret-like keys are dropped and secret-like text is
    redacted; the removed values are never retained.
    """

    if value is None:
        return {}, False
    if not isinstance(value, Mapping):
        value = {"value": value}
    cleaned = sanitize_metadata(dict(value))
    if cleaned.get("truncated") is True and set(cleaned) <= {"truncated", "originalBytes"}:
        return cleaned, True
    scrubbed = _sanitize_strings(cleaned)
    return scrubbed, scrubbed != cleaned


def _sanitize_strings(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {str(key): _sanitize_strings(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_strings(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def assert_query_safe(value: Any) -> None:
    """Reject a query carrying secret-like keys or secret-like filter text.

    Raises :class:`KnowledgeHistorySecretError`; the offending values are never
    echoed back.
    """

    paths = secret_fields(value) if isinstance(value, (Mapping, list, tuple)) else []
    if paths:
        raise KnowledgeHistorySecretError(
            "QUERY_CONTAINS_SECRET_FIELD",
            "query contains secret-like fields that must be rejected",
        )
    for text in _iter_strings(value):
        try:
            result = sanitize_text(text)
        except ValueError:
            raise KnowledgeHistorySecretError(
                "QUERY_TEXT_INVALID",
                "query contains an invalid text value that must be rejected",
            )
        if result.sensitiveRemoved:
            raise KnowledgeHistorySecretError(
                "QUERY_CONTAINS_SECRET_TEXT",
                "query contains secret-like text that must be rejected",
            )


def redact_links(links: Mapping[str, Any]) -> tuple[dict, bool]:
    """Return a sanitized links mapping (secret keys dropped, text scrubbed)."""

    cleaned, redacted = sanitize_summary(links or {})
    return cleaned, redacted
