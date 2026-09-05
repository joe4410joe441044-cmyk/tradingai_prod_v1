"""D-8 Human Review: the mandatory informational gate for knowledge promotion.

Human approval is an informational approval for knowledge promotion ONLY.  It
does NOT authorize LIVE, PAPER, orders, strategy deployment or any runtime
mutation.

Promotion Authority = HUMAN_REVIEW_REQUIRED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_TEXT,
    bound,
    deterministic_id,
)
from backend.knowledge_evolution.authority import (
    KNOWLEDGE_PROMOTION_AUTHORITY,
    KnowledgeEvolutionAuthority,
    mutation_interfaces,
)


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


@dataclass(frozen=True)
class HumanReview:
    """A typed, informational human review of a hypothesis/knowledge promotion."""

    review_id: str
    hypothesis_id: str
    decision: ReviewDecision
    reviewer: str
    reviewed_at: str
    notes: str = ""
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewId": self.review_id,
            "hypothesisId": self.hypothesis_id,
            "decision": self.decision.value,
            "reviewer": self.reviewer,
            "reviewedAt": self.reviewed_at,
            "notes": self.notes,
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
            },
            "operationalAuthority": "NONE",
            "knowledgePromotionAuthority": KNOWLEDGE_PROMOTION_AUTHORITY.value,
        }

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return KNOWLEDGE_PROMOTION_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def approved(self) -> bool:
        return self.decision is ReviewDecision.APPROVED


def derive_review_id(
    hypothesis_id: str,
    decision: ReviewDecision,
    reviewer: str,
    reviewed_at: str,
) -> str:
    return deterministic_id("review", hypothesis_id, decision.value, reviewer, reviewed_at)


def record_human_review(
    *,
    hypothesis_id: str,
    decision: ReviewDecision,
    reviewer: str,
    reviewed_at: str,
    notes: str = "",
    provenance: Optional[ProvenanceRecord] = None,
) -> HumanReview:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if not reviewed_at:
        raise ValueError("reviewed_at is required")
    review_id = derive_review_id(hypothesis_id, decision, reviewer, reviewed_at)
    return HumanReview(
        review_id=review_id,
        hypothesis_id=hypothesis_id,
        decision=decision,
        reviewer=bound(reviewer, 128),
        reviewed_at=bound(reviewed_at, 64),
        notes=bound(notes, MAX_D8_TEXT),
        provenance=provenance or ProvenanceRecord(
            truth_level=TruthLevel.OBSERVATION_FINDING,
            source_category=SourceCategory.CONTRACT,
            source_reference=f"HUMAN_REVIEW:{review_id}",
            notes="informational knowledge promotion review",
        ),
    )


__all__ = [
    "HumanReview",
    "ReviewDecision",
    "derive_review_id",
    "record_human_review",
]
