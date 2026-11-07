"""Pure Canonical Context Builder for ``tradingai-context/v1``.

The builder is a pure function: it performs no network I/O, no LLM call, no
order submission, no runtime mutation, no file write, and no Git mutation.  It
only maps already-observed SOURCE / RUNTIME / PROJECT truth into one canonical
Context Pack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import re
from typing import Any, Mapping

from backend.supervisor.contracts import (
    DomainSnapshot,
    Freshness as SupervisorFreshness,
    InputValueState,
    MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot,
)

from .schema import (
    AcceptedTestsSection,
    Availability,
    CanonicalContext,
    ContextObservation,
    ContractsSection,
    FieldObservation,
    Freshness,
    FreshnessSummary,
    GeneratorInfo,
    KnownIssuesSection,
    ProjectTruth,
    ProvenanceEntry,
    ProvenanceSummary,
    SafetyContext,
    SectionMeta,
    SourceTruth,
    ValueState,
    WorkstreamsSection,
    empty_project_truth,
    unavailable_observation,
    unavailable_source_truth,
)

_SECTION_ORDER: tuple[str, ...] = (
    "runtime",
    "marketSelection",
    "executionControl",
    "market",
    "moneyManagement",
    "governance",
    "tradingCycle",
    "position",
    "orders",
    "smallAccount",
    "account",
    "emergency",
    "health",
)

_MARKET_SELECTION_FIELDS = frozenset(
    {
        "activeSymbol",
        "selectionMode",
        "selectionSource",
        "amsRuntimeState",
        "selectionCycleId",
        "safeSwitchState",
        "suitabilityEvidenceState",
    }
)
_EXECUTION_CONTROL_FIELDS = frozenset(
    {
        "authoritativeRuntimeState",
        "synchronizationState",
        "pendingOrderState",
        "realOrderAllowed",
        "selectedMode",
        "dryRun",
        "autoTradeEnabled",
    }
)
_ORDER_FIELDS = frozenset({"pendingOrderState"})

_SENSITIVE_NAME = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|secret|passphrase|password|token|"
    r"authorization|cookie|private[_-]?key|database[_-]?url)"
)
_SENSITIVE_VALUE = (
    re.compile(r"(?i)\b(api[_-]?key|api[_-]?secret|password|passphrase|"
               r"authorization|cookie|refresh[_-]?token|token|secret|"
               r"private[_-]?key)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
               r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)
REDACTED = "[REDACTED:SENSITIVE]"


@dataclass(frozen=True)
class RuntimeTruthSource:
    """RUNTIME TRUTH input: an existing Supervisor snapshot plus extras."""

    snapshot: ReadOnlySupervisorSnapshot | None = None
    extra: Mapping[str, ContextObservation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.snapshot is not None and not isinstance(
            self.snapshot, ReadOnlySupervisorSnapshot
        ):
            raise TypeError("snapshot must be a ReadOnlySupervisorSnapshot or None")
        for name in self.extra:
            if name not in _SECTION_ORDER:
                raise ValueError(f"unknown runtime extra section: {name}")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _redact(value: str) -> str:
    sanitized = value
    for pattern in _SENSITIVE_VALUE:
        sanitized = pattern.sub(REDACTED, sanitized)
    return sanitized


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    return _redact(str(value))


def _value_state(value: Any, observed: InputValueState | None) -> ValueState:
    if observed is not None:
        return {
            InputValueState.PRESENT: ValueState.PRESENT,
            InputValueState.ABSENT: ValueState.ABSENT,
            InputValueState.NULL: ValueState.NULL,
            InputValueState.UNKNOWN: ValueState.UNKNOWN,
        }[observed]
    if value is None:
        return ValueState.NULL
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized == "UNKNOWN":
            return ValueState.UNKNOWN
        if normalized == "UNAVAILABLE":
            return ValueState.UNAVAILABLE
    return ValueState.PRESENT


def _map_freshness(value: SupervisorFreshness) -> tuple[Freshness, Availability]:
    if value is SupervisorFreshness.FRESH:
        return Freshness.FRESH, Availability.AVAILABLE
    if value is SupervisorFreshness.STALE:
        return Freshness.STALE, Availability.STALE
    if value is SupervisorFreshness.MISSING:
        return Freshness.UNKNOWN, Availability.UNAVAILABLE
    return Freshness.UNKNOWN, Availability.UNKNOWN


_AVAILABILITY_SEVERITY = {
    Availability.AVAILABLE: 0,
    Availability.STALE: 1,
    Availability.UNKNOWN: 2,
    Availability.UNAVAILABLE: 3,
}
_FRESHNESS_SEVERITY = {
    Freshness.FRESH: 0,
    Freshness.NOT_APPLICABLE: 1,
    Freshness.STALE: 2,
    Freshness.UNKNOWN: 3,
}
_STATE_RANK = {
    ValueState.NULL: 1,
    ValueState.ABSENT: 2,
    ValueState.UNKNOWN: 3,
    ValueState.UNAVAILABLE: 3,
    ValueState.PRESENT: 4,
}


def _severity_availability(values: tuple[Availability, ...]) -> Availability:
    if not values:
        return Availability.UNKNOWN
    return max(values, key=lambda item: _AVAILABILITY_SEVERITY[item])


def _severity_freshness(values: tuple[Freshness, ...]) -> Freshness:
    if not values:
        return Freshness.UNKNOWN
    return max(values, key=lambda item: _FRESHNESS_SEVERITY[item])


def _domain_fields(
    domains: tuple[DomainSnapshot | MoneyManagementSnapshot, ...],
    *,
    include: frozenset[str] | None = None,
) -> tuple[FieldObservation, ...]:
    observations: dict[str, FieldObservation] = {}

    def consider(observation: FieldObservation) -> None:
        existing = observations.get(observation.name)
        if existing is None or (
            _STATE_RANK[observation.state] > _STATE_RANK[existing.state]
        ):
            observations[observation.name] = observation

    for domain in domains:
        field_states = {item.field: item.state for item in domain.fieldStates}
        domain_freshness, _ = _map_freshness(domain.freshness)
        for name in type(domain).model_fields:
            if name in {"freshness", "evaluatedAt", "source", "fieldStates"}:
                continue
            if include is not None and name not in include:
                continue
            if _SENSITIVE_NAME.search(name):
                consider(
                    FieldObservation(
                        name=name,
                        value=REDACTED,
                        state=ValueState.PRESENT,
                        source=getattr(domain, "source", None),
                        observedAt=domain.evaluatedAt,
                        freshness=domain_freshness,
                    )
                )
                continue
            raw = getattr(domain, name)
            consider(
                FieldObservation(
                    name=name,
                    value=_scalar(raw),
                    state=_value_state(raw, field_states.get(name)),
                    source=getattr(domain, "source", None),
                    observedAt=domain.evaluatedAt,
                    freshness=domain_freshness,
                )
            )
    return tuple(observations.values())


def _observation_from_domains(
    *,
    section: str,
    domains: tuple[DomainSnapshot | MoneyManagementSnapshot, ...],
    include: frozenset[str] | None = None,
) -> ContextObservation:
    source = next((getattr(item, "source", None) for item in domains if getattr(item, "source", None)), "UNKNOWN")
    observed_at = next(
        (item.evaluatedAt for item in domains if item.evaluatedAt is not None), None
    )
    mapped = tuple(_map_freshness(item.freshness) for item in domains)
    freshness = _severity_freshness(tuple(item[0] for item in mapped))
    availability = _severity_availability(tuple(item[1] for item in mapped))
    observed_at_values = tuple(
        item.evaluatedAt for item in domains if item.evaluatedAt is not None
    )
    if observed_at_values:
        observed_at = max(observed_at_values)
    return ContextObservation(
        meta=SectionMeta(
            source=source,
            observedAt=observed_at,
            freshness=freshness,
            availability=availability,
            provenance=(
                ProvenanceEntry(
                    source=source,
                    reader="supervisor-snapshot-adapter",
                    observedAt=observed_at,
                    detail=f"mapped from existing Supervisor snapshot ({section})",
                ),
            ),
        ),
        fields=_domain_fields(domains, include=include),
    )


def _sanitized_extra(observation: ContextObservation) -> ContextObservation:
    fields = tuple(
        FieldObservation(
            name=item.name,
            value=(
                REDACTED
                if _SENSITIVE_NAME.search(item.name)
                else _scalar(item.value)
            ),
            state=item.state,
            source=item.source,
            observedAt=item.observedAt,
            freshness=item.freshness,
        )
        for item in observation.fields
    )
    provenance = tuple(
        ProvenanceEntry(
            source=entry.source,
            reader=entry.reader,
            observedAt=entry.observedAt,
            detail=_redact(entry.detail) if entry.detail else None,
        )
        for entry in observation.meta.provenance
    )
    meta = observation.meta.model_copy(
        update={
            "detail": _redact(observation.meta.detail)
            if observation.meta.detail
            else None,
            "provenance": provenance,
        }
    )
    return ContextObservation(meta=meta, fields=fields)


def _section(
    *,
    snapshot: ReadOnlySupervisorSnapshot | None,
    extra: Mapping[str, ContextObservation],
    name: str,
    domains: tuple[DomainSnapshot | MoneyManagementSnapshot, ...] = (),
    include: frozenset[str] | None = None,
    unobserved_source: str,
) -> ContextObservation:
    if name in extra:
        return _sanitized_extra(extra[name])
    if snapshot is None:
        return unavailable_observation(
            unobserved_source,
            detail="RUNTIME TRUTH snapshot was not supplied",
        )
    if not domains:
        return unavailable_observation(unobserved_source)
    return _observation_from_domains(section=name, domains=domains, include=include)


def _section_meta_for_project(truth: ProjectTruth) -> SectionMeta:
    return truth.meta


def _project_sections(
    project: ProjectTruth,
) -> tuple[ContractsSection, WorkstreamsSection, KnownIssuesSection, AcceptedTestsSection]:
    meta = _section_meta_for_project(project)
    contracts = tuple(sorted(project.contracts, key=lambda item: item.contractId))
    workstreams = tuple(sorted(project.workstreams, key=lambda item: item.workstreamId))
    known_issues = tuple(sorted(project.knownIssues, key=lambda item: item.issueId))
    accepted_tests = tuple(
        sorted(project.acceptedTests, key=lambda item: item.testId)
    )
    return (
        ContractsSection(meta=meta, items=contracts),
        WorkstreamsSection(meta=meta, items=workstreams),
        KnownIssuesSection(meta=meta, items=known_issues),
        AcceptedTestsSection(meta=meta, items=accepted_tests),
    )


def _freshness_summary(
    *,
    generated_at: datetime,
    observations: Mapping[str, ContextObservation],
    source: SourceTruth,
    project_sections: tuple[
        ContractsSection, WorkstreamsSection, KnownIssuesSection, AcceptedTestsSection
    ],
) -> FreshnessSummary:
    metas: list[tuple[str, SectionMeta]] = [("source", source.meta)]
    metas.extend((name, observation.meta) for name, observation in observations.items())
    metas.extend(
        (name, section.meta)
        for name, section in zip(
            ("contracts", "workstreams", "knownIssues", "acceptedTests"),
            project_sections,
        )
    )
    stale = tuple(sorted(name for name, meta in metas if meta.availability is Availability.STALE))
    unknown = tuple(
        sorted(name for name, meta in metas if meta.availability is Availability.UNKNOWN)
    )
    unavailable = tuple(
        sorted(
            name for name, meta in metas if meta.availability is Availability.UNAVAILABLE
        )
    )
    observed = [
        meta for _, meta in metas
        if meta.availability in {Availability.AVAILABLE, Availability.STALE}
    ]
    if not observed:
        overall_freshness = Freshness.UNKNOWN
        overall_availability = Availability.UNAVAILABLE if unavailable else Availability.UNKNOWN
    elif any(meta.availability is Availability.STALE for meta in observed):
        overall_freshness = Freshness.STALE
        overall_availability = Availability.STALE
    else:
        overall_freshness = Freshness.FRESH
        overall_availability = Availability.AVAILABLE
    return FreshnessSummary(
        overall=overall_freshness,
        availability=overall_availability,
        evaluatedAt=generated_at,
        staleSections=stale,
        unknownSections=unknown,
        unavailableSections=unavailable,
        sectionCount=len(metas),
    )


def _provenance_summary(
    *,
    source: SourceTruth,
    observations: Mapping[str, ContextObservation],
    project_sections: tuple[
        ContractsSection, WorkstreamsSection, KnownIssuesSection, AcceptedTestsSection
    ],
) -> ProvenanceSummary:
    entries: list[ProvenanceEntry] = list(source.meta.provenance)
    for observation in observations.values():
        entries.extend(observation.meta.provenance)
    for section in project_sections:
        entries.extend(section.meta.provenance)
    unique: dict[tuple[str, str, str, str], ProvenanceEntry] = {}
    for entry in entries:
        key = (
            entry.source,
            entry.reader,
            entry.observedAt.isoformat() if entry.observedAt else "",
            entry.detail or "",
        )
        unique[key] = entry
    ordered = tuple(unique[key] for key in sorted(unique))
    return ProvenanceSummary(entries=ordered)


def build_canonical_context(
    *,
    generated_at: datetime,
    source_truth: SourceTruth | None = None,
    runtime_truth: RuntimeTruthSource | None = None,
    project_truth: ProjectTruth | None = None,
    generator: GeneratorInfo | None = None,
) -> CanonicalContext:
    """Map three truth systems into one deterministic, read-only Context Pack."""

    generated = _aware(generated_at)
    source = source_truth if source_truth is not None else unavailable_source_truth(generated)
    project = project_truth if project_truth is not None else empty_project_truth(generated)
    snapshot = runtime_truth.snapshot if runtime_truth is not None else None
    extra = dict(runtime_truth.extra) if runtime_truth is not None else {}

    observations = {
        "runtime": _section(
            snapshot=snapshot,
            extra=extra,
            name="runtime",
            domains=(
                (snapshot.bot, snapshot.loop) if snapshot is not None else ()
            ),
            unobserved_source="BOT_MANAGER_STATUS",
        ),
        "marketSelection": _section(
            snapshot=snapshot,
            extra=extra,
            name="marketSelection",
            domains=((snapshot.market,) if snapshot is not None else ()),
            include=_MARKET_SELECTION_FIELDS,
            unobserved_source="BOT_MANAGER_STATUS",
        ),
        "executionControl": _section(
            snapshot=snapshot,
            extra=extra,
            name="executionControl",
            domains=(
                (snapshot.execution, snapshot.trade) if snapshot is not None else ()
            ),
            include=_EXECUTION_CONTROL_FIELDS,
            unobserved_source="BOT_MANAGER_STATUS",
        ),
        "market": _section(
            snapshot=snapshot,
            extra=extra,
            name="market",
            domains=((snapshot.market,) if snapshot is not None else ()),
            unobserved_source="BOT_MANAGER_STATUS",
        ),
        "moneyManagement": _section(
            snapshot=snapshot,
            extra=extra,
            name="moneyManagement",
            domains=((snapshot.moneyManagement,) if snapshot is not None else ()),
            unobserved_source="MONEY_MANAGEMENT_RUNTIME",
        ),
        "governance": _section(
            snapshot=snapshot,
            extra=extra,
            name="governance",
            domains=((snapshot.governance,) if snapshot is not None else ()),
            unobserved_source="GOVERNANCE_RUNTIME",
        ),
        "tradingCycle": _section(
            snapshot=snapshot,
            extra=extra,
            name="tradingCycle",
            domains=((snapshot.decision,) if snapshot is not None else ()),
            unobserved_source="BOT_MANAGER_STATUS",
        ),
        "position": _section(
            snapshot=snapshot,
            extra=extra,
            name="position",
            unobserved_source="RUNTIME_POSITION_READER",
        ),
        "orders": _section(
            snapshot=snapshot,
            extra=extra,
            name="orders",
            domains=((snapshot.execution,) if snapshot is not None else ()),
            include=_ORDER_FIELDS,
            unobserved_source="BOT_MANAGER_STATUS",
        ),
        "smallAccount": _section(
            snapshot=snapshot,
            extra=extra,
            name="smallAccount",
            unobserved_source="SMALL_ACCOUNT_CONFIG",
        ),
        "account": _section(
            snapshot=snapshot,
            extra=extra,
            name="account",
            unobserved_source="ACCOUNT_STATUS",
        ),
        "emergency": _section(
            snapshot=snapshot,
            extra=extra,
            name="emergency",
            domains=((snapshot.emergency,) if snapshot is not None else ()),
            unobserved_source="GOVERNANCE_RUNTIME",
        ),
        "health": _section(
            snapshot=snapshot,
            extra=extra,
            name="health",
            domains=((snapshot.health,) if snapshot is not None else ()),
            unobserved_source="BACKEND_HEALTH_PRODUCER",
        ),
    }

    project_sections = _project_sections(project)
    freshness = _freshness_summary(
        generated_at=generated,
        observations=observations,
        source=source,
        project_sections=project_sections,
    )
    provenance = _provenance_summary(
        source=source,
        observations=observations,
        project_sections=project_sections,
    )

    return CanonicalContext(
        schemaVersion="tradingai-context/v1",
        generatedAt=generated,
        generator=generator if generator is not None else GeneratorInfo(),
        source=source,
        runtime=observations["runtime"],
        marketSelection=observations["marketSelection"],
        executionControl=observations["executionControl"],
        market=observations["market"],
        moneyManagement=observations["moneyManagement"],
        governance=observations["governance"],
        tradingCycle=observations["tradingCycle"],
        position=observations["position"],
        orders=observations["orders"],
        smallAccount=observations["smallAccount"],
        account=observations["account"],
        emergency=observations["emergency"],
        health=observations["health"],
        contracts=project_sections[0],
        workstreams=project_sections[1],
        knownIssues=project_sections[2],
        acceptedTests=project_sections[3],
        safety=SafetyContext(),
        freshness=freshness,
        provenance=provenance,
    )
