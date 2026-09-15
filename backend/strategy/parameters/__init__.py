"""Canonical strategy parameter authority.

This package is the single canonical authority for strategy parameter values.
E-PARAM-1 added the pure model, registry, validation, migration baselines and
persistence store.  E-PARAM-2 adds the resolver/runtime snapshot that connects
the PAPER scope to the Trading Cycle without changing PAPER behavior.  LIVE
remains on its legacy runtime path.
"""

from .baselines import (
    LIVE_BASELINE_EXACT_KEYS,
    LIVE_BASELINE_IMPERFECT_MAPPING_KEYS,
    LIVE_BASELINE_NON_EQUIVALENT_KEYS,
    LIVE_CLASS_CONSTANT_BASELINE,
    PAPER_MIGRATION_BASELINE,
    MigrationBaseline,
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
from .registry import (
    CouplingGroup,
    ParameterMetadata,
    ParameterTier,
    StrategyParameterRegistry,
    ValueType,
)
from .resolver import (
    LIVE_FEATURE_CONTRACT,
    LIVE_RUNTIME_SCOPE,
    PAPER_RUNTIME_SCOPE,
    STRATEGY_PARAMETERS_DIR_ENV,
    CanonicalParameterResolver,
    RuntimeAuthorityStatus,
    RuntimeParameterSnapshot,
    default_runtime_base_directory,
)
from .store import (
    ENVELOPE_VERSION,
    INTEGRITY_ALGORITHM,
    MAX_FILE_SIZE,
    STORAGE_SUBDIRECTORY,
    StoreFailureCode,
    StoreLoadResult,
    StoreLoadStatus,
    StoreSaveResult,
    StoreSaveStatus,
    StrategyParameterStore,
    serialize_parameter_envelope,
)
from .validation import (
    ValidationCode,
    ValidationIssue,
    ValidationResult,
    validate_parameters,
)

__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "CouplingGroup",
    "CanonicalParameterResolver",
    "ENVELOPE_VERSION",
    "INTEGRITY_ALGORITHM",
    "LIVE_BASELINE_EXACT_KEYS",
    "LIVE_BASELINE_IMPERFECT_MAPPING_KEYS",
    "LIVE_BASELINE_NON_EQUIVALENT_KEYS",
    "LIVE_CLASS_CONSTANT_BASELINE",
    "LIVE_FEATURE_CONTRACT",
    "LIVE_RUNTIME_SCOPE",
    "MAX_FILE_SIZE",
    "MigrationBaseline",
    "PAPER_MIGRATION_BASELINE",
    "PAPER_RUNTIME_SCOPE",
    "ParameterMetadata",
    "ParameterScope",
    "ParameterSource",
    "ParameterStatus",
    "ParameterTier",
    "RuntimeAuthorityStatus",
    "RuntimeParameterSnapshot",
    "STORAGE_SUBDIRECTORY",
    "STRATEGY_PARAMETERS_DIR_ENV",
    "StoreFailureCode",
    "StoreLoadResult",
    "StoreLoadStatus",
    "StoreSaveResult",
    "StoreSaveStatus",
    "StrategyParameterRegistry",
    "StrategyParameterSet",
    "StrategyParameterStore",
    "ValidationCode",
    "ValidationIssue",
    "ValidationResult",
    "ValueType",
    "default_runtime_base_directory",
    "format_timestamp",
    "materialize_parameter_set",
    "serialize_parameter_envelope",
    "validate_parameters",
]
