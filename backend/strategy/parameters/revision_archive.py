"""Durable canonical parameter revision archive (E-PERF-2).

The canonical :class:`~backend.strategy.parameters.store.StrategyParameterStore`
persists exactly one CONFIGURED and one EFFECTIVE set per scope, overwriting the
previous values on every write/promotion.  That means revision N is lost as soon
as revision N+1 is written or promoted.

This module adds the smallest possible history-preserving layer on top of the
existing store: every promoted revision is additionally persisted under its own
variant (``rev-<effectiveRevision>``) using the *same* atomic, integrity-checked
store.  No new database, no second registry and no new serialization format are
introduced.

Properties:

- deterministic: ``rev-<n>`` is derived from the canonical effectiveRevision;
- append/history preserving: existing revision files are never overwritten by a
  newer revision (different variant filename);
- restart-safe: revisions are reconstructed with a fresh store instance;
- read-only for consumers: :meth:`ParameterRevisionArchive.get` /
  :meth:`history` only read;
- non-authoritative: writing an archive record never changes configured,
  effective or runtime authority.
"""

from __future__ import annotations

from typing import Optional, Union

from .model import ParameterScope, StrategyParameterSet
from .resolver import default_runtime_base_directory
from .store import StoreLoadStatus, StrategyParameterStore

REVISION_VARIANT_PREFIX = "rev-"


def revision_variant(effective_revision: int) -> str:
    """Return the deterministic store variant for one effective revision."""

    if isinstance(effective_revision, bool) or not isinstance(
        effective_revision, int
    ):
        raise TypeError("effectiveRevision must be an int")
    if effective_revision < 0:
        raise ValueError("effectiveRevision must be non-negative")
    return f"{REVISION_VARIANT_PREFIX}{effective_revision}"


def _revision_from_variant(variant: str) -> Optional[int]:
    if not isinstance(variant, str) or not variant.startswith(
        REVISION_VARIANT_PREFIX
    ):
        return None
    raw = variant[len(REVISION_VARIANT_PREFIX):]
    if not raw.isdigit():
        return None
    return int(raw)


class ParameterRevisionArchive:
    """History-preserving view over the canonical parameter store."""

    def __init__(
        self,
        *,
        store: Optional[StrategyParameterStore] = None,
        base_directory=None,
    ):
        if store is None and base_directory is None:
            base_directory = default_runtime_base_directory()
        self._store = store
        self._base_directory = base_directory

    @property
    def store(self) -> StrategyParameterStore:
        if self._store is None:
            self._store = StrategyParameterStore(self._base_directory)
        return self._store

    def record(self, parameter_set: StrategyParameterSet):
        """Persist one promoted revision under its own immutable variant.

        Returns the canonical store save result.  Promotion logic treats a
        non-``SAVED`` result as a fail-closed persistence failure, so a revision
        can never become EFFECTIVE without first being archived.
        """

        if not isinstance(parameter_set, StrategyParameterSet):
            raise TypeError("StrategyParameterSet required")
        return self.store.save(
            parameter_set,
            variant=revision_variant(parameter_set.effectiveRevision),
        )

    def get(
        self,
        scope: Union[ParameterScope, str],
        effective_revision: int,
    ) -> Optional[StrategyParameterSet]:
        """Return the archived set for ``(scope, effectiveRevision)`` or None."""

        try:
            variant = revision_variant(effective_revision)
        except (TypeError, ValueError):
            return None
        try:
            result = self.store.load(scope, variant=variant)
        except Exception:
            return None
        if (
            result is not None
            and result.status is StoreLoadStatus.VALID
            and isinstance(result.parameter_set, StrategyParameterSet)
        ):
            return result.parameter_set
        return None

    def revisions(
        self,
        scope: Union[ParameterScope, str],
    ) -> list:
        """Return archived sets for one scope ordered by effectiveRevision."""

        try:
            resolved = ParameterScope(scope) if not isinstance(
                scope, ParameterScope
            ) else scope
        except ValueError:
            return []
        if resolved not in (ParameterScope.PAPER, ParameterScope.LIVE):
            return []
        found = []
        for variant in self.store.list_variants(resolved):
            revision = _revision_from_variant(variant)
            if revision is None:
                continue
            parameter_set = self.get(resolved, revision)
            if parameter_set is not None:
                found.append(parameter_set)
        return sorted(found, key=lambda item: item.effectiveRevision)

    def history(self, scope: Optional[str] = None) -> list:
        """Return archived revisions for one scope or both scopes."""

        if scope is not None:
            return self.revisions(scope)
        combined = []
        for candidate in (ParameterScope.PAPER, ParameterScope.LIVE):
            combined.extend(self.revisions(candidate))
        return combined


def default_revision_archive() -> ParameterRevisionArchive:
    """Return the archive over the repository runtime parameter directory."""

    return ParameterRevisionArchive()
