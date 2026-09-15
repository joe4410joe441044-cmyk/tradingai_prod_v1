"""Canonical strategy parameter authority (E-PARAM-1 foundation).

This package is the single canonical authority for strategy parameter values.
E-PARAM-1 adds the pure model, registry, validation, migration baselines and
persistence store only.  No Trading Cycle consumer reads this package yet; the
runtime consumer wiring belongs to E-PARAM-2 / E-PARAM-3.
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
    "ENVELOPE_VERSION",
    "INTEGRITY_ALGORITHM",
    "LIVE_BASELINE_EXACT_KEYS",
    "LIVE_BASELINE_IMPERFECT_MAPPING_KEYS",
    "LIVE_BASELINE_NON_EQUIVALENT_KEYS",
    "LIVE_CLASS_CONSTANT_BASELINE",
    "MAX_FILE_SIZE",
    "MigrationBaseline",
    "PAPER_MIGRATION_BASELINE",
    "ParameterMetadata",
    "ParameterScope",
    "ParameterSource",
    "ParameterStatus",
    "ParameterTier",
    "STORAGE_SUBDIRECTORY",
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
    "format_timestamp",
    "materialize_parameter_set",
    "serialize_parameter_envelope",
    "validate_parameters",
]
