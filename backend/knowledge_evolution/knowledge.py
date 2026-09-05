"""D-8 Validated Knowledge: promotion is gated by Hypothesis + Validation + Human Review.

Validated Knowledge Authority = INFORMATION_ONLY.  It remains BELOW
``CANONICAL_SPECIFICATION`` and ``CURRENT_SOURCE_RUNTIME`` in the truth
hierarchy and NEVER overwrites canonical specification or mutates strategy.

Promotion is mandatory-gated:

    Hypothesis (SUPPORTED/validated)
      + Validation (SUPPORTED)
      + Human Review (APPROVED)
      -> ValidatedKnowledgeCandidate

A rejected / needs-more-evidence review, or a non-supported validation, never
promotes.  Even an APPROVED VALIDATED KNOWLEDGE does NOT automatically modify
entry/exit/DOM/spread/risk/leverage/sizing/MM/execution/strategy parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_FINDING_IDS,
    MAX_D8_LIMITATIONS,
    MAX_D8_TEXT,
    MAX_D8_WARNINGS,
    bound,
    dedupe,
    deterministic_id,
    order_annotations,
)
from backend.knowledge_evolution.authority import (
    KnowledgeEvolutionAuthority,
    VALIDATED_KNOWLEDGE_AUTHORITY,
    mutation_interfaces,
)
from backend.knowledge_evolution.human_review import HumanReview, ReviewDecision
from backend.knowledge_evolution.hypothesis import Hypothesis, HypothesisStatus
from backend.knowledge_evolution.validation import Validation, ValidationResult


class ValidatedKnowledgeStatus(str, Enum):
    """Deterministic status of a Validated Knowledge candidate."""

    VALIDATED_KNOWN = "VALIDATED_KNOWN"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    SUPERSEDED = "SUPERSEDED"


class KnowledgePromotionError(ValueError):
    """Raised when a promotion is attempted without the required gates."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"knowledge promotion blocked: {code}")


@dataclass(frozen=True)
class ValidatedKnowledge:
    """A VALIDATED_KNOWLEDGE-layer candidate (INFORMATION_ONLY)."""

    knowledge_id: str
    statement: str
    origin_hypothesis_id: str
    validation_references: tuple[str, ...]
    human_review_reference: str
    provenance: ProvenanceRecord
    version: str
    created_at: str
    limitations: tuple[str, ...] = ()
    scope: str = ""
    status: ValidatedKnowledgeStatus = ValidatedKnowledgeStatus.VALIDATED_KNOWN
    drift: Optional[object] = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledgeId": self.knowledge_id,
            "statement": self.statement,
            "originHypothesisId": self.origin_hypothesis_id,
            "validationReferences": list(self.validation_references),
            "humanReviewReference": self.human_review_reference,
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
                "notes": self.provenance.notes,
            },
            "version": self.version,
            "createdAt": self.created_at,
            "limitations": list(self.limitations),
            "scope": self.scope,
            "status": self.status.value,
            "drift": self.drift.stable_json() if self.drift and hasattr(self.drift, "stable_json") else None,
            "warnings": list(self.warnings),
            "authority": VALIDATED_KNOWLEDGE_AUTHORITY.value,
            "strategyMutationAuthority": "NONE",
            "canonicalMutationAuthority": "NONE",
        }

    @property
    def truth_level(self) -> TruthLevel:
        return TruthLevel.VALIDATED_KNOWLEDGE

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return VALIDATED_KNOWLEDGE_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def execution_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def strategy_mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def can_write_canonical(self) -> bool:
        return False

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)


def derive_knowledge_id(
    origin_hypothesis_id: str,
    version: str,
    validation_references: Iterable[str] = (),
) -> str:
    return deterministic_id(
        "knowledge",
        origin_hypothesis_id,
        version,
        tuple(sorted(dedupe(validation_references))),
    )


def promote_to_validated_knowledge(
    hypothesis: Hypothesis,
    validation: Validation,
    human_review: HumanReview,
    *,
    version: str = "1.0",
    created_at: str = "",
    scope: str = "",
    limitations: Iterable[str] = (),
    provenance: Optional[ProvenanceRecord] = None,
    drift: Optional[object] = None,
) -> ValidatedKnowledge:
    """Promote to Validated Knowledge ONLY after all gates pass.

    Gates enforced (all mandatory):

      * hypothesis must be a validated/SUPPORTED state;
      * validation.result must be SUPPORTED;
      * human_review.decision must be APPROVED.

    None of these grant any operational, execution, strategy or canonical
    authority.  The promotion is informational only.
    """
    if not isinstance(hypothesis, Hypothesis):
        raise TypeError("typed Hypothesis required")
    if not isinstance(validation, Validation):
        raise TypeError("typed Validation required")
    if not isinstance(human_review, HumanReview):
        raise TypeError("typed HumanReview required")

    if human_review.decision is not ReviewDecision.APPROVED:
        raise KnowledgePromotionError(
            "HUMAN_REVIEW_NOT_APPROVED", human_review.decision.value
        )
    if validation.result is not ValidationResult.SUPPORTED:
        raise KnowledgePromotionError(
            "VALIDATION_NOT_SUPPORTED", validation.result.value
        )
    if hypothesis.status not in {HypothesisStatus.SUPPORTED}:
        raise KnowledgePromotionError(
            "HYPOTHESIS_NOT_SUPPORTED", hypothesis.status.value
        )
    _reject_orphan_validation(validation, hypothesis)
    _reject_orphan_review(human_review, hypothesis)

    knowledge_id = derive_knowledge_id(
        hypothesis.hypothesis_id, version, (validation.validation_id,)
    )
    default_created = created_at or "--"
    return ValidatedKnowledge(
        knowledge_id=knowledge_id,
        statement=bound(hypothesis.statement, MAX_D8_TEXT),
        origin_hypothesis_id=hypothesis.hypothesis_id,
        validation_references=(validation.validation_id,),
        human_review_reference=human_review.review_id,
        provenance=provenance or _default_provenance(knowledge_id, hypothesis),
        version=bound(version, 16),
        created_at=bound(default_created, 64),
        limitations=tuple(
            dedupe(bound(item, 300) for item in limitations)
        )[:MAX_D8_LIMITATIONS]
        or hypothesis.limitations[:MAX_D8_LIMITATIONS],
        scope=bound(scope, 256),
        status=ValidatedKnowledgeStatus.VALIDATED_KNOWN,
        drift=drift,
        warnings=(),
    )


def _reject_orphan_validation(validation: Validation, hypothesis: Hypothesis) -> None:
    if validation.hypothesis_id != hypothesis.hypothesis_id:
        raise KnowledgePromotionError(
            "VALIDATION_HYPOTHESIS_MISMATCH",
            f"{validation.hypothesis_id}!={hypothesis.hypothesis_id}",
        )


def _reject_orphan_review(review: HumanReview, hypothesis: Hypothesis) -> None:
    if review.hypothesis_id != hypothesis.hypothesis_id:
        raise KnowledgePromotionError(
            "REVIEW_HYPOTHESIS_MISMATCH",
            f"{review.hypothesis_id}!={hypothesis.hypothesis_id}",
        )


def _default_provenance(knowledge_id: str, hypothesis: Hypothesis) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.VALIDATED_KNOWLEDGE,
        source_category=SourceCategory.CONTRACT,
        source_reference=f"VALIDATED_KNOWLEDGE:{knowledge_id}",
        notes=f"promoted from hypothesis {hypothesis.hypothesis_id}",
    )


__all__ = [
    "KnowledgePromotionError",
    "ValidatedKnowledge",
    "ValidatedKnowledgeStatus",
    "derive_knowledge_id",
    "promote_to_validated_knowledge",
]
