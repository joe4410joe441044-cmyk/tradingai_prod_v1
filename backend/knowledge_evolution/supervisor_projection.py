"""D-8 read-only Supervisor projection.

Supervisor Authority = READ_ONLY_ANALYSIS.  The Supervisor observes D-8 context
read-only where useful but is NOT an investigation engine.  Its focus remains
"Is TradingAI operating normally according to canonical specification?".

This projection surfaces only a bounded, labeled summary; it grants no
investigation authority and no operational authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from backend.knowledge_evolution._base import MAX_D8_TEXT, bound
from backend.knowledge_evolution.authority import (
    SUPERVISOR_AUTHORITY,
    KnowledgeEvolutionAuthority,
)
from backend.knowledge_evolution.investigation import InvestigationResult


@dataclass(frozen=True)
class SupervisorKnowledgeContext:
    """A bounded read-only summary of D-8 activity for the Supervisor."""

    context_id: str
    observations: int = 0
    hypotheses: int = 0
    validations: int = 0
    knowledge_candidates: int = 0
    warnings: tuple[str, ...] = ()
    authority: str = SUPERVISOR_AUTHORITY.value
    investigation_authority: str = KnowledgeEvolutionAuthority.NONE.value
    operational_authority: str = KnowledgeEvolutionAuthority.NONE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "contextId": self.context_id,
            "observations": self.observations,
            "hypotheses": self.hypotheses,
            "validations": self.validations,
            "knowledgeCandidates": self.knowledge_candidates,
            "warnings": list(self.warnings),
            "authority": self.authority,
            "investigationAuthority": self.investigation_authority,
            "operationalAuthority": self.operational_authority,
        }


def build_supervisor_knowledge_context(
    *,
    observations: int = 0,
    hypotheses: int = 0,
    validations: int = 0,
    knowledge_candidates: int = 0,
    warnings: Iterable[str] = (),
) -> SupervisorKnowledgeContext:
    return SupervisorKnowledgeContext(
        context_id="d8-supervisor-readonly",
        observations=max(0, int(observations)),
        hypotheses=max(0, int(hypotheses)),
        validations=max(0, int(validations)),
        knowledge_candidates=max(0, int(knowledge_candidates)),
        warnings=tuple(warnings)[:20],
    )


def investigation_summary(result: InvestigationResult) -> dict[str, Any]:
    """Return a bounded read-only summary of one investigation result."""
    return {
        "investigationId": result.investigation_id,
        "question": bound(result.question, MAX_D8_TEXT),
        "outcome": result.outcome.value,
        "evidenceCount": len(result.evidence_set.evidence),
        "findings": list(result.finding_ids),
        "authority": SUPERVISOR_AUTHORITY.value,
    }


__all__ = [
    "SupervisorKnowledgeContext",
    "build_supervisor_knowledge_context",
    "investigation_summary",
]
