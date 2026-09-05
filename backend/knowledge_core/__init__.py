"""TradingAI Knowledge Core: deterministic, READ-ONLY shared knowledge foundation.

The Knowledge Core is INFORMATION AUTHORITY only.  It describes existing truth
(System Map, Component Registry, Source Index, Runtime Semantics, Reason Code
Catalog and Knowledge Provenance).  It exposes no execution action, no
mutation surface, and no runtime authority of any kind.

Dependency direction (never reversed):
    knowledge_core
       ^        ^
   Advisor   Supervisor
"""

from __future__ import annotations

from .authority import (
    AuthorityClass,
    KnowledgeAuthority,
    SourceCategory,
    TruthLevel,
    TRUTH_PRIORITY,
)
from .provenance import ProvenanceRecord
from .domain import DOMAIN_RECORDS, Domain, DomainRecord
from .component_registry import (
    COMPONENT_RECORDS,
    ComponentRecord,
    ComponentRegistry,
)
from .system_map import DomainComponentIndex, SystemMap, default_system_map
from .source_index import SOURCE_INDEX_RECORDS, SourceIndex, SourceIndexRecord
from .runtime_semantics import RUNTIME_SEMANTICS, RuntimeSemantic, RuntimeSemanticsRegistry
from .reason_codes import (
    REASON_CODE_RECORDS,
    UNKNOWN,
    ReasonCodeCatalog,
    ReasonCodeRecord,
)
from .core import (
    KnowledgeCore,
    KnowledgeAuthorityReport,
    build_default_knowledge_core,
    mutation_interface_names,
)
from .canonical_loader import (
    AUTHORITY_PRIORITY,
    CanonicalKnowledgeAuthority,
    CanonicalKnowledgeDocument,
    CanonicalKnowledgeEntry,
    CanonicalKnowledgeLoadError,
    CanonicalKnowledgeLoader,
    CanonicalKnowledgeLoadResult,
    CanonicalKnowledgeManifest,
    VerificationState,
    default_repository_root,
    load_canonical_knowledge,
    production_canonical_knowledge_manifest,
    sha256_digest,
)
from .drift import (
    D7_REASON_CODES,
    DRIFT_STATUS_RANK,
    AUTHORITY_CONFLICT,
    EVIDENCE_STALE,
    PROVENANCE_FINGERPRINT_MISMATCH,
    PROVENANCE_SOURCE_MISSING,
    PROVENANCE_UNKNOWN,
    PROVENANCE_VERSION_MISMATCH,
    DriftAssessment,
    DriftFinding,
    DriftStatus,
    SourceKind,
    TemporalScope,
    assess_authority_conflict,
    assess_provenance,
    build_conflicting_assessment,
    fingerprint_bytes,
    fingerprint_fields,
    fingerprint_structured,
    merge_status,
    normalize_value,
    provenance_from_advisor,
    provenance_from_knowledge,
    provenance_from_specialist,
    provenance_from_trace,
)

__all__ = [
    "KnowledgeCore",
    "KnowledgeAuthorityReport",
    "build_default_knowledge_core",
    "mutation_interface_names",
    "AuthorityClass",
    "KnowledgeAuthority",
    "SourceCategory",
    "TruthLevel",
    "TRUTH_PRIORITY",
    "ProvenanceRecord",
    "DOMAIN_RECORDS",
    "Domain",
    "DomainRecord",
    "COMPONENT_RECORDS",
    "ComponentRecord",
    "ComponentRegistry",
    "DomainComponentIndex",
    "SystemMap",
    "default_system_map",
    "SOURCE_INDEX_RECORDS",
    "SourceIndex",
    "SourceIndexRecord",
    "RUNTIME_SEMANTICS",
    "RuntimeSemantic",
    "RuntimeSemanticsRegistry",
    "REASON_CODE_RECORDS",
    "UNKNOWN",
    "ReasonCodeCatalog",
    "ReasonCodeRecord",
    "AUTHORITY_PRIORITY",
    "CanonicalKnowledgeAuthority",
    "CanonicalKnowledgeDocument",
    "CanonicalKnowledgeEntry",
    "CanonicalKnowledgeLoadError",
    "CanonicalKnowledgeLoader",
    "CanonicalKnowledgeLoadResult",
    "CanonicalKnowledgeManifest",
    "VerificationState",
    "default_repository_root",
    "load_canonical_knowledge",
    "production_canonical_knowledge_manifest",
    "sha256_digest",
    "D7_REASON_CODES",
    "DRIFT_STATUS_RANK",
    "DriftAssessment",
    "DriftFinding",
    "DriftStatus",
    "SourceKind",
    "TemporalScope",
    "AUTHORITY_CONFLICT",
    "EVIDENCE_STALE",
    "PROVENANCE_FINGERPRINT_MISMATCH",
    "PROVENANCE_SOURCE_MISSING",
    "PROVENANCE_UNKNOWN",
    "PROVENANCE_VERSION_MISMATCH",
    "assess_authority_conflict",
    "assess_provenance",
    "build_conflicting_assessment",
    "fingerprint_bytes",
    "fingerprint_fields",
    "fingerprint_structured",
    "merge_status",
    "normalize_value",
    "provenance_from_advisor",
    "provenance_from_knowledge",
    "provenance_from_specialist",
    "provenance_from_trace",
]

__version__ = "0.1.0"
