"""Typed, side-effect-free inputs for Supervisor snapshot construction."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping


@dataclass(frozen=True)
class SnapshotSource:
    """A producer payload supplied by composition code; never fetched here."""

    payload: Mapping[str, object] | None

    def __post_init__(self) -> None:
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise TypeError("snapshot source payload must be a mapping or None")


@dataclass(frozen=True)
class SnapshotFreshnessPolicy:
    """Caller-owned thresholds. No age threshold is selected by Supervisor."""

    maximumAgeBySource: tuple[tuple[str, timedelta], ...]
    futureTolerance: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.futureTolerance < timedelta(0):
            raise ValueError("futureTolerance must be non-negative")
        names: set[str] = set()
        for name, maximum_age in self.maximumAgeBySource:
            if name not in {"bot", "governance", "moneyManagement", "health"}:
                raise ValueError("unknown freshness policy source")
            if name in names:
                raise ValueError("duplicate freshness policy source")
            if maximum_age < timedelta(0):
                raise ValueError("maximumAge must be non-negative")
            names.add(name)

    def maximum_age(self, source: str) -> timedelta | None:
        return dict(self.maximumAgeBySource).get(source)
