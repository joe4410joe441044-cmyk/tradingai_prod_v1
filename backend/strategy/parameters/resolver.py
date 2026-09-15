"""Canonical parameter resolver and PAPER runtime authority (E-PARAM-2).

This module connects the canonical strategy parameter authority created by
E-PARAM-1 to the PAPER Trading Cycle without changing PAPER behavior.  It adds
the approved CONFIGURED -> EFFECTIVE -> PAPER RUNTIME SNAPSHOT chain:

- CONFIGURED: the persisted canonical :class:`StrategyParameterSet` for the
  PAPER scope, or the named ``PAPER_MIGRATION_BASELINE`` when the store is
  missing/corrupt/unavailable.  The fallback is always explicit and observable.
- EFFECTIVE: the fully validated PAPER set used by the next applicable cycle.
  Because no PARAMETER SETTINGS write API/UI exists yet, EFFECTIVE resolves to
  CONFIGURED (no operator mutation, no revision churn).
- RUNTIME SNAPSHOT: an immutable :class:`RuntimeParameterSnapshot` that carries
  the canonical metadata plus a legacy-compatible ``PAPER_ONLY`` view so the
  existing runtime consumers keep working unchanged.

This task activates PAPER only.  LIVE remains on its current runtime path; the
resolver refuses to fall back to LIVE values and never resolves a LIVE scope.
The resolver is pure with respect to trading logic and does not know about UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from .baselines import PAPER_MIGRATION_BASELINE, materialize_parameter_set
from .model import (
    ParameterScope,
    StrategyParameterSet,
    format_timestamp,
)
from .store import StoreLoadStatus, StrategyParameterStore
from .validation import validate_parameters

# Legacy runtime scope string required by ``parameter_value`` and existing PAPER
# consumers.  The canonical persisted scope remains ``ParameterScope.PAPER``.
PAPER_RUNTIME_SCOPE = "PAPER_ONLY"

# Explicit, strategy-parameter-specific runtime base directory override.  When
# unset the repository's existing runtime convention (``logs/runtime``) is
# reused; no environment-specific absolute path is hardcoded.
STRATEGY_PARAMETERS_DIR_ENV = "STRATEGY_PARAMETERS_DIR"


class RuntimeAuthorityStatus(str, Enum):
    """Observable provenance of the resolved PAPER authority."""

    PERSISTED = "PERSISTED"
    PAPER_MIGRATION_BASELINE = "PAPER_MIGRATION_BASELINE"


def default_runtime_base_directory() -> Path:
    """Return the strategy-parameter runtime base directory.

    Reuses the repository runtime convention (``<repo>/logs/runtime``).  A
    strategy-parameter-specific absolute override may be supplied through the
    ``STRATEGY_PARAMETERS_DIR`` environment variable.
    """

    override = os.environ.get(STRATEGY_PARAMETERS_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "logs" / "runtime"


def _freeze_parameters(
    parameters: Mapping[str, Any],
) -> Mapping[str, float]:
    return MappingProxyType(
        {str(name): float(value) for name, value in parameters.items()}
    )


def _freeze_runtime_parameters(
    parameters: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    return MappingProxyType(
        {
            str(name): MappingProxyType(dict(entry))
            for name, entry in parameters.items()
            if isinstance(entry, Mapping)
        }
    )


@dataclass(frozen=True)
class RuntimeParameterSnapshot:
    """Immutable PAPER runtime parameter snapshot.

    Canonical metadata is preserved alongside the legacy-compatible runtime
    view.  The snapshot is never mutated after creation; ``to_runtime_dict``
    returns fresh copies so a consumer cannot mutate snapshot state.
    """

    schemaVersion: int
    parameterSetId: str
    configuredRevision: int
    effectiveRevision: int
    scope: str
    canonicalScope: str
    source: str
    featureContract: str
    capturedAt: str
    authorityStatus: str
    storeStatus: str
    parameterSetStatus: str
    calibrationId: str
    authority: str
    parameters: Mapping[str, float]
    runtimeParameters: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if isinstance(self.configuredRevision, bool) or not isinstance(
            self.configuredRevision, int
        ):
            raise TypeError("configuredRevision must be an int")
        if isinstance(self.effectiveRevision, bool) or not isinstance(
            self.effectiveRevision, int
        ):
            raise TypeError("effectiveRevision must be an int")
        if self.configuredRevision < 0 or self.effectiveRevision < 0:
            raise ValueError("revisions must be non-negative")
        if self.effectiveRevision > self.configuredRevision:
            raise ValueError(
                "effectiveRevision must not exceed configuredRevision"
            )
        object.__setattr__(
            self, "parameters", _freeze_parameters(self.parameters)
        )
        object.__setattr__(
            self,
            "runtimeParameters",
            _freeze_runtime_parameters(self.runtimeParameters),
        )

    def parameter_value(self, name: str, default: Any = None) -> Any:
        """Return the canonical value, then the legacy value, else ``default``."""

        if name in self.parameters:
            return self.parameters[name]
        entry = self.runtimeParameters.get(name)
        if isinstance(entry, Mapping) and "value" in entry:
            return entry["value"]
        return default

    def to_runtime_dict(self) -> dict:
        """Return the legacy-compatible runtime parameterAuthority mapping.

        The canonical persisted scope is ``PAPER``; this runtime view keeps
        exposing ``scope="PAPER_ONLY"`` (required by ``parameter_value``) and
        additionally carries the canonical metadata needed to prove authority.
        """

        runtime: dict = {
            str(name): dict(entry)
            for name, entry in self.runtimeParameters.items()
        }
        for name, value in self.parameters.items():
            entry = runtime.get(name)
            if entry is None:
                continue
            entry["value"] = value
            runtime[name] = entry
        return {
            "schemaVersion": self.schemaVersion,
            "calibrationId": self.calibrationId,
            "scope": self.scope,
            "authority": self.authority,
            "parameters": runtime,
            "canonicalScope": self.canonicalScope,
            "parameterSetId": self.parameterSetId,
            "configuredRevision": self.configuredRevision,
            "effectiveRevision": self.effectiveRevision,
            "source": self.source,
            "featureContract": self.featureContract,
            "capturedAt": self.capturedAt,
            "authorityStatus": self.authorityStatus,
            "storeStatus": self.storeStatus,
            "parameterSetStatus": self.parameterSetStatus,
        }

    def to_dict(self) -> dict:
        """Deterministic plain-dict observability/status representation."""

        return {
            "schemaVersion": self.schemaVersion,
            "parameterSetId": self.parameterSetId,
            "configuredRevision": self.configuredRevision,
            "effectiveRevision": self.effectiveRevision,
            "scope": self.scope,
            "canonicalScope": self.canonicalScope,
            "source": self.source,
            "featureContract": self.featureContract,
            "capturedAt": self.capturedAt,
            "authorityStatus": self.authorityStatus,
            "storeStatus": self.storeStatus,
            "parameterSetStatus": self.parameterSetStatus,
            "calibrationId": self.calibrationId,
            "authority": self.authority,
            "parameters": {
                name: self.parameters[name]
                for name in sorted(self.parameters)
            },
        }


class CanonicalParameterResolver:
    """Resolve the canonical PAPER authority into an immutable runtime snapshot."""

    def __init__(
        self,
        *,
        store: Optional[StrategyParameterStore] = None,
        base_directory: Optional[Path] = None,
        legacy_calibration: Optional[Mapping[str, Any]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        if store is None and base_directory is None:
            base_directory = default_runtime_base_directory()
        if base_directory is not None and not isinstance(base_directory, Path):
            base_directory = Path(base_directory)
        self._store = store
        self._base_directory = base_directory
        self._legacy_calibration = legacy_calibration
        self._now = now
        self._fallback_parameter_set: Optional[StrategyParameterSet] = None

    @property
    def store(self) -> Optional[StrategyParameterStore]:
        if self._store is None and self._base_directory is not None:
            self._store = StrategyParameterStore(self._base_directory)
        return self._store

    def resolve_paper(self) -> RuntimeParameterSnapshot:
        """Resolve the PAPER CONFIGURED -> EFFECTIVE -> runtime snapshot chain."""

        load_result = self._load_paper()
        if self._is_valid_paper_set(load_result):
            configured = load_result.parameter_set
            authority_status = RuntimeAuthorityStatus.PERSISTED.value
            store_status = StoreLoadStatus.VALID.value
        else:
            configured = self._fallback_configured()
            authority_status = (
                RuntimeAuthorityStatus.PAPER_MIGRATION_BASELINE.value
            )
            store_status = (
                load_result.status.value
                if load_result is not None
                else "UNAVAILABLE"
            )
        effective = self._effective_from(configured)
        return self._build_snapshot(
            effective,
            authority_status=authority_status,
            store_status=store_status,
        )

    def _load_paper(self):
        store = self.store
        if store is None:
            return None
        try:
            return store.load(ParameterScope.PAPER)
        except Exception:
            return None

    @staticmethod
    def _is_valid_paper_set(load_result) -> bool:
        if load_result is None:
            return False
        if load_result.status is not StoreLoadStatus.VALID:
            return False
        parameter_set = load_result.parameter_set
        if not isinstance(parameter_set, StrategyParameterSet):
            return False
        if parameter_set.scope is not ParameterScope.PAPER:
            return False
        return not validate_parameters(
            parameter_set.parameters, require_complete=True
        ).errors

    def _fallback_configured(self) -> StrategyParameterSet:
        if self._fallback_parameter_set is None:
            self._fallback_parameter_set = materialize_parameter_set(
                PAPER_MIGRATION_BASELINE,
                configured_revision=1,
                effective_revision=1,
                now=self._captured_at(),
            )
        return self._fallback_parameter_set

    @staticmethod
    def _effective_from(
        configured: StrategyParameterSet,
    ) -> StrategyParameterSet:
        # No PARAMETER SETTINGS write API/UI exists yet, so the effective set
        # is the validated configured set.  Revisions are preserved exactly;
        # no artificial revision churn is introduced.
        return configured

    def _build_snapshot(
        self,
        effective: StrategyParameterSet,
        *,
        authority_status: str,
        store_status: str,
    ) -> RuntimeParameterSnapshot:
        legacy = self._legacy_calibration
        if not isinstance(legacy, Mapping):
            from backend.strategy.normalized_parameters import (
                PAPER_NORMALIZED_CALIBRATION,
            )

            legacy = PAPER_NORMALIZED_CALIBRATION
        legacy_parameters = legacy.get("parameters") or {}
        runtime_parameters = {
            str(name): dict(entry)
            for name, entry in legacy_parameters.items()
            if isinstance(entry, Mapping)
        }
        return RuntimeParameterSnapshot(
            schemaVersion=int(legacy.get("schemaVersion", 1) or 1),
            parameterSetId=effective.parameterSetId,
            configuredRevision=effective.configuredRevision,
            effectiveRevision=effective.effectiveRevision,
            scope=PAPER_RUNTIME_SCOPE,
            canonicalScope=effective.scope.value,
            source=effective.source.value,
            featureContract=self._feature_contract(legacy_parameters),
            capturedAt=format_timestamp(self._captured_at()),
            authorityStatus=authority_status,
            storeStatus=store_status,
            parameterSetStatus=effective.status.value,
            calibrationId=str(legacy.get("calibrationId") or ""),
            authority=str(legacy.get("authority") or ""),
            parameters=dict(effective.parameters),
            runtimeParameters=runtime_parameters,
        )

    @staticmethod
    def _feature_contract(legacy_parameters: Mapping[str, Any]) -> str:
        entry = legacy_parameters.get("strategyFeatureCalibrationId")
        if isinstance(entry, Mapping):
            value = entry.get("value")
            if value:
                return str(value)
        return "LEGACY_CALLBACK_WINDOW"

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
