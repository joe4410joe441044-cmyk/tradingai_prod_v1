"""Bounded, typed KNOWLEDGE_EVOLUTION context for the AI Advisor (D-9D).

This is INFORMATION_ONLY and READ_ONLY evidence infrastructure.  It provides a
distinct, bounded ``KNOWLEDGE_EVOLUTION`` layer that the Advisor prompt builder
renders separately from ``CURRENT_RUNTIME`` and ``HISTORICAL_EVIDENCE``.

It reduces the real Knowledge Evolution persistence (``KnowledgeEvolutionStore``,
the single knowledge authority introduced in D-9F/D-9C) into a small, allowlisted,
bounded projection suitable for prompt injection, and it connects a bounded,
deterministic Investigation over the authoritative D-5 trace
(``TradingTraceStore`` -> ``UnifiedTradingTrace`` -> ``ExperienceRecord``).

It deliberately:

* never dumps raw database rows, SQL or secrets;
* never flattens truth levels: ValidatedKnowledge stays below Canonical
  Specification, Finding/Pattern stay observations, Hypothesis stays
  unvalidated until validation + human review, Investigation is ANALYSIS_ONLY;
* never creates a second knowledge persistence authority / cache / DB;
* never emits a write-side Knowledge mutation from an ordinary Advisor chat;
* bounds every collection and exposes truncation as an explicit fact.

This module is PROVIDER_NEUTRAL (no LLM SDK, no network).
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from backend.knowledge_evolution._base import bound, dedupe
from backend.knowledge_evolution.authority import (
    ADVISOR_AUTHORITY,
    INVESTIGATION_AUTHORITY,
)
from backend.knowledge_evolution.experience import (
    ExperienceRecord,
    experience_from_trace,
)
from backend.knowledge_evolution.finding import Finding
from backend.knowledge_evolution.hypothesis import Hypothesis, HypothesisStatus
from backend.knowledge_evolution.investigation import (
    InvestigationFilter,
    InvestigationResult,
    make_investigation,
    run_investigation,
)
from backend.knowledge_evolution.knowledge import ValidatedKnowledge
from backend.knowledge_evolution.pattern import Pattern
from backend.knowledge_evolution.validation import Validation, ValidationResult
from backend.knowledge_evolution.advisor_projection import (
    KnowledgeStateLabel,
    label_object,
    project_object,
)
from backend.runtime.unified_trace import list_unified_traces

# --------------------------------------------------------------------------- #
# Bounds (explicit, deterministic; no unbounded prompt growth).
# --------------------------------------------------------------------------- #

MAX_KNOWLEDGE_VALIDATED = 3
MAX_KNOWLEDGE_HYPOTHESES = 3
MAX_KNOWLEDGE_FINDINGS = 3
MAX_KNOWLEDGE_PATTERNS = 3
MAX_KNOWLEDGE_VALIDATIONS = 3
MAX_KNOWLEDGE_TEXT = 640
MAX_KNOWLEDGE_IDENTIFIER = 128
MAX_KNOWLEDGE_EVIDENCE_IDS = 8
MAX_KNOWLEDGE_WARNINGS = 8
MAX_KNOWLEDGE_INVESTIGATION_EVIDENCE = 10
MAX_KNOWLEDGE_TRACES = 5

# Authority labels surfaced to the prompt (never operational).
READ_ONLY_AUTHORITY = ADVISOR_AUTHORITY.value
ANALYSIS_ONLY_AUTHORITY = INVESTIGATION_AUTHORITY.value


class AdvisorKnowledgeItem(BaseModel):
    """A bounded, labeled projection of one Knowledge Evolution object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    objectId: str
    statement: str
    state: str
    evidence: Tuple[str, ...] = Field(default_factory=tuple)
    provenance: str = ""


class AdvisorKnowledgeInvestigation(BaseModel):
    """A bounded, ANALYSIS_ONLY Investigation projection over evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    investigationId: str
    question: str
    outcome: str
    status: str
    evidenceCount: int
    totalCandidates: int
    truncated: bool
    reasonCodes: Tuple[str, ...] = Field(default_factory=tuple)
    warnings: Tuple[str, ...] = Field(default_factory=tuple)
    authority: str = ANALYSIS_ONLY_AUTHORITY


class AdvisorKnowledgeContext(BaseModel):
    """A bounded, allowlisted, classified Knowledge Evolution context.

    Conceptual layering (never flattened): status, validatedKnowledge (highest
    projection priority), hypotheses, findings, patterns, validations, the
    investigation block, warnings, truncation and the enclosing authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schemaVersion: str = "advisor-knowledge/v1"
    status: str = "AVAILABLE"
    validatedKnowledge: Tuple[AdvisorKnowledgeItem, ...] = Field(default_factory=tuple)
    hypotheses: Tuple[AdvisorKnowledgeItem, ...] = Field(default_factory=tuple)
    findings: Tuple[AdvisorKnowledgeItem, ...] = Field(default_factory=tuple)
    patterns: Tuple[AdvisorKnowledgeItem, ...] = Field(default_factory=tuple)
    validations: Tuple[AdvisorKnowledgeItem, ...] = Field(default_factory=tuple)
    investigation: Optional[AdvisorKnowledgeInvestigation] = None
    warnings: Tuple[str, ...] = Field(default_factory=tuple)
    truncated: bool = False
    authority: str = READ_ONLY_AUTHORITY

    @property
    def is_empty(self) -> bool:
        return not (
            self.validatedKnowledge
            or self.hypotheses
            or self.findings
            or self.patterns
            or self.validations
            or self.investigation is not None
        )

    @property
    def is_unavailable(self) -> bool:
        return self.status == "NOT_AVAILABLE"


# --------------------------------------------------------------------------- #
# Deterministic bounded projection of one D-8 object.
# --------------------------------------------------------------------------- #


def _statement_for(item: object) -> str:
    if isinstance(item, Validation):
        return (
            f"validation of hypothesis {bound(item.hypothesis_id, 64)}: "
            f"result={item.result.value} sample={item.sample_size} support={item.support_count}"
        )
    if isinstance(item, Hypothesis):
        detail = item.statement or ""
        status = item.status.value
        return detail or f"hypothesis ({status})"
    return str(getattr(item, "statement", "") or getattr(item, "description", ""))


def _project_knowledge_item(item: object) -> Optional[AdvisorKnowledgeItem]:
    """Project a single D-8 object into a bounded, classified Advisor item.

    Reuses the D-8 ``label_object``/``project_object`` projection where possible.
    """
    if item is None:
        return None
    projected = project_object(item)
    if projected is None:
        return None
    # D-8 reuses HYPOTHESIS for a SUPPORTED Validation; the Advisor-facing
    # VALIDATION bucket re-labels these so the classification stays distinct.
    if isinstance(item, Validation):
        label = KnowledgeStateLabel.INCONCLUSIVE.value if (
            item.result is ValidationResult.INCONCLUSIVE
        ) else "VALIDATION"
        state = item.result.value
    else:
        label = projected.label
        state = projected.state or "UNKNOWN"
    # Preserve the D-8 label so hypothesis-not-validated and finding-not-validated
    # remain explicit rather than being flattened into VALIDATED_KNOWLEDGE.
    return AdvisorKnowledgeItem(
        label=label,
        objectId=bound(projected.object_id, MAX_KNOWLEDGE_IDENTIFIER),
        statement=bound(_statement_for(item), MAX_KNOWLEDGE_TEXT),
        state=state,
        evidence=tuple(dedupe(projected.evidence))[:MAX_KNOWLEDGE_EVIDENCE_IDS],
        provenance=bound(projected.provenance, MAX_KNOWLEDGE_IDENTIFIER),
    )


def _bounded_bucket(
    objects: Iterable[object],
    *,
    limit: int,
) -> tuple[AdvisorKnowledgeItem, ...]:
    ordered = sorted(
        (item for item in objects if item is not None),
        key=lambda item: str(
            getattr(item, "knowledge_id", None)
            or getattr(item, "finding_id", None)
            or getattr(item, "pattern_id", None)
            or getattr(item, "hypothesis_id", None)
            or getattr(item, "validation_id", None)
            or ""
        ),
    )
    projected = tuple(item for item in (_project_knowledge_item(o) for o in ordered[:limit]) if item is not None)
    return projected


def build_advisor_investigation(
    *,
    question: str,
    investigation_id: str,
    criterion: InvestigationFilter,
    experiences: Iterable[ExperienceRecord],
    evidence_limit: int = MAX_KNOWLEDGE_INVESTIGATION_EVIDENCE,
) -> AdvisorKnowledgeInvestigation:
    """Project a bounded Investigation over authoritative Experience evidence."""
    request = make_investigation(
        question=question,
        criterion=criterion,
        investigation_id=investigation_id,
        limit=evidence_limit,
    )
    result = run_investigation(request, experiences, evidence_limit=evidence_limit)
    return _project_investigation_result(result)


def _project_investigation_result(result: InvestigationResult) -> AdvisorKnowledgeInvestigation:
    evidence = result.evidence_set.evidence
    reason_codes = tuple(
        dedupe(code.code for item in evidence for code in item.reason_codes)
    )[:MAX_KNOWLEDGE_EVIDENCE_IDS]
    warnings = tuple(dedupe(result.warnings))[:MAX_KNOWLEDGE_WARNINGS]
    return AdvisorKnowledgeInvestigation(
        investigationId=bound(result.investigation_id, MAX_KNOWLEDGE_IDENTIFIER),
        question=bound(result.question, MAX_KNOWLEDGE_TEXT),
        outcome=result.outcome.value,
        status="INCONCLUSIVE" if result.outcome.value in {
            "INSUFFICIENT_EVIDENCE", "NO_MATCHING_EVIDENCE", "AMBIGUOUS",
        } else "ANALYSIS_AVAILABLE",
        evidenceCount=len(evidence),
        totalCandidates=result.evidence_set.total_candidates,
        truncated=result.evidence_set.truncated,
        reasonCodes=reason_codes,
        warnings=warnings,
    )


def _build_default_investigation(
    *,
    trace_limit: int = MAX_KNOWLEDGE_TRACES,
    evidence_limit: int = MAX_KNOWLEDGE_INVESTIGATION_EVIDENCE,
) -> Optional[AdvisorKnowledgeInvestigation]:
    """Run a bounded, deterministic Investigation over authoritative D-5 evidence."""
    traces = list_unified_traces(limit=trace_limit)
    experiences = tuple(
        experience_from_trace(trace)
        for trace in traces
    )
    if not experiences:
        return AdvisorKnowledgeInvestigation(
            investigationId="advisor-default",
            question="What do recent trading evidence records show?",
            outcome="NO_MATCHING_EVIDENCE",
            status="INCONCLUSIVE",
            evidenceCount=0,
            totalCandidates=0,
            truncated=False,
            reasonCodes=(),
            warnings=("NO_MATCHING_EVIDENCE",),
        )
    return build_advisor_investigation(
        question="What do recent trading evidence records show?",
        investigation_id="advisor-default",
        criterion=InvestigationFilter(),
        experiences=experiences,
        evidence_limit=evidence_limit,
    )


def build_advisor_knowledge_context(
    *,
    validated_knowledge: Iterable[ValidatedKnowledge] = (),
    hypotheses: Iterable[Hypothesis] = (),
    findings: Iterable[Finding] = (),
    patterns: Iterable[Pattern] = (),
    validations: Iterable[Validation] = (),
    investigation: Optional[AdvisorKnowledgeInvestigation] = None,
    warnings: Iterable[str] = (),
    status: str = "AVAILABLE",
) -> AdvisorKnowledgeContext:
    """Build a bounded, deterministic, classified Knowledge Evolution context.

    Determinism: each bucket is sorted by object id and truncated to its bound.
    ValidatedKnowledge is projected first (highest priority) in the prompt layer.
    """
    vk_source = tuple(validated_knowledge)
    hyp_source = tuple(hypotheses)
    finding_source = tuple(findings)
    pattern_source = tuple(patterns)
    val_source = tuple(validations)

    vk_items = _bounded_bucket(vk_source, limit=MAX_KNOWLEDGE_VALIDATED)
    hyp_items = _bounded_bucket(hyp_source, limit=MAX_KNOWLEDGE_HYPOTHESES)
    finding_items = _bounded_bucket(finding_source, limit=MAX_KNOWLEDGE_FINDINGS)
    pattern_items = _bounded_bucket(pattern_source, limit=MAX_KNOWLEDGE_PATTERNS)
    val_items = _bounded_bucket(val_source, limit=MAX_KNOWLEDGE_VALIDATIONS)

    truncated = any(
        len(iterable) > limit
        for iterable, limit in (
            (vk_source, MAX_KNOWLEDGE_VALIDATED),
            (hyp_source, MAX_KNOWLEDGE_HYPOTHESES),
            (finding_source, MAX_KNOWLEDGE_FINDINGS),
            (pattern_source, MAX_KNOWLEDGE_PATTERNS),
            (val_source, MAX_KNOWLEDGE_VALIDATIONS),
        )
    )
    if investigation is not None and investigation.truncated:
        truncated = True
    return AdvisorKnowledgeContext(
        status=status,
        validatedKnowledge=vk_items,
        hypotheses=hyp_items,
        findings=finding_items,
        patterns=pattern_items,
        validations=val_items,
        investigation=investigation,
        warnings=tuple(dedupe(warnings))[:MAX_KNOWLEDGE_WARNINGS],
        truncated=truncated,
    )


def build_default_advisor_knowledge_context(
    *,
    store=None,
    store_path=None,
    trace_limit: int = MAX_KNOWLEDGE_TRACES,
    evidence_limit: int = MAX_KNOWLEDGE_INVESTIGATION_EVIDENCE,
) -> AdvisorKnowledgeContext:
    """Build the default Knowledge Evolution context from the single authority.

    Reads the real ``KnowledgeEvolutionStore`` (the one durable Knowledge
    persistence authority, D-9F/D-9C) and the authoritative D-5 trading trace.
    Any store/trace failure degrades to an empty NOT_AVAILABLE context so the
    Advisor request always continues safely.
    """
    try:
        from backend.knowledge_evolution.store import (
            DEFAULT_KNOWLEDGE_STORE_PATH,
            KnowledgeEvolutionStore,
        )

        resolved_path = store_path or DEFAULT_KNOWLEDGE_STORE_PATH
        if store is None:
            store = KnowledgeEvolutionStore(resolved_path)
        vk = store.list_validated_knowledge(limit=MAX_KNOWLEDGE_VALIDATED)
        hyps = store.list_hypotheses(limit=MAX_KNOWLEDGE_HYPOTHESES)
        findings = store.list_findings(limit=MAX_KNOWLEDGE_FINDINGS)
        patterns = store.list_patterns(limit=MAX_KNOWLEDGE_PATTERNS)
        validations = store.list_validations(limit=MAX_KNOWLEDGE_VALIDATIONS)
        investigation = _build_default_investigation(
            trace_limit=trace_limit, evidence_limit=evidence_limit
        )
        return build_advisor_knowledge_context(
            validated_knowledge=vk,
            hypotheses=hyps,
            findings=findings,
            patterns=patterns,
            validations=validations,
            investigation=investigation,
        )
    except Exception:
        return empty_advisor_knowledge_context()


def empty_advisor_knowledge_context() -> AdvisorKnowledgeContext:
    """A safe, bounded, empty Knowledge Evolution context (NOT_AVAILABLE)."""
    return AdvisorKnowledgeContext(
        status="NOT_AVAILABLE",
        warnings=("KNOWLEDGE_UNAVAILABLE",),
        truncated=False,
    )


# --------------------------------------------------------------------------- #
# Allowlisted rendering (name, value) pairs for the prompt layer.
# --------------------------------------------------------------------------- #


def knowledge_lines(context: Optional[AdvisorKnowledgeContext]) -> list[tuple[str, object]]:
    """Return allowlisted (name, value) pairs for the prompt layer.

    Only typed, bounded fields are surfaced; raw DB payloads are never projected.
    """
    if context is None:
        return [("classification", "KNOWLEDGE EVOLUTION"), ("status", "NOT_AVAILABLE")]
    lines: list[tuple[str, object]] = [
        ("classification", "KNOWLEDGE EVOLUTION"),
        ("status", context.status),
        ("authority", context.authority),
    ]
    if context.truncated:
        lines.append(("truncated", True))
    if context.warnings:
        lines.append(("warnings", ",".join(context.warnings)))
    if context.status == "NOT_AVAILABLE":
        lines.append(("statusDetail", "knowledge evolution unavailable"))
        return lines
    for prefix, items in (
        ("validatedKnowledge", context.validatedKnowledge),
        ("hypothesis", context.hypotheses),
        ("finding", context.findings),
        ("pattern", context.patterns),
        ("validation", context.validations),
    ):
        for index, item in enumerate(items):
            lines.extend(_item_lines(prefix, index, item))
    if context.investigation is not None:
        inv = context.investigation
        lines.append(("investigation.classification", "ANALYSIS ONLY"))
        lines.append(("investigation.authority", inv.authority))
        lines.append(("investigation.investigationId", inv.investigationId))
        lines.append(("investigation.outcome", inv.outcome))
        lines.append(("investigation.status", inv.status))
        lines.append(("investigation.evidenceCount", inv.evidenceCount))
        lines.append(("investigation.totalCandidates", inv.totalCandidates))
        if inv.truncated:
            lines.append(("investigation.truncated", True))
        if inv.reasonCodes:
            lines.append(("investigation.reasonCodes", ",".join(inv.reasonCodes)))
        if inv.warnings:
            lines.append(("investigation.warnings", ",".join(inv.warnings)))
    return lines


def _item_lines(prefix: str, index: int, item: AdvisorKnowledgeItem) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = [
        (f"{prefix}[{index}].label", item.label),
        (f"{prefix}[{index}].objectId", item.objectId),
        (f"{prefix}[{index}].state", item.state),
        (f"{prefix}[{index}].statement", item.statement),
    ]
    if item.evidence:
        out.append((f"{prefix}[{index}].evidence", ",".join(item.evidence)))
    if item.provenance:
        out.append((f"{prefix}[{index}].provenance", item.provenance))
    return out


def render_advisor_knowledge(context: Optional[AdvisorKnowledgeContext]) -> str:
    """Render the bounded Knowledge Evolution context as plain content lines."""
    return "\n".join(
        f"{name}={_render_scalar(value)}" for name, value in knowledge_lines(context)
    )


def _render_scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


__all__ = [
    "AdvisorKnowledgeContext",
    "AdvisorKnowledgeItem",
    "AdvisorKnowledgeInvestigation",
    "MAX_KNOWLEDGE_VALIDATED",
    "MAX_KNOWLEDGE_HYPOTHESES",
    "MAX_KNOWLEDGE_FINDINGS",
    "MAX_KNOWLEDGE_PATTERNS",
    "MAX_KNOWLEDGE_VALIDATIONS",
    "MAX_KNOWLEDGE_TEXT",
    "MAX_KNOWLEDGE_EVIDENCE_IDS",
    "MAX_KNOWLEDGE_WARNINGS",
    "MAX_KNOWLEDGE_INVESTIGATION_EVIDENCE",
    "MAX_KNOWLEDGE_TRACES",
    "build_advisor_investigation",
    "build_advisor_knowledge_context",
    "build_default_advisor_knowledge_context",
    "empty_advisor_knowledge_context",
    "knowledge_lines",
    "render_advisor_knowledge",
]
