"""TradingAI Knowledge Evolution (D-8): deterministic Experience Memory,
Investigation, Pattern/Finding, Hypothesis, Validation and Validated Knowledge.

D-8 introduces the first complete deterministic foundation for:

    RAW EVIDENCE
        -> EXPERIENCE MEMORY
        -> INVESTIGATION
        -> PATTERN / FINDING
        -> HYPOTHESIS
        -> VALIDATION
        -> HUMAN REVIEW
        -> VALIDATED KNOWLEDGE

Authority ladder (descriptive metadata; nothing here grants operational power):

    Experience Memory Authority      = EVIDENCE_ONLY
    Investigation Authority          = ANALYSIS_ONLY
    Pattern Authority                = OBSERVATION_ONLY
    Finding Authority                = OBSERVATION_ONLY
    Hypothesis Authority             = HYPOTHESIS_ONLY
    Validation Authority             = ANALYSIS_ONLY
    Validated Knowledge Authority    = INFORMATION_ONLY
    Knowledge Promotion Authority    = HUMAN_REVIEW_REQUIRED
    Advisor Authority                = READ_ONLY
    Supervisor Authority             = READ_ONLY_ANALYSIS
    Operational / Execution / Strategy / MM / Canonical Mutation = NONE

This package is PROVIDER_NEUTRAL (no LLM SDK, no network), deterministic
(no random IDs) and read-only with respect to the runtime.

Dependency direction:
    knowledge_evolution -> knowledge_core (provenance/truth/drift)
    knowledge_evolution -> runtime.unified_trace (D-5 authoritative evidence)
    Advisor/Supervisor may import knowledge_evolution (read-only views).
"""

from __future__ import annotations

from .authority import (
    ADVISOR_AUTHORITY,
    CANONICAL_MUTATION_AUTHORITY,
    EXECUTION_AUTHORITY,
    EXPERIENCE_MEMORY_AUTHORITY,
    FINDING_AUTHORITY,
    HYPOTHESIS_AUTHORITY,
    INVESTIGATION_AUTHORITY,
    KNOWLEDGE_PROMOTION_AUTHORITY,
    MONEY_MANAGEMENT_MUTATION_AUTHORITY,
    OPERATIONAL_AUTHORITY,
    PATTERN_AUTHORITY,
    STRATEGY_MUTATION_AUTHORITY,
    SUPERVISOR_AUTHORITY,
    VALIDATED_KNOWLEDGE_AUTHORITY,
    VALIDATION_AUTHORITY,
    KnowledgeEvolutionAuthority,
    assert_no_mutation,
    mutation_interfaces,
)
from .experience import (
    ExperienceRecord,
    ExperienceStatus,
    ExperienceType,
    derive_experience_id,
    experience_from_trace,
    make_experience,
)
from .investigation import (
    InvestigationEvidenceSet,
    InvestigationFilter,
    InvestigationOutcome,
    InvestigationRequest,
    InvestigationResult,
    make_investigation,
    run_investigation,
    select_experiences,
)
from .pattern import (
    CooccurrenceCounts,
    EvidenceStrength,
    Pattern,
    PatternStatus,
    PatternType,
    build_pattern,
    count_cooccurrence,
    derive_pattern_id,
    resolve_evidence_strength,
)
from .finding import Finding, FindingStatus, build_finding, derive_finding_id
from .hypothesis import (
    Hypothesis,
    HypothesisStatus,
    advance_hypothesis,
    derive_hypothesis_id,
    propose_hypothesis,
)
from .validation import (
    AcceptanceCriterion,
    Relation,
    Validation,
    ValidationEvidence,
    ValidationMetric,
    ValidationMethod,
    ValidationResult,
    derive_validation_id,
    evaluate_validation,
)
from .human_review import HumanReview, ReviewDecision, derive_review_id, record_human_review
from .knowledge import (
    KnowledgePromotionError,
    ValidatedKnowledge,
    ValidatedKnowledgeStatus,
    derive_knowledge_id,
    promote_to_validated_knowledge,
)
from .advisor_projection import (
    AdvisorKnowledgeItem,
    AdvisorKnowledgeProjection,
    KnowledgeStateLabel,
    build_advisor_knowledge_projection,
    label_object,
)
from .supervisor_projection import (
    SupervisorKnowledgeContext,
    build_supervisor_knowledge_context,
    investigation_summary,
)

__all__ = [
    # authority
    "ADVISOR_AUTHORITY", "CANONICAL_MUTATION_AUTHORITY", "EXECUTION_AUTHORITY",
    "EXPERIENCE_MEMORY_AUTHORITY", "FINDING_AUTHORITY", "HYPOTHESIS_AUTHORITY",
    "INVESTIGATION_AUTHORITY", "KNOWLEDGE_PROMOTION_AUTHORITY",
    "MONEY_MANAGEMENT_MUTATION_AUTHORITY", "OPERATIONAL_AUTHORITY", "PATTERN_AUTHORITY",
    "STRATEGY_MUTATION_AUTHORITY", "SUPERVISOR_AUTHORITY",
    "VALIDATED_KNOWLEDGE_AUTHORITY", "VALIDATION_AUTHORITY",
    "KnowledgeEvolutionAuthority", "assert_no_mutation", "mutation_interfaces",
    # experience
    "ExperienceRecord", "ExperienceStatus", "ExperienceType", "derive_experience_id",
    "experience_from_trace", "make_experience",
    # investigation
    "InvestigationEvidenceSet", "InvestigationFilter", "InvestigationOutcome",
    "InvestigationRequest", "InvestigationResult", "make_investigation",
    "run_investigation", "select_experiences",
    # pattern
    "CooccurrenceCounts", "EvidenceStrength", "Pattern", "PatternStatus", "PatternType",
    "build_pattern", "count_cooccurrence", "derive_pattern_id", "resolve_evidence_strength",
    # finding
    "Finding", "FindingStatus", "build_finding", "derive_finding_id",
    # hypothesis
    "Hypothesis", "HypothesisStatus", "advance_hypothesis", "derive_hypothesis_id",
    "propose_hypothesis",
    # validation
    "AcceptanceCriterion", "Relation", "Validation", "ValidationEvidence",
    "ValidationMetric", "ValidationMethod", "ValidationResult", "derive_validation_id",
    "evaluate_validation",
    # human review
    "HumanReview", "ReviewDecision", "derive_review_id", "record_human_review",
    # validated knowledge
    "KnowledgePromotionError", "ValidatedKnowledge", "ValidatedKnowledgeStatus",
    "derive_knowledge_id", "promote_to_validated_knowledge",
    # projections
    "AdvisorKnowledgeItem", "AdvisorKnowledgeProjection", "KnowledgeStateLabel",
    "build_advisor_knowledge_projection", "label_object",
    "SupervisorKnowledgeContext", "build_supervisor_knowledge_context",
    "investigation_summary",
]

__version__ = "0.1.0"
