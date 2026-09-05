"""Small deterministic helpers shared across Specialist evaluators."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import SourceReference, SpecialistObservation

_OBSERVATION_KEYS = ("code", "severity")


def dedupe_reason_codes(codes: Iterable[str]) -> tuple[str, ...]:
    """Stable, key-preserving deduplication of preserved reason codes."""
    if not codes:
        return ()
    return tuple(dict.fromkeys(codes))


def dedupe_references(refs: Iterable[SourceReference]) -> tuple[SourceReference, ...]:
    """Stable deduplication by subsystem/type/identifier."""
    seen: dict[tuple[str, str, str], SourceReference] = {}
    for ref in refs:
        key = (ref.sourceSubsystem, ref.sourceType, ref.sourceIdentifier)
        seen.setdefault(key, ref)
    return tuple(seen[key] for key in sorted(seen))


def unique_warnings(warnings: Iterable[str]) -> tuple[str, ...]:
    """Stable deduplication of warning labels."""
    if not warnings:
        return ()
    return tuple(dict.fromkeys(warnings))


def merge_observations(
    observations: Iterable[SpecialistObservation],
) -> tuple[SpecialistObservation, ...]:
    """Stable deduplication of findings by code+severity.

    When multiple observations share a code and severity the first (documented,
    most specific) detail is kept; order is preserved.
    """
    seen: set[tuple[str, str]] = set()
    merged: list[SpecialistObservation] = []
    for obs in observations:
        key = (obs.code, obs.severity.value)
        if key in seen:
            continue
        seen.add(key)
        merged.append(obs)
    return tuple(merged)
