"""Canonical parameter settings service (E-PARAM-4).

Thin authority layer used by the operator-facing PARAMETER SETTINGS API.  It
reuses the canonical registry, validation, migration baselines and persistence
store created by E-PARAM-1/2/3.  It never invents a second parameter system and
never mutates trading runtime state: it only validates, checks the optimistic
concurrency revision and persists a complete canonical configuration.

Revision semantics (approved):

- CONFIGURED is the persisted ``StrategyParameterSet`` for a scope.
- On an accepted write the configured revision increments exactly once and the
  new set is marked ``PENDING``.  Promotion to EFFECTIVE is intentionally
  deferred (E-PARAM-5), so a write never falsely reports itself as effective.
- EFFECTIVE is the currently promoted set.  Until E-PARAM-5 promotes a new
  configured revision, it is the previously persisted effective snapshot (or
  the resolved configured/baseline set when no effective snapshot exists yet).

A separate ``effective`` persistence variant is used so the CONFIGURED and
EFFECTIVE parameter maps can differ without a second authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from .baselines import (
    LIVE_BASELINE_EXACT_KEYS,
    LIVE_CLASS_CONSTANT_BASELINE,
    PAPER_MIGRATION_BASELINE,
    materialize_parameter_set,
)
from .model import (
    CANONICAL_SCHEMA_VERSION,
    ParameterScope,
    ParameterSource,
    ParameterStatus,
    StrategyParameterSet,
    format_timestamp,
)
from .promotion_service import (
    ParameterPromotionService,
    PromotionOutcome,
    PromotionResult,
)
from .registry import ParameterTier, StrategyParameterRegistry
from .resolver import default_runtime_base_directory
from .runtime_registry import get_runtime_snapshot
from .store import StoreLoadStatus, StrategyParameterStore
from .validation import validate_parameters

EFFECTIVE_VARIANT = "effective"

_SUPPORTED_SCOPES = (ParameterScope.PAPER, ParameterScope.LIVE)


class UpdateOutcome(str, Enum):
    """Stable outcome of a canonical configuration write."""

    ACCEPTED = "ACCEPTED"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_BODY = "INVALID_BODY"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    LIVE_CONFIRMATION_REQUIRED = "LIVE_CONFIRMATION_REQUIRED"
    LIVE_PARAMETER_NOT_WRITABLE = "LIVE_PARAMETER_NOT_WRITABLE"
    STORE_FAILURE = "STORE_FAILURE"


@dataclass(frozen=True)
class UpdateResult:
    """Result of :meth:`ParameterSettingsService.update_configuration`."""

    outcome: UpdateOutcome
    payload: dict = field(default_factory=dict)


def _coerce_scope(scope: Any) -> ParameterScope:
    if isinstance(scope, ParameterScope):
        resolved = scope
    elif isinstance(scope, str):
        resolved = ParameterScope(scope.strip().upper())
    else:
        raise ValueError("scope must be PAPER or LIVE")
    if resolved not in _SUPPORTED_SCOPES:
        raise ValueError("scope must be PAPER or LIVE")
    return resolved


def _baseline_for(scope: ParameterScope):
    if scope is ParameterScope.PAPER:
        return PAPER_MIGRATION_BASELINE
    return LIVE_CLASS_CONSTANT_BASELINE


class ParameterSettingsService:
    """Read/write authority for the canonical strategy parameter settings."""

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
        self._baseline_cache: dict = {}
        self._promotion: Optional[ParameterPromotionService] = None

    # ------------------------------------------------------------------
    # infrastructure
    # ------------------------------------------------------------------

    @property
    def store(self) -> StrategyParameterStore:
        if self._store is None:
            self._store = StrategyParameterStore(self._base_directory)
        return self._store

    @property
    def promotion(self) -> ParameterPromotionService:
        """The single canonical PENDING -> EFFECTIVE promotion authority."""

        if self._promotion is None:
            self._promotion = ParameterPromotionService(
                store=self.store,
                now=self._now,
            )
        return self._promotion

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

    def _baseline_set(self, scope: ParameterScope) -> StrategyParameterSet:
        cached = self._baseline_cache.get(scope)
        if cached is None:
            cached = materialize_parameter_set(
                _baseline_for(scope),
                configured_revision=1,
                effective_revision=1,
                now=self._captured_at(),
            )
            self._baseline_cache[scope] = cached
        return cached

    def _load_scope(self, scope: ParameterScope, variant: Optional[str] = None):
        try:
            return self.store.load(scope, variant=variant)
        except Exception:
            return None

    def _configured_set(self, scope: ParameterScope) -> StrategyParameterSet:
        result = self._load_scope(scope)
        if (
            result is not None
            and result.status is StoreLoadStatus.VALID
            and isinstance(result.parameter_set, StrategyParameterSet)
            and result.parameter_set.scope is scope
        ):
            return result.parameter_set
        return self._baseline_set(scope)

    def _effective_set(
        self,
        scope: ParameterScope,
        configured: StrategyParameterSet,
    ) -> StrategyParameterSet:
        result = self._load_scope(scope, variant=EFFECTIVE_VARIANT)
        if (
            result is not None
            and result.status is StoreLoadStatus.VALID
            and isinstance(result.parameter_set, StrategyParameterSet)
            and result.parameter_set.scope is scope
        ):
            return result.parameter_set
        return configured

    def _store_status(self, scope: ParameterScope) -> str:
        result = self._load_scope(scope)
        if result is None:
            return "UNAVAILABLE"
        return result.status.value

    def _effective_store_status(self, scope: ParameterScope) -> str:
        result = self._load_scope(scope, variant=EFFECTIVE_VARIANT)
        if result is None:
            return "UNAVAILABLE"
        return result.status.value

    def _authority_status(self, scope: ParameterScope) -> str:
        if self._store_status(scope) == StoreLoadStatus.VALID.value:
            return "PERSISTED"
        if scope is ParameterScope.PAPER:
            return "PAPER_MIGRATION_BASELINE"
        return "LIVE_CLASS_CONSTANT_BASELINE"

    @staticmethod
    def _presentation_status(
        configured: StrategyParameterSet,
        effective: StrategyParameterSet,
    ) -> str:
        # PENDING is observable exactly while the configured revision has not
        # yet been promoted into EFFECTIVE.  Once promoted, the presentation
        # status follows the promoted EFFECTIVE record (ACTIVE) rather than the
        # historical configured record, which intentionally keeps the PENDING
        # status it was written with for audit.
        if configured.configuredRevision > effective.effectiveRevision:
            return ParameterStatus.PENDING.value
        if effective.status is ParameterStatus.ACTIVE:
            return ParameterStatus.ACTIVE.value
        return configured.status.value

    @staticmethod
    def _is_pending(
        configured: StrategyParameterSet,
        effective: StrategyParameterSet,
    ) -> bool:
        return configured.configuredRevision > effective.effectiveRevision

    @staticmethod
    def _parameters_map(parameter_set: StrategyParameterSet) -> dict:
        return {
            name: parameter_set.parameters[name]
            for name in sorted(parameter_set.parameters)
        }

    @staticmethod
    def _warnings(parameter_set: StrategyParameterSet) -> list:
        return list(
            validate_parameters(
                parameter_set.parameters, require_complete=True
            ).warnings
        )

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def schema(self) -> dict:
        parameters = []
        for metadata in StrategyParameterRegistry.PARAMETERS:
            parameters.append(
                {
                    "name": metadata.name,
                    "labelEn": metadata.label_en,
                    "labelJa": metadata.label_ja,
                    "unit": metadata.unit,
                    "minimum": metadata.minimum,
                    "maximum": metadata.maximum,
                    "minimumInclusive": metadata.minimum_inclusive,
                    "maximumInclusive": metadata.maximum_inclusive,
                    "precision": metadata.precision,
                    "valueType": metadata.value_type.value,
                    "scopeApplicability": sorted(
                        scope.value for scope in metadata.scope_applicability
                    ),
                    "couplingGroup": metadata.coupling_group.value,
                    "tier": metadata.tier.value,
                    "primaryAdvanced": (
                        metadata.tier is ParameterTier.PRIMARY
                    ),
                    "editable": bool(metadata.editable),
                    "liveWritable": metadata.name in LIVE_BASELINE_EXACT_KEYS,
                    "description": metadata.description,
                }
            )
        return {
            "schemaVersion": CANONICAL_SCHEMA_VERSION,
            "parameterCount": len(parameters),
            "primaryCount": sum(
                1 for entry in parameters if entry["tier"] == "PRIMARY"
            ),
            "advancedCount": sum(
                1 for entry in parameters if entry["tier"] == "ADVANCED"
            ),
            "parameters": parameters,
        }

    def configuration(self, scope: Any) -> dict:
        resolved = _coerce_scope(scope)
        configured = self._configured_set(resolved)
        effective = self._effective_set(resolved, configured)
        return {
            "parameterSetId": configured.parameterSetId,
            "scope": resolved.value,
            "configuredRevision": configured.configuredRevision,
            "effectiveRevision": effective.effectiveRevision,
            "status": self._presentation_status(configured, effective),
            "pending": self._is_pending(configured, effective),
            "effectiveStatus": effective.status.value,
            "source": configured.source.value,
            "updatedAt": format_timestamp(configured.updatedAt),
            "effectiveFrom": (
                format_timestamp(configured.effectiveFrom)
                if configured.effectiveFrom is not None
                else None
            ),
            "storeStatus": self._store_status(resolved),
            "authorityStatus": self._authority_status(resolved),
            "warnings": [
                _issue_to_dict(issue)
                for issue in self._warnings(configured)
            ],
            "parameters": self._parameters_map(configured),
        }

    def effective(self, scope: Any) -> dict:
        resolved = _coerce_scope(scope)
        configured = self._configured_set(resolved)
        effective = self._effective_set(resolved, configured)
        validation = validate_parameters(
            effective.parameters, require_complete=True
        )
        return {
            "parameterSetId": effective.parameterSetId,
            "scope": resolved.value,
            "configuredRevision": configured.configuredRevision,
            "effectiveRevision": effective.effectiveRevision,
            "status": self._presentation_status(configured, effective),
            "pending": self._is_pending(configured, effective),
            "effectiveStatus": effective.status.value,
            "source": effective.source.value,
            "validation": validation.to_dict(),
            "warnings": [
                _issue_to_dict(issue) for issue in validation.warnings
            ],
            "parameters": self._parameters_map(effective),
        }

    def runtime(self, scope: Any) -> dict:
        resolved = _coerce_scope(scope)
        snapshot = get_runtime_snapshot(resolved.value)
        if not snapshot:
            return {
                "scope": resolved.value,
                "canonicalScope": resolved.value,
                "status": "NO_RUNTIME_SNAPSHOT",
                "runtimeSnapshotAvailable": False,
                "source": None,
                "parameterSetId": None,
                "configuredRevision": None,
                "effectiveRevision": None,
                "featureContract": None,
                "capturedAt": None,
                "parameters": {},
            }
        return {
            "scope": resolved.value,
            "canonicalScope": snapshot.get("canonicalScope", resolved.value),
            "status": "AVAILABLE",
            "runtimeSnapshotAvailable": True,
            "source": snapshot.get("source"),
            "parameterSetId": snapshot.get("parameterSetId"),
            "configuredRevision": snapshot.get("configuredRevision"),
            "effectiveRevision": snapshot.get("effectiveRevision"),
            "featureContract": snapshot.get("featureContract"),
            "capturedAt": snapshot.get("capturedAt"),
            "authorityStatus": snapshot.get("authorityStatus"),
            "storeStatus": snapshot.get("storeStatus"),
            "parameters": dict(snapshot.get("parameters") or {}),
        }

    def status(self) -> dict:
        scopes = {}
        for scope in _SUPPORTED_SCOPES:
            configured = self._configured_set(scope)
            effective = self._effective_set(scope, configured)
            store_status = self._store_status(scope)
            effective_status = self._effective_store_status(scope)
            snapshot = get_runtime_snapshot(scope.value)
            validation = validate_parameters(
                effective.parameters, require_complete=True
            )
            warnings = [
                _issue_to_dict(issue) for issue in validation.warnings
            ]
            errors = [_issue_to_dict(issue) for issue in validation.errors]
            scopes[scope.value] = {
                "scope": scope.value,
                "health": "OK" if not errors else "DEGRADED",
                "storeStatus": store_status,
                "effectiveStoreStatus": effective_status,
                "configuredAvailable": True,
                "effectiveAvailable": True,
                "runtimeSnapshotAvailable": snapshot is not None,
                "fallbackActive": (
                    store_status != StoreLoadStatus.VALID.value
                ),
                "authorityStatus": self._authority_status(scope),
                "source": configured.source.value,
                "status": self._presentation_status(configured, effective),
                "pending": self._is_pending(configured, effective),
                "promotionState": (
                    "PENDING"
                    if self._is_pending(configured, effective)
                    else "EFFECTIVE"
                ),
                "effectiveStatus": effective.status.value,
                "configuredRevision": configured.configuredRevision,
                "effectiveRevision": effective.effectiveRevision,
                "warnings": warnings,
                "errors": errors,
            }
        return {
            "status": "OK",
            "parameterCount": len(StrategyParameterRegistry.PARAMETERS),
            "scopes": scopes,
        }

    # ------------------------------------------------------------------
    # promotion
    # ------------------------------------------------------------------

    def promote_if_safe(
        self,
        scope: Any,
        *,
        safe_to_promote: bool,
        open_position: bool = False,
    ) -> dict:
        """Delegate one safe promotion attempt to the canonical authority.

        This is intentionally a thin pass-through: the promotion logic lives in
        :class:`ParameterPromotionService`.  A successful promotion never
        changes order / bot / runtime authority; it only advances the effective
        parameter revision for the scope.
        """

        try:
            resolved = _coerce_scope(scope)
        except (ValueError, TypeError):
            return PromotionResult(
                outcome=PromotionOutcome.INVALID_SCOPE,
                scope=None,
                promoted=False,
                message="scope must be PAPER or LIVE",
            ).to_dict()
        result = self.promotion.promote_pending(
            resolved,
            safe_to_promote=safe_to_promote,
            open_position=open_position,
        )
        return result.to_dict()

    def pending_state(self, scope: Any) -> dict:
        try:
            resolved = _coerce_scope(scope)
        except (ValueError, TypeError):
            return {"scope": None, "valid": False, "pending": False}
        return self.promotion.pending_state(resolved)

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def update_configuration(
        self,
        *,
        scope: Any,
        parameters: Any,
        expected_revision: Any,
        confirm_live: bool = False,
    ) -> UpdateResult:
        try:
            resolved = _coerce_scope(scope)
        except (ValueError, TypeError):
            return UpdateResult(
                UpdateOutcome.INVALID_SCOPE,
                {
                    "code": "INVALID_SCOPE",
                    "message": "scope must be PAPER or LIVE",
                    "scope": scope,
                },
            )

        if not isinstance(parameters, Mapping):
            return UpdateResult(
                UpdateOutcome.INVALID_BODY,
                {
                    "code": "INVALID_PARAMETERS",
                    "message": "parameters must be an object",
                },
            )
        if isinstance(expected_revision, bool) or not isinstance(
            expected_revision, int
        ):
            return UpdateResult(
                UpdateOutcome.INVALID_BODY,
                {
                    "code": "INVALID_EXPECTED_REVISION",
                    "message": "expectedRevision must be an integer",
                },
            )

        configured = self._configured_set(resolved)
        effective = self._effective_set(resolved, configured)

        if expected_revision != configured.configuredRevision:
            return UpdateResult(
                UpdateOutcome.REVISION_CONFLICT,
                {
                    "code": "REVISION_CONFLICT",
                    "message": (
                        "expectedRevision does not match the current "
                        "configuredRevision"
                    ),
                    "expectedRevision": expected_revision,
                    "configuredRevision": configured.configuredRevision,
                    "effectiveRevision": effective.effectiveRevision,
                    "scope": resolved.value,
                    "configuration": self.configuration(resolved),
                },
            )

        validation = validate_parameters(parameters, require_complete=True)
        if validation.errors:
            return UpdateResult(
                UpdateOutcome.VALIDATION_ERROR,
                {
                    "code": "INVALID_CONFIGURATION",
                    "message": "configuration failed canonical validation",
                    "scope": resolved.value,
                    "validation": validation.to_dict(),
                },
            )

        if resolved is ParameterScope.LIVE:
            if confirm_live is not True:
                return UpdateResult(
                    UpdateOutcome.LIVE_CONFIRMATION_REQUIRED,
                    {
                        "code": "LIVE_CONFIRMATION_REQUIRED",
                        "message": (
                            "LIVE configuration changes require "
                            "confirmLive=true"
                        ),
                        "scope": resolved.value,
                    },
                )
            rejected = self._rejected_live_parameters(parameters, configured)
            if rejected:
                return UpdateResult(
                    UpdateOutcome.LIVE_PARAMETER_NOT_WRITABLE,
                    {
                        "code": "LIVE_UNMIGRATED_PARAMETER_WRITE_REJECTED",
                        "message": (
                            "one or more parameters have no proven canonical "
                            "LIVE runtime consumer and cannot be edited in LIVE"
                        ),
                        "scope": resolved.value,
                        "rejectedParameters": rejected,
                        "liveWritableParameters": sorted(
                            LIVE_BASELINE_EXACT_KEYS
                        ),
                    },
                )

        if not self._ensure_effective_record(resolved, effective):
            return UpdateResult(
                UpdateOutcome.STORE_FAILURE,
                {
                    "code": "EFFECTIVE_SNAPSHOT_PERSIST_FAILED",
                    "message": "could not persist the effective snapshot",
                },
            )

        new_set = StrategyParameterSet(
            parameterSetId=configured.parameterSetId,
            schemaVersion=CANONICAL_SCHEMA_VERSION,
            scope=resolved,
            status=ParameterStatus.PENDING,
            createdAt=configured.createdAt,
            updatedAt=self._captured_at(),
            source=ParameterSource.PARAMETER_SETTINGS,
            parameters=dict(parameters),
            effectiveFrom=None,
            configuredRevision=configured.configuredRevision + 1,
            effectiveRevision=effective.effectiveRevision,
        )
        save_result = self.store.save(new_set)
        if save_result.status.value != "SAVED":
            return UpdateResult(
                UpdateOutcome.STORE_FAILURE,
                {
                    "code": "CONFIGURATION_PERSIST_FAILED",
                    "message": "could not persist the configuration",
                    "failureCode": (
                        save_result.failure_code.value
                        if save_result.failure_code is not None
                        else None
                    ),
                },
            )

        # A successful atomic write is not sufficient if the authority cannot
        # load the same revision/values. Never report a fallback as a saved set.
        persisted = self._load_scope(resolved)
        if (
            persisted is None
            or persisted.status is not StoreLoadStatus.VALID
            or persisted.parameter_set != new_set
        ):
            return UpdateResult(
                UpdateOutcome.STORE_FAILURE,
                {
                    "code": "CONFIGURATION_READBACK_FAILED",
                    "message": "saved configuration could not be verified; reload before retrying",
                },
            )

        accepted_validation = validate_parameters(
            parameters, require_complete=True
        )
        return UpdateResult(
            UpdateOutcome.ACCEPTED,
            {
                "code": "CONFIGURATION_ACCEPTED",
                "message": "configuration accepted",
                "scope": resolved.value,
                "configuredRevision": new_set.configuredRevision,
                "effectiveRevision": new_set.effectiveRevision,
                "status": ParameterStatus.PENDING.value,
                "warnings": [
                    _issue_to_dict(issue)
                    for issue in accepted_validation.warnings
                ],
                "configuration": self.configuration(resolved),
                "effective": self.effective(resolved),
            },
        )

    def _rejected_live_parameters(
        self,
        parameters: Mapping[str, Any],
        effective: StrategyParameterSet,
    ) -> list:
        rejected = []
        for name, value in parameters.items():
            if name in LIVE_BASELINE_EXACT_KEYS:
                continue
            current = effective.parameters.get(name)
            try:
                changed = float(value) != float(current)
            except (TypeError, ValueError):
                changed = True
            if changed:
                rejected.append(name)
        return sorted(rejected)

    def _ensure_effective_record(
        self,
        scope: ParameterScope,
        effective: StrategyParameterSet,
    ) -> bool:
        result = self._load_scope(scope, variant=EFFECTIVE_VARIANT)
        if result is not None and result.status is StoreLoadStatus.VALID:
            return True
        record = StrategyParameterSet(
            parameterSetId=effective.parameterSetId,
            schemaVersion=CANONICAL_SCHEMA_VERSION,
            scope=scope,
            status=ParameterStatus.ACTIVE,
            createdAt=effective.createdAt,
            updatedAt=effective.updatedAt,
            source=effective.source,
            parameters=dict(effective.parameters),
            effectiveFrom=effective.effectiveFrom,
            configuredRevision=effective.effectiveRevision,
            effectiveRevision=effective.effectiveRevision,
        )
        save_result = self.store.save(record, variant=EFFECTIVE_VARIANT)
        return save_result.status.value == "SAVED"


def _issue_to_dict(issue) -> dict:
    return {
        "code": issue.code.value,
        "parameter": issue.parameter,
        "message": issue.message,
    }
