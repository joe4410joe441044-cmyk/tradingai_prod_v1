"""D-8 read-only Advisor projection: label knowledge states, never flatten them.

Advisor Authority = READ_ONLY.

The projection renders D-8 objects into a bounded, allowlisted, labeled view so
the Advisor can explicitly distinguish:

    FACT / CURRENT
    VALIDATED KNOWLEDGE
    FINDING
    PATTERN
    HYPOTHESIS
    UNVALIDATED
    INCONCLUSIVE

No raw databases, payloads or secrets are projected.  The core is
provider-neutral; this module performs no LLM call and no runtime mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional, Union

from backend.knowledge_evolution._base import (
    MAX_D8_EVIDENCE_IDS,
    MAX_D8_TEXT,
    bound,
    dedupe,
)
from backend.knowledge_evolution.authority import ADVISOR_AUTHORITY, KnowledgeEvolutionAuthority
from backend.knowledge_evolution.finding import Finding
from backend.knowledge_evolution.hypothesis import Hypothesis, HypothesisStatus
from backend.knowledge_evolution.knowledge import ValidatedKnowledge
from backend.knowledge_evolution.pattern import Pattern
from backend.knowledge_evolution.validation import Validation, ValidationResult

KnowledgeObject = Union[Finding, Pattern, Hypothesis, Validation, ValidatedKnowledge, None]


class KnowledgeStateLabel(str, Enum):
    """Explicit knowledge-state labels the Advisor may surface."""

    FACT_CURRENT = "FACT_CURRENT"
    VALIDATED_KNOWLEDGE = "VALIDATED_KNOWLEDGE"
    FINDING = "FINDING"
    PATTERN = "PATTERN"
    HYPOTHESIS = "HYPOTHESIS"
    UNVALIDATED = "UNVALIDATED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class AdvisorKnowledgeItem:
    """A bounded, labeled projection of one D-8 knowledge object."""

    label: str
    object_id: str
    statement: str
    state: str
    evidence: tuple[str, ...] = ()
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "objectId": self.object_id,
            "statement": self.statement,
            "state": self.state,
            "evidence": list(self.evidence),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class AdvisorKnowledgeProjection:
    """A bounded, allowlisted, labeled projection of D-8 knowledge."""

    items: tuple[AdvisorKnowledgeItem, ...]
    truncated: bool = False
    omittedCount: int = 0
    authority: str = ADVISOR_AUTHORITY.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "truncated": self.truncated,
            "omittedCount": self.omittedCount,
            "authority": self.authority,
        }

    @property
    def is_empty(self) -> bool:
        return not self.items


def label_object(item: KnowledgeObject) -> KnowledgeStateLabel:
    """Deterministically label a D-8 object with its truth state."""
    if isinstance(item, ValidatedKnowledge):
        return KnowledgeStateLabel.VALIDATED_KNOWLEDGE
    if isinstance(item, Finding):
        return KnowledgeStateLabel.FINDING
    if isinstance(item, Pattern):
        return KnowledgeStateLabel.PATTERN
    if isinstance(item, Hypothesis):
        if item.status in {
            HypothesisStatus.NOT_SUPPORTED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.SUPERSEDED,
        }:
            return KnowledgeStateLabel.UNVALIDATED
        return KnowledgeStateLabel.HYPOTHESIS
    if isinstance(item, Validation):
        if item.result is ValidationResult.INCONCLUSIVE:
            return KnowledgeStateLabel.INCONCLUSIVE
        if item.result is ValidationResult.SUPPORTED:
            return KnowledgeStateLabel.HYPOTHESIS
        return KnowledgeStateLabel.UNVALIDATED
    return KnowledgeStateLabel.FACT_CURRENT


def project_object(item: KnowledgeObject) -> Optional[AdvisorKnowledgeItem]:
    if item is None:
        return None
    label = label_object(item)
    object_id = getattr(item, "finding_id", None) or getattr(item, "pattern_id", None) or getattr(
        item, "hypothesis_id", None
    ) or getattr(item, "validation_id", None) or getattr(item, "knowledge_id", None) or ""
    statement = getattr(item, "statement", None) or getattr(item, "description", "") or ""
    evidence = tuple(
        getattr(item, "supporting_evidence_ids", ()) or getattr(item, "supporting_experience_ids", ())
    )
    provenance = getattr(getattr(item, "provenance", None), "source_reference", "") or ""
    return AdvisorKnowledgeItem(
        label=label.value,
        object_id=str(object_id),
        statement=bound(statement, MAX_D8_TEXT),
        state=getattr(item, "status", "UNKNOWN").value if hasattr(getattr(item, "status", None), "value") else str(getattr(item, "status", "UNKNOWN")),
        evidence=tuple(dedupe(str(x) for x in evidence))[:MAX_D8_EVIDENCE_IDS],
        provenance=str(provenance),
    )


def build_advisor_knowledge_projection(
    objects: Iterable[KnowledgeObject],
    *,
    limit: int = 20,
) -> AdvisorKnowledgeProjection:
    """Build a bounded, labeled projection of D-8 objects for the Advisor."""
    if limit < 0:
        raise ValueError("limit must be non-negative")
    ordered = sorted(
        (item for item in objects if item is not None),
        key=lambda item: (
            getattr(item, "finding_id", None) or getattr(item, "pattern_id", None)
            or getattr(item, "hypothesis_id", None) or getattr(item, "validation_id", None)
            or getattr(item, "knowledge_id", "") or ""
        ),
    )
    projected = [project_object(item) for item in ordered[:limit]]
    selected = tuple(item for item in projected if item is not None)
    omitted = max(0, len(ordered) - len(selected))
    return AdvisorKnowledgeProjection(
        items=selected,
        truncated=bool(omitted),
        omittedCount=omitted,
    )


__all__ = [
    "AdvisorKnowledgeItem",
    "AdvisorKnowledgeProjection",
    "KnowledgeObject",
    "KnowledgeStateLabel",
    "build_advisor_knowledge_projection",
    "label_object",
    "project_object",
]
