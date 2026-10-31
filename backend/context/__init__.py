"""Canonical AI Context Sharing foundation (Phase 1).

READ-ONLY: this package never mutates source, runtime, orders, or Production.
"""

from .builder import RuntimeTruthSource, build_canonical_context
from .context_views import (
    build_operator_context_view,
    build_public_context_view,
    view_to_json,
    view_to_markdown,
)
from .runtime_collector import collect_runtime_context, collect_tradingai_context
from .runtime_composer import compose_tradingai_context
from .injection_boundary import inject_verified_runtime_snapshots
from .snapshot_copy import copy_injection_inputs, copy_json_snapshot
from .runtime_reader_adapter import collect_verified_runtime_context
from .runtime_truth import read_position_truth, read_runtime_sections
from .project_truth import DEFAULT_REGISTRY_PATH, load_project_truth
from .schema import (
    PROJECT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    AcceptedTestRecord,
    AcceptedTestsSection,
    Availability,
    CanonicalContext,
    ContextObservation,
    ContractRecord,
    ContractsSection,
    FieldObservation,
    Freshness,
    FreshnessSummary,
    GeneratorInfo,
    IssueStatus,
    KnownIssueRecord,
    KnownIssuesSection,
    ProjectTruth,
    ProvenanceEntry,
    ProvenanceSummary,
    SafetyContext,
    SectionMeta,
    SourceTruth,
    TestStatus,
    ValueState,
    VerificationState,
    WorkstreamRecord,
    WorkstreamsSection,
    WorkstreamStatus,
)
from .serializer import context_to_dict, to_canonical_json, to_markdown
from .source_truth import read_source_truth

__all__ = [
    "PROJECT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "AcceptedTestRecord",
    "AcceptedTestsSection",
    "Availability",
    "CanonicalContext",
    "ContextObservation",
    "ContractRecord",
    "ContractsSection",
    "DEFAULT_REGISTRY_PATH",
    "FieldObservation",
    "Freshness",
    "FreshnessSummary",
    "GeneratorInfo",
    "IssueStatus",
    "KnownIssueRecord",
    "KnownIssuesSection",
    "ProjectTruth",
    "ProvenanceEntry",
    "ProvenanceSummary",
    "RuntimeTruthSource",
    "SafetyContext",
    "SectionMeta",
    "SourceTruth",
    "TestStatus",
    "ValueState",
    "VerificationState",
    "WorkstreamRecord",
    "WorkstreamsSection",
    "WorkstreamStatus",
    "build_canonical_context",
    "build_operator_context_view",
    "build_public_context_view",
    "collect_runtime_context",
    "collect_tradingai_context",
    "collect_verified_runtime_context",
    "compose_tradingai_context",
    "copy_injection_inputs",
    "copy_json_snapshot",
    "inject_verified_runtime_snapshots",
    "read_position_truth",
    "read_runtime_sections",
    "context_to_dict",
    "load_project_truth",
    "read_source_truth",
    "to_canonical_json",
    "to_markdown",
    "view_to_json",
    "view_to_markdown",
]
