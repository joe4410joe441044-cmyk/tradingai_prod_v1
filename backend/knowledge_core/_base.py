"""Deterministic read-only serialization helpers for the Knowledge Core.

The Knowledge Core is INFORMATION AUTHORITY only.  It holds descriptive
registries that point at existing truth (source paths / symbols).  It never
redefines runtime logic and never exposes a mutation surface.

These helpers are internal and enforce deterministic, order-stable output so
that ``stable_json`` for an identical Knowledge Core is byte-for-byte equal
across separate constructions.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

_UNSET = object()


def _skip_field(name: str) -> bool:
    # Internal bookkeeping fields (leading underscore) are not part of the
    # public deterministic contract.
    return name.startswith("_") or name.startswith("__")


def to_plain(value: Any) -> Any:
    """Recursively convert a record graph into JSON-safe plain data.

    Enums collapse to their value.  Tuples and lists become lists.  Mappings
    (including ``MappingProxyType``) become dicts.  Unknown scalars are
    returned unchanged.  Deterministic because order is preserved from the
    caller's sorted tuples.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return to_plain_datetime(value)
    if value is _UNSET:
        return None
    if is_dataclass(value):
        result: dict[str, Any] = {}
        for field in fields(value):
            if _skip_field(field.name):
                continue
            result[field.name] = to_plain(getattr(value, field.name))
        return result
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_plain(item) for item in value]
    return value


def to_plain_datetime(value: datetime) -> str:
    """UTF-8 deterministic serialization of a datetime in UTC.

    Naive datetimes are rejected (never silently interpreted with a local
    timezone); aware datetimes are normalized to UTC and rendered with a ``Z``
    suffix so separate constructions serialize identically.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    """Serialize a Knowledge Core record graph deterministically."""
    return json.dumps(
        to_plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a read-only view over a plain dict of records.

    Consumer mutation attempts raise ``TypeError``.
    """
    from types import MappingProxyType

    return MappingProxyType(dict(value))
