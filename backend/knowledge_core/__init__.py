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
]

__version__ = "0.1.0"
