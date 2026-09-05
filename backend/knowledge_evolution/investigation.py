"""D-8 Investigation: a bounded, deterministic question over historical evidence.

An Investigation represents:

    a bounded question (natural language, for the human/LLM helper)
    + selected historical evidence (deterministic, inspectable)
    + selection criteria (the explicit filters that were applied)
    + provenance
    + resulting findings

Investigation Authority = ANALYSIS_ONLY.  It never modifies strategy, never
changes runtime and never authors a trading rule.

Evidence selection is ALWAYS deterministic and auditable.  An LLM may help
phrase the natural-language question, but the final selected evidence set is
produced by this module from explicit, inspectable filters - never silently
chosen by a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_core.drift import DriftStatus
from backend.knowledge_evolution._base import (
    MAX_D8_EVIDENCE_IDS,
    MAX_D8_SOURCE_REFERENCES,
    MAX_D8_WARNINGS,
    bound,
    dedupe,
    deterministic_id,
)
from backend.knowledge_evolution.authority import (
    INVESTIGATION_AUTHORITY,
    KnowledgeEvolutionAuthority,
    mutation_interfaces,
)
from backend.knowledge_evolution.experience import ExperienceRecord, ExperienceType
from backend.runtime.unified_trace import TraceCompleteness, Provenance


class InvestigationOutcome(str, Enum):
    """Deterministic 'did the evidence answer the question' outcome."""

    FINDINGS_PRODUCED = "FINDINGS_PRODUCED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_MATCHING_EVIDENCE = "NO_MATCHING_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class InvestigationFilter:
    """Explicit, auditable selection criteria.

    Any field that is ``None`` is not applied.  ``reason_codes`` matches when
    the experience carries ANY of the listed codes.  ``outcomes`` matches when
    the experience outcome is ANY of the listed outcomes.  Time range uses the
    experience ``started_at`` (ISO-8601 string ordering).
    """

    symbol: Optional[str] = None
    mode: Optional[str] = None
    started_from: Optional[str] = None
    started_to: Optional[str] = None
    trace_ids: tuple[str, ...] = ()
    decision_ids: tuple[str, ...] = ()
    trade_ids: tuple[str, ...] = ()
    experience_types: tuple[ExperienceType, ...] = ()
    reason_codes: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    completeness: tuple[TraceCompleteness, ...] = ()
    drift_statuses: tuple[DriftStatus, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "mode": self.mode,
            "startedFrom": self.started_from,
            "startedTo": self.started_to,
            "traceIds": list(self.trace_ids),
            "decisionIds": list(self.decision_ids),
            "tradeIds": list(self.trade_ids),
            "experienceTypes": [t.value for t in self.experience_types],
            "reasonCodes": list(self.reason_codes),
            "outcomes": list(self.outcomes),
            "completeness": [c.value for c in self.completeness],
            "driftStatuses": [d.value for d in self.drift_statuses],
        }


def _matches(record: ExperienceRecord, criterion: InvestigationFilter) -> bool:
    if criterion.symbol is not None and record.symbol != criterion.symbol:
        return False
    if criterion.mode is not None and record.mode != criterion.mode:
        return False
    if criterion.started_from is not None and (record.started_at or "") < criterion.started_from:
        return False
    if criterion.started_to is not None and (record.started_at or "") > criterion.started_to:
        return False
    if criterion.trace_ids and record.trace_id not in criterion.trace_ids:
        return False
    if criterion.decision_ids and record.decision_id not in criterion.decision_ids:
        return False
    if criterion.trade_ids and record.trade_id not in criterion.trade_ids:
        return False
    if criterion.experience_types and record.experience_type not in criterion.experience_types:
        return False
    if criterion.reason_codes:
        present = {code.code for code in record.reason_codes}
        if not (present & set(criterion.reason_codes)):
            return False
    if criterion.outcomes and record.outcome not in criterion.outcomes:
        return False
    if criterion.completeness and record.completeness not in criterion.completeness:
        return False
    if criterion.drift_statuses:
        drift_status = record.drift.status if record.drift else None
        if drift_status not in criterion.drift_statuses:
            return False
    return True


def select_experiences(
    experiences: Iterable[ExperienceRecord],
    criterion: InvestigationFilter,
    *,
    limit: int = 100,
) -> tuple[ExperienceRecord, ...]:
    """Deterministically select experiences matching ``criterion``.

    The selection is ordered by ``experience_id`` for reproducibility and
    enforced to ``limit`` (bounded).  Inputs are never mutated.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    ordered = sorted(experiences, key=lambda item: item.experience_id)
    selected = [item for item in ordered if _matches(item, criterion)]
    return tuple(selected[:limit])


@dataclass(frozen=True)
class InvestigationEvidenceSet:
    """The result of a deterministic, auditable evidence selection."""

    investigation_id: str
    criterion: InvestigationFilter
    evidence: tuple[ExperienceRecord, ...]
    total_candidates: int
    truncated: bool
    provenance: ProvenanceRecord
    warnings: tuple[str, ...] = ()
    source_references: tuple[Provenance, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigationId": self.investigation_id,
            "criterion": self.criterion.as_dict(),
            "evidenceCount": len(self.evidence),
            "evidenceIds": [item.experience_id for item in self.evidence],
            "totalCandidates": self.total_candidates,
            "truncated": self.truncated,
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
                "notes": self.provenance.notes,
            },
            "warnings": list(self.warnings),
            "sourceReferences": [p.to_dict() for p in self.source_references],
            "authority": INVESTIGATION_AUTHORITY.value,
        }

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return INVESTIGATION_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def empty(self) -> bool:
        return not self.evidence


@dataclass(frozen=True)
class InvestigationRequest:
    """A bounded question plus its explicit selection criteria."""

    investigation_id: str
    question: str
    criterion: InvestigationFilter
    provenance: ProvenanceRecord
    limit: int = 100
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigationId": self.investigation_id,
            "question": self.question,
            "criterion": self.criterion.as_dict(),
            "limit": self.limit,
            "provenance": self.provenance.source_reference,
            "warnings": list(self.warnings),
            "authority": INVESTIGATION_AUTHORITY.value,
        }


@dataclass(frozen=True)
class InvestigationResult:
    """The typed result of running an investigation over selected evidence."""

    investigation_id: str
    question: str
    outcome: InvestigationOutcome
    evidence_set: InvestigationEvidenceSet
    finding_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigationId": self.investigation_id,
            "question": self.question,
            "outcome": self.outcome.value,
            "evidenceSet": self.evidence_set.to_dict(),
            "findingIds": list(self.finding_ids),
            "warnings": list(self.warnings),
            "authority": INVESTIGATION_AUTHORITY.value,
        }


def make_investigation(
    *,
    question: str,
    criterion: InvestigationFilter,
    provenance: Optional[ProvenanceRecord] = None,
    limit: int = 100,
    investigation_id: Optional[str] = None,
) -> InvestigationRequest:
    """Create a bounded InvestigationRequest with a deterministic ID."""
    if not question.strip():
        raise ValueError("investigation question is required")
    derived = investigation_id or deterministic_id(
        "investigation", question, criterion.as_dict()
    )
    return InvestigationRequest(
        investigation_id=derived,
        question=bound(question, 512),
        criterion=criterion,
        provenance=provenance or _default_provenance(derived),
        limit=limit,
    )


def run_investigation(
    request: InvestigationRequest,
    experiences: Iterable[ExperienceRecord],
    *,
    evidence_limit: int = 100,
) -> InvestigationResult:
    """    Deterministically run an investigation: select evidence and report.

    The evidence selection is auditable via ``evidence_set.criterion`` and
    ``evidence_set.evidence``.  Truncation and missing evidence are surfaced
    explicitly (never hidden).
    """
    materialized = list(experiences)
    total_candidates = len(materialized)
    effective_limit = min(
        evidence_limit if evidence_limit is not None else request.limit,
        request.limit,
        MAX_D8_EVIDENCE_IDS,
    )
    matching = [item for item in sorted(materialized, key=lambda item: item.experience_id)
                if _matches(item, request.criterion)]
    truncated = len(matching) > effective_limit
    selected = tuple(matching[:effective_limit])
    warnings = list(request.warnings)
    if truncated:
        warnings.append("EVIDENCE_TRUNCATED")
    if not selected:
        outcome = InvestigationOutcome.NO_MATCHING_EVIDENCE
        warnings.append("NO_MATCHING_EVIDENCE")
    elif all(
        item.completeness in {TraceCompleteness.AMBIGUOUS, TraceCompleteness.UNAVAILABLE}
        for item in selected
    ):
        outcome = InvestigationOutcome.AMBIGUOUS
    elif len(selected) < 2:
        outcome = InvestigationOutcome.INSUFFICIENT_EVIDENCE
        warnings.append("INSUFFICIENT_EVIDENCE")
    else:
        outcome = InvestigationOutcome.FINDINGS_PRODUCED
    warnings = list(dedupe(warnings))[:MAX_D8_WARNINGS]
    evidence_set = InvestigationEvidenceSet(
        investigation_id=request.investigation_id,
        criterion=request.criterion,
        evidence=selected,
        total_candidates=total_candidates,
        truncated=truncated,
        provenance=request.provenance,
        warnings=tuple(warnings),
        source_references=_collect_source_references(selected),
    )
    return InvestigationResult(
        investigation_id=request.investigation_id,
        question=request.question,
        outcome=outcome,
        evidence_set=evidence_set,
        finding_ids=(),
        warnings=tuple(warnings),
        provenance=request.provenance,
    )


def _collect_source_references(evidence: tuple[ExperienceRecord, ...]) -> tuple[Provenance, ...]:
    seen: dict[tuple[str, str, str], Provenance] = {}
    for item in evidence:
        for reference in item.source_references:
            key = (reference.source_subsystem.value if hasattr(reference.source_subsystem, "value") else str(reference.source_subsystem), reference.source_type, reference.source_identifier)
            if key not in seen:
                seen[key] = reference
    return tuple(sorted(
        seen.values(),
        key=lambda p: (
            p.source_subsystem.value if hasattr(p.source_subsystem, "value") else str(p.source_subsystem),
            p.source_type,
            p.source_identifier,
        ),
    ))[:MAX_D8_SOURCE_REFERENCES]


def _default_provenance(investigation_id: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.CONTRACT,
        source_reference=f"INVESTIGATION:{investigation_id}",
        notes="deterministic investigation evidence selection",
    )


__all__ = [
    "InvestigationEvidenceSet",
    "InvestigationFilter",
    "InvestigationOutcome",
    "InvestigationRequest",
    "InvestigationResult",
    "make_investigation",
    "run_investigation",
    "select_experiences",
]
