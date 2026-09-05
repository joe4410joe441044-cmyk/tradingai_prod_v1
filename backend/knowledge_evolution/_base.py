"""Deterministic helpers for the D-8 Knowledge Evolution pipeline.

INFORMATION_ONLY.  READ_ONLY.  DETERMINISTIC.  PROVIDER_NEUTRAL.

This module provides pure, standard-library helpers shared by the D-8 record
types.  It never depends on an LLM SDK, never opens a network connection and
never mutates any input.

The helpers here deliberately REUSE the existing D-1/D-7 deterministic
serialization and fingerprinting (``knowledge_core._base.stable_json`` and
``knowledge_core.drift.normalize_value``/``fingerprint_structured``) rather than
introducing a parallel one.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from backend.knowledge_core._base import stable_json
from backend.knowledge_core.drift import fingerprint_structured

_HASH_PREFIX = "sha256:"
_HASH_LEN = 64

# Named truncation bounds.  Every D-8 collection is bounded so an unbounded
# prompt/result is impossible.
MAX_D8_TEXT = 512
MAX_D8_SUMMARY = 256
MAX_D8_TAGS = 12
MAX_D8_SOURCE_REFERENCES = 40
MAX_D8_REASON_CODES = 40
MAX_D8_WARNINGS = 20
MAX_D8_LIMITATIONS = 20
MAX_D8_EVIDENCE_IDS = 200
MAX_D8_COUNTEREVIDENCE_IDS = 200
MAX_D8_PATTERN_IDS = 40
MAX_D8_FINDING_IDS = 40


def deterministic_id(scope: str, *parts: Any) -> str:
    """Derive a stable, deterministic D-8 identifier from ``parts``.

    The identifier is ``f"{scope}:{sha256hex}"`` where the hex digest is
    computed from the D-7 canonical normalization of the ordered parts.  It
    is guaranteed deterministic for identical inputs and never uses a random
    generator.
    """
    if not scope:
        raise ValueError("scope is required")
    digest = fingerprint_structured(list(parts))
    if digest.startswith(_HASH_PREFIX):
        digest = digest[len(_HASH_PREFIX):]
    if len(digest) != _HASH_LEN:
        raise ValueError("unexpected digest length")
    return f"{scope}:{digest}"


def content_hash(*parts: Any) -> str:
    """Return a ``sha256:<hex>`` content digest of the ordered ``parts``.

    Used to record a stable identity/summary hash without storing raw secrets.
    """
    payload = fingerprint_structured(list(parts))
    if not payload.startswith(_HASH_PREFIX):
        payload = _HASH_PREFIX + hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
    return payload


def bound(text: str, limit: int = MAX_D8_TEXT) -> str:
    """Truncate ``text`` to an explicit character bound (never unbounded)."""
    if text is None:
        return ""
    return str(text)[:limit]


def dedupe(items: Iterable[str]) -> tuple[str, ...]:
    """Stable order-preserving de-duplication of boundable strings."""
    seen: dict[str, None] = {}
    for item in items:
        if isinstance(item, str) and item and item not in seen:
            seen[item] = None
    return tuple(seen.keys())


def is_blank(value: str) -> bool:
    return value is None or not str(value).strip()


def clean_tags(tags: Iterable[str], limit: int = MAX_D8_TAGS) -> tuple[str, ...]:
    """Return a bounded, de-duplicated, order-preserving tuple of tags."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = bound(tag, 64).strip()
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
            if len(cleaned) >= limit:
                break
    return tuple(cleaned)


def order_annotations(items: Iterable[str]) -> tuple[str, ...]:
    """Return a sorted, de-duplicated tuple (for deterministic ordering)."""
    return tuple(sorted(dedupe(items)))


__all__ = [
    "MAX_D8_COUNTEREVIDENCE_IDS",
    "MAX_D8_EVIDENCE_IDS",
    "MAX_D8_FINDING_IDS",
    "MAX_D8_LIMITATIONS",
    "MAX_D8_PATTERN_IDS",
    "MAX_D8_REASON_CODES",
    "MAX_D8_SOURCE_REFERENCES",
    "MAX_D8_SUMMARY",
    "MAX_D8_TAGS",
    "MAX_D8_TEXT",
    "MAX_D8_WARNINGS",
    "bound",
    "clean_tags",
    "content_hash",
    "dedupe",
    "deterministic_id",
    "is_blank",
    "order_annotations",
    "stable_json",
]
