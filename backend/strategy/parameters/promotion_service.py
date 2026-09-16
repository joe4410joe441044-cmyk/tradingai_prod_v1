"""Canonical PENDING -> EFFECTIVE promotion authority (E-PARAM-5).

E-PARAM-4 accepted operator writes as a new ``CONFIGURED`` revision marked
``PENDING`` while the previous ``EFFECTIVE`` revision stayed active.  This
module is the single backend authority that performs the safe promotion
boundary:

    CONFIGURED -> PENDING -> EFFECTIVE -> RUNTIME SNAPSHOT -> TRADE

Design constraints (approved):

- Exactly one authority owns the promotion transition.  API, frontend,
  MicrostructureStateBuilder, MicrostructureEdgeStrategy and ExecutionRuntime
  never promote; the runtime only supplies the *safety signal* (stopped /
  running-flat / open-position).
- Promotion is fail-closed: a validation, persistence, corruption or revision
  inconsistency failure leaves the current EFFECTIVE authority untouched.
- Promotion is scope-isolated: a PAPER pending revision can never promote LIVE
  and vice versa.
- Promotion never increments a revision on reads, validation failures, auth
  failures or repeated checks with no pending revision (no revision churn).
- Historical configured revision metadata is preserved for audit.  The
  promoted EFFECTIVE record is persisted atomically with the canonical
  :class:`~backend.strategy.parameters.store.StrategyParameterStore`.

The service is pure with respect to trading logic: it never changes order,
leverage, quantity, symbol, mode or bot lifecycle authority.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from .model import (
    CANONICAL_SCHEMA_VERSION,
    ParameterScope,
    ParameterStatus,
    StrategyParameterSet,
)
from .resolver import default_runtime_base_directory
from .store import StoreLoadStatus, StrategyParameterStore
from .validation import validate_parameters

EFFECTIVE_VARIANT = "effective"

_SUPPORTED_SCOPES = (ParameterScope.PAPER, ParameterScope.LIVE)


class PromotionOutcome(str, Enum):
    """Stable outcome of one safe promotion attempt."""

    PROMOTED = "PROMOTED"
    NO_PENDING = "NO_PENDING"
    DEFERRED_OPEN_POSITION = "DEFERRED_OPEN_POSITION"
    DEFERRED_NOT_SAFE = "DEFERRED_NOT_SAFE"
    INVALID_SCOPE = "INVALID_SCOPE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    REVISION_INCONSISTENCY = "REVISION_INCONSISTENCY"


@dataclass(frozen=True)
class PromotionResult:
    """Result of :meth:`ParameterPromotionService.promote_pending`."""

    outcome: PromotionOutcome
    scope: Optional[str]
    promoted: bool
    configured_revision: Optional[int] = None
    previous_effective_revision: Optional[int] = None
    effective_revision: Optional[int] = None
    message: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "scope": self.scope,
            "promoted": self.promoted,
            "configuredRevision": self.configured_revision,
            "previousEffectiveRevision": self.previous_effective_revision,
            "effectiveRevision": self.effective_revision,
            "message": self.message,
            "details": dict(self.details),
        }


def _coerce_scope(scope) -> ParameterScope:
    if isinstance(scope, ParameterScope):
        resolved = scope
    elif isinstance(scope, str):
        resolved = ParameterScope(scope.strip().upper())
    else:
        raise ValueError("scope must be PAPER or LIVE")
    if resolved not in _SUPPORTED_SCOPES:
        raise ValueError("scope must be PAPER or LIVE")
    return resolved


class ParameterPromotionService:
    """Single authority for the safe PENDING -> EFFECTIVE transition."""

    def __init__(
        self,
        *,
        store: Optional[StrategyParameterStore] = None,
        base_directory: Optional[Path] = None,
        now=None,
    ):
        if store is None and base_directory is None:
            base_directory = default_runtime_base_directory()
        if base_directory is not None and not isinstance(base_directory, Path):
            base_directory = Path(base_directory)
        self._store = store
        self._base_directory = base_directory
        self._now = now
        self._lock = threading.Lock()
        self._last_result: Optional[PromotionResult] = None

    @property
    def store(self) -> StrategyParameterStore:
        if self._store is None:
            self._store = StrategyParameterStore(self._base_directory)
        return self._store

    @property
    def last_result(self) -> Optional[PromotionResult]:
        return self._last_result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _captured_at(self) -> datetime:
        if callable(self._now):
            moment = self._now()
        elif isinstance(self._now, datetime):
            moment = self._now
        else:
            moment = datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)

    def _load(self, scope: ParameterScope, variant=None):
        try:
            return self.store.load(scope, variant=variant)
        except Exception:
            return None

    def pending_state(self, scope) -> dict:
        """Return the observable pending/effective state without mutating."""

        try:
            resolved = _coerce_scope(scope)
        except (ValueError, TypeError):
            return {
                "scope": None,
                "valid": False,
                "pending": False,
                "reason": "INVALID_SCOPE",
            }
        configured = self._load(resolved)
        configured_valid = self._valid_scope_set(configured, resolved)
        effective = self._load(resolved, variant=EFFECTIVE_VARIANT)
        effective_valid = self._valid_scope_set(effective, resolved)
        configured_revision = (
            configured.parameter_set.configuredRevision
            if configured_valid
            else None
        )
        effective_revision = (
            effective.parameter_set.effectiveRevision
            if effective_valid
            else None
        )
        pending = bool(
            configured_valid
            and configured.parameter_set.status is ParameterStatus.PENDING
            and (
                effective_revision is None
                or configured_revision > effective_revision
            )
        )
        return {
            "scope": resolved.value,
            "valid": configured_valid,
            "pending": pending,
            "configuredRevision": configured_revision,
            "effectiveRevision": effective_revision,
            "configuredStatus": (
                configured.parameter_set.status.value
                if configured_valid
                else None
            ),
            "effectiveStatus": (
                effective.parameter_set.status.value
                if effective_valid
                else None
            ),
        }

    @staticmethod
    def _valid_scope_set(load_result, scope: ParameterScope) -> bool:
        if load_result is None:
            return False
        if load_result.status is not StoreLoadStatus.VALID:
            return False
        parameter_set = load_result.parameter_set
        if not isinstance(parameter_set, StrategyParameterSet):
            return False
        return parameter_set.scope is scope

    def _record(self, result: PromotionResult) -> PromotionResult:
        self._last_result = result
        return result

    # ------------------------------------------------------------------
    # promotion
    # ------------------------------------------------------------------

    def promote_pending(
        self,
        scope,
        *,
        safe_to_promote: bool,
        open_position: bool = False,
    ) -> PromotionResult:
        """Attempt the safe PENDING -> EFFECTIVE promotion for one scope.

        ``open_position`` is the critical invariant: while a position is open
        the pending revision is deferred so the open trade keeps the revision
        it was entered with.  ``safe_to_promote`` is the runtime lifecycle
        signal (bot stopped, or running and flat).
        """

        try:
            resolved = _coerce_scope(scope)
        except (ValueError, TypeError):
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.INVALID_SCOPE,
                    scope=None,
                    promoted=False,
                    message="scope must be PAPER or LIVE",
                )
            )

        with self._lock:
            return self._promote_locked(
                resolved,
                safe_to_promote=bool(safe_to_promote),
                open_position=bool(open_position),
            )

    def _promote_locked(
        self,
        scope: ParameterScope,
        *,
        safe_to_promote: bool,
        open_position: bool,
    ) -> PromotionResult:
        configured_load = self._load(scope)
        if configured_load is None or (
            configured_load.status is not StoreLoadStatus.VALID
        ):
            if configured_load is not None and configured_load.status in (
                StoreLoadStatus.CORRUPT,
                StoreLoadStatus.INVALID,
            ):
                return self._record(
                    PromotionResult(
                        outcome=PromotionOutcome.REVISION_INCONSISTENCY,
                        scope=scope.value,
                        promoted=False,
                        message=(
                            "persisted configured revision is corrupt; "
                            "effective authority is unchanged"
                        ),
                        details={"storeStatus": configured_load.status.value},
                    )
                )
            # No persisted configured revision: the named baseline is already
            # effective, so there is nothing to promote.
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.NO_PENDING,
                    scope=scope.value,
                    promoted=False,
                    message="no persisted configured revision",
                )
            )

        configured = configured_load.parameter_set
        if not self._valid_scope_set(configured_load, scope):
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.REVISION_INCONSISTENCY,
                    scope=scope.value,
                    promoted=False,
                    message="configured revision scope mismatch",
                )
            )

        effective_load = self._load(scope, variant=EFFECTIVE_VARIANT)
        effective_valid = self._valid_scope_set(effective_load, scope)
        effective = effective_load.parameter_set if effective_valid else None
        previous_effective_revision = (
            effective.effectiveRevision if effective is not None else None
        )

        configured_revision = configured.configuredRevision

        if configured.status is not ParameterStatus.PENDING:
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.NO_PENDING,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message="configured revision is not pending",
                )
            )

        if (
            previous_effective_revision is not None
            and previous_effective_revision >= configured_revision
        ):
            if previous_effective_revision == configured_revision:
                return self._record(
                    PromotionResult(
                        outcome=PromotionOutcome.NO_PENDING,
                        scope=scope.value,
                        promoted=False,
                        configured_revision=configured_revision,
                        previous_effective_revision=previous_effective_revision,
                        effective_revision=previous_effective_revision,
                        message="pending revision already promoted",
                    )
                )
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.REVISION_INCONSISTENCY,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message=(
                        "effectiveRevision exceeds configuredRevision; "
                        "effective authority is unchanged"
                    ),
                )
            )

        if open_position:
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.DEFERRED_OPEN_POSITION,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message=(
                        "open position continues with its entry revision; "
                        "promotion deferred to the next safe flat boundary"
                    ),
                )
            )

        if not safe_to_promote:
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.DEFERRED_NOT_SAFE,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message="no safe decision boundary reached yet",
                )
            )

        validation = validate_parameters(
            configured.parameters, require_complete=True
        )
        if validation.errors:
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.VALIDATION_FAILURE,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message=(
                        "pending configuration failed canonical validation; "
                        "effective authority is unchanged"
                    ),
                    details={"validation": validation.to_dict()},
                )
            )

        moment = self._captured_at()
        try:
            promoted = StrategyParameterSet(
                parameterSetId=configured.parameterSetId,
                schemaVersion=CANONICAL_SCHEMA_VERSION,
                scope=scope,
                status=ParameterStatus.ACTIVE,
                createdAt=configured.createdAt,
                updatedAt=moment,
                source=configured.source,
                parameters=dict(configured.parameters),
                effectiveFrom=moment,
                configuredRevision=configured_revision,
                effectiveRevision=configured_revision,
            )
        except (ValueError, TypeError) as exc:
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.VALIDATION_FAILURE,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message="promoted revision failed construction",
                    details={"error": str(exc)},
                )
            )

        save_result = self.store.save(promoted, variant=EFFECTIVE_VARIANT)
        if save_result.status.value != "SAVED":
            return self._record(
                PromotionResult(
                    outcome=PromotionOutcome.PERSISTENCE_FAILURE,
                    scope=scope.value,
                    promoted=False,
                    configured_revision=configured_revision,
                    previous_effective_revision=previous_effective_revision,
                    effective_revision=previous_effective_revision,
                    message=(
                        "could not persist the promoted effective revision; "
                        "effective authority is unchanged"
                    ),
                    details={
                        "failureCode": (
                            save_result.failure_code.value
                            if save_result.failure_code is not None
                            else None
                        )
                    },
                )
            )

        return self._record(
            PromotionResult(
                outcome=PromotionOutcome.PROMOTED,
                scope=scope.value,
                promoted=True,
                configured_revision=configured_revision,
                previous_effective_revision=previous_effective_revision,
                effective_revision=configured_revision,
                message="pending revision promoted to effective",
                details={"effectiveFrom": promoted.effectiveFrom.isoformat()},
            )
        )
