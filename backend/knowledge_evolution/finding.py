"""D-8 Finding: an interpreted but evidence-grounded observation.

A Finding is produced from an Investigation.  Its truth level is
``OBSERVATION_FINDING``.  Findings must be traceable back to evidence; an
"orphan" finding (one with no investigation / no evidence) is rejected.

Finding Authority = OBSERVATION_ONLY.

Findings preserve supporting evidence, counterevidence, reason codes,
provenance, confidence and limitations.  They never climb the truth ladder on
their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_COUNTEREVIDENCE_IDS,
    MAX_D8_EVIDENCE_IDS,
    MAX_D8_LIMITATIONS,
    MAX_D8_SOURCE_REFERENCES,
    MAX_D8_TEXT,
    MAX_D8_WARNINGS,
    bound,
    dedupe,
    deterministic_id,
)
from backend.knowledge_evolution.authority import (
    FINDING_AUTHORITY,
    KnowledgeEvolutionAuthority,
    mutation_interfaces,
)
from backend.knowledge_evolution.investigation import InvestigationResult
from backend.knowledge_evolution.pattern import EvidenceStrength
from backend.runtime.unified_trace import Provenance, TraceReasonCode


class FindingStatus(str, Enum):
    """Deterministic status of a Finding (observation only)."""

    OBSERVATION = "OBSERVATION"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    PROVISIONAL = "PROVISIONAL"


@dataclass(frozen=True)
class Finding:
    """A typed, evidence-grounded interpretation produced by an Investigation."""

    finding_id: str
    investigation_id: str
    statement: str
    supporting_evidence_ids: tuple[str, ...]
    counterevidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    source_references: tuple[Provenance, ...] = ()
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    evidence_strength: EvidenceStrength = EvidenceStrength.INSUFFICIENT
    status: FindingStatus = FindingStatus.OBSERVATION
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "findingId": self.finding_id,
            "investigationId": self.investigation_id,
            "statement": self.statement,
            "supportingEvidenceIds": list(self.supporting_evidence_ids),
            "counterevidenceIds": list(self.counterevidence_ids),
            "reasonCodes": list(self.reason_codes),
            "sourceReferences": [p.to_dict() for p in self.source_references],
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
                "notes": self.provenance.notes,
            },
            "evidenceStrength": self.evidence_strength.value,
            "status": self.status.value,
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "authority": FINDING_AUTHORITY.value,
        }

    @property
    def truth_level(self) -> TruthLevel:
        return TruthLevel.OBSERVATION_FINDING

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return FINDING_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def is_observation(self) -> bool:
        return self.authority is FINDING_AUTHORITY


def derive_finding_id(investigation_id: str, statement: str) -> str:
    return deterministic_id("finding", investigation_id, statement)


def build_finding(
    investigation: InvestigationResult,
    *,
    statement: str,
    supporting_evidence_ids: Optional[tuple[str, ...]] = None,
    counterevidence_ids: Optional[tuple[str, ...]] = None,
    status: FindingStatus = FindingStatus.OBSERVATION,
    provenance: Optional[ProvenanceRecord] = None,
    limitations: tuple[str, ...] = (),
    evidence_strength: Optional[EvidenceStrength] = None,
    finding_id: Optional[str] = None,
) -> Finding:
    """Create an evidence-grounded Finding; orphan findings are rejected.

    ``investigation`` must carry a non-empty evidence set; otherwise the
    finding would have no traceable evidence and is rejected.
    """
    if not isinstance(investigation, InvestigationResult):
        raise TypeError("typed InvestigationResult required")
    if investigation.evidence_set.empty:
        raise ValueError("orphan finding rejected: investigation has no evidence")
    evidence_set = investigation.evidence_set
    if not statement.strip():
        raise ValueError("finding statement is required")
    support_ids = tuple(supporting_evidence_ids or ())
    if not support_ids:
        support_ids = tuple(item.experience_id for item in evidence_set.evidence)
    counter_ids = tuple(counterevidence_ids or ())
    derived = finding_id or derive_finding_id(
        investigation.investigation_id, statement
    )
    strength = evidence_strength or resolve_strength(support_ids, counter_ids, evidence_set)
    reason_codes = _collect_reason_codes(evidence_set)
    warnings = list(evidence_set.warnings)
    if not counter_ids:
        warnings.append("COUNTEREVIDENCE_UNAVAILABLE")
    if len(support_ids) > MAX_D8_EVIDENCE_IDS:
        warnings.append("SUPPORTING_EVIDENCE_TRUNCATED")
    if len(counter_ids) > MAX_D8_COUNTEREVIDENCE_IDS:
        warnings.append("COUNTEREVIDENCE_TRUNCATED")
    return Finding(
        finding_id=derived,
        investigation_id=investigation.investigation_id,
        statement=bound(statement, MAX_D8_TEXT),
        supporting_evidence_ids=tuple(support_ids)[:MAX_D8_EVIDENCE_IDS],
        counterevidence_ids=tuple(counter_ids)[:MAX_D8_COUNTEREVIDENCE_IDS],
        reason_codes=tuple(dedupe(reason_codes))[:40],
        source_references=evidence_set.source_references[:MAX_D8_SOURCE_REFERENCES],
        provenance=provenance or _default_provenance(derived, investigation),
        evidence_strength=strength,
        status=status,
        limitations=tuple(dedupe(bound(item, 300) for item in limitations))[:MAX_D8_LIMITATIONS],
        warnings=tuple(dedupe(warnings))[:MAX_D8_WARNINGS],
    )


def resolve_strength(
    supporting_ids: tuple[str, ...],
    counter_ids: tuple[str, ...],
    evidence_set: object,
) -> EvidenceStrength:
    sample = len(supporting_ids) + len(counter_ids)
    if sample <= 1 or len(supporting_ids) <= 0:
        return EvidenceStrength.INSUFFICIENT
    if sample < 5:
        return EvidenceStrength.WEAK
    ratio = len(supporting_ids) / sample
    if len(counter_ids) <= 0:
        return EvidenceStrength.STRONG
    if ratio >= 0.8:
        return EvidenceStrength.STRONG
    if ratio >= 0.6:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


def _collect_reason_codes(evidence_set: object) -> tuple[str, ...]:
    codes: list[str] = []
    for item in getattr(evidence_set, "evidence", ()):
        for code in item.reason_codes:
            codes.append(code.code)
    return tuple(codes)


def _default_provenance(finding_id: str, investigation: InvestigationResult) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.CONTRACT,
        source_reference=f"FINDING:{finding_id}",
        notes=f"derived from investigation {investigation.investigation_id}",
    )


__all__ = [
    "Finding",
    "FindingStatus",
    "build_finding",
    "derive_finding_id",
    "resolve_strength",
]
