"""BC-8 isolated integration and acceptance harness for the Knowledge Hub.

Importing this package performs no scan, no Git call, no network access, no
database write, and no scheduler registration. Everything here is opt-in and
operates only on caller-supplied paths.
"""

from .integration_models import (
    CONDITIONAL_READY,
    NOT_READY,
    READINESS_UNKNOWN,
    READY_FOR_APPROVAL,
    STAGE_FAILED,
    STAGE_OK,
    STAGE_SKIPPED,
    VERDICT_BLOCKED,
    VERDICT_PARTIAL,
    VERDICT_PASS,
    CanonicalReconciliation,
    DeploymentReadiness,
    HashMismatchClassification,
    HashMismatchEntry,
    IntegrationConfig,
    IntegrationResult,
    ReconciliationEntry,
    StageResult,
)
from .integration_runner import run_isolated_integration
from .acceptance import classify_hash_mismatch, evaluate_acceptance
from .readiness import (
    assess_deployment_readiness,
    reconcile_with_canonical,
    production_dirty_state,
)
from .handoff import render_handoff, write_handoff


__all__ = [
    "CONDITIONAL_READY",
    "NOT_READY",
    "READINESS_UNKNOWN",
    "READY_FOR_APPROVAL",
    "STAGE_FAILED",
    "STAGE_OK",
    "STAGE_SKIPPED",
    "VERDICT_BLOCKED",
    "VERDICT_PARTIAL",
    "VERDICT_PASS",
    "CanonicalReconciliation",
    "DeploymentReadiness",
    "HashMismatchClassification",
    "HashMismatchEntry",
    "IntegrationConfig",
    "IntegrationResult",
    "ReconciliationEntry",
    "StageResult",
    "assess_deployment_readiness",
    "classify_hash_mismatch",
    "evaluate_acceptance",
    "production_dirty_state",
    "reconcile_with_canonical",
    "render_handoff",
    "run_isolated_integration",
    "write_handoff",
]
