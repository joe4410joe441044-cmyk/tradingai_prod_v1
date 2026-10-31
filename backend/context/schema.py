"""Canonical AI context schema for ``tradingai-context/v1``.

The models in this module are pure, framework-neutral value objects.  They do
not read the filesystem, the network, the runtime, or Git.  Absent values are
represented explicitly rather than guessed: callers must say whether a fact is
``UNKNOWN``, ``UNAVAILABLE``, or ``STALE``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "tradingai-context/v1"
PROJECT_SCHEMA_VERSION = "tradingai-project-truth/v1"
GENERATOR_NAME = "tradingai-context-builder"
GENERATOR_VERSION = "1.0.0"


class Availability(str, Enum):
    """Whether the canonical context could observe a section at all."""

    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class Freshness(str, Enum):
    """Age/authority quality of an observed section or field."""

    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValueState(str, Enum):
    """Per-field presence state; never silently replaced by a default value."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    NULL = "NULL"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class WorkstreamStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"
    DEPLOYED = "DEPLOYED"


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PARTIAL = "PARTIAL"
    VERIFIED = "VERIFIED"


class IssueStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"


class TestStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    FAIL = "FAIL"


JsonScalar = str | int | float | bool | None


class ContextModel(BaseModel):
    """Immutable base model with no default side effects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_aware(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError("number must be finite")
    return value


class ProvenanceEntry(ContextModel):
    """One auditable statement about where a fact came from."""

    source: str = Field(min_length=1, max_length=200)
    reader: str = Field(min_length=1, max_length=200)
    observedAt: datetime | None = None
    detail: str | None = Field(default=None, max_length=500)

    @field_validator("observedAt")
    @classmethod
    def observed_aware(cls, value: datetime | None) -> datetime | None:
        return _optional_aware(value)


class SectionMeta(ContextModel):
    """Common provenance envelope attached to every canonical section."""

    source: str = Field(min_length=1, max_length=200)
    observedAt: datetime | None = None
    freshness: Freshness = Freshness.UNKNOWN
    availability: Availability = Availability.UNKNOWN
    provenance: tuple[ProvenanceEntry, ...] = ()
    detail: str | None = Field(default=None, max_length=500)

    @field_validator("observedAt")
    @classmethod
    def observed_aware(cls, value: datetime | None) -> datetime | None:
        return _optional_aware(value)


class FieldObservation(ContextModel):
    """A single observed value with an explicit presence state."""

    name: str = Field(min_length=1, max_length=200)
    value: JsonScalar = None
    state: ValueState
    source: str | None = Field(default=None, max_length=200)
    observedAt: datetime | None = None
    freshness: Freshness = Freshness.UNKNOWN

    @field_validator("observedAt")
    @classmethod
    def observed_aware(cls, value: datetime | None) -> datetime | None:
        return _optional_aware(value)

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: JsonScalar) -> JsonScalar:
        if isinstance(value, float):
            return _finite(value)
        return value


class ContextObservation(ContextModel):
    """A named canonical section plus its observed fields."""

    meta: SectionMeta
    fields: tuple[FieldObservation, ...] = ()


class GeneratorInfo(ContextModel):
    name: str = GENERATOR_NAME
    version: str = GENERATOR_VERSION
    components: tuple[str, ...] = (
        "source-truth-reader",
        "runtime-truth-adapter",
        "project-truth-registry",
        "canonical-context-builder",
    )


class WorktreeInfo(ContextModel):
    path: str = Field(min_length=1, max_length=1000)
    branch: str | None = Field(default=None, max_length=300)
    head: str | None = Field(default=None, max_length=64)


class SourceTruth(ContextModel):
    """READ-ONLY Git source facts.

    ``deployedCommit`` is only populated when an explicit, externally supplied
    value is passed to the reader.  The local HEAD is never treated as the
    Production deployed commit.
    """

    repository: str | None = Field(default=None, max_length=1000)
    repositoryAvailability: Availability = Availability.UNKNOWN
    branch: str | None = Field(default=None, max_length=300)
    head: str | None = Field(default=None, max_length=64)
    originMain: str | None = Field(default=None, max_length=64)
    ahead: int | None = Field(default=None, ge=0)
    behind: int | None = Field(default=None, ge=0)
    dirty: bool | None = None
    worktrees: tuple[WorktreeInfo, ...] = ()
    deployedCommit: str | None = Field(default=None, max_length=64)
    deployedCommitState: Availability = Availability.UNKNOWN
    deployedCommitEvidence: str | None = Field(default=None, max_length=500)
    meta: SectionMeta


class ContractRecord(ContextModel):
    contractId: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    owner: str = Field(default="UNKNOWN", max_length=200)
    status: WorkstreamStatus = WorkstreamStatus.UNKNOWN
    documentPath: str | None = Field(default=None, max_length=500)
    verified: bool = False
    references: tuple[str, ...] = ()


class WorkstreamRecord(ContextModel):
    workstreamId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    owner: str = Field(default="UNKNOWN", max_length=200)
    branch: str | None = Field(default=None, max_length=300)
    worktree: str | None = Field(default=None, max_length=1000)
    status: WorkstreamStatus = WorkstreamStatus.UNKNOWN
    verification: VerificationState = VerificationState.UNVERIFIED
    acceptedContracts: tuple[str, ...] = ()
    knownIssues: tuple[str, ...] = ()
    acceptedTests: tuple[str, ...] = ()
    decisionReferences: tuple[str, ...] = ()
    evidenceReferences: tuple[str, ...] = ()
    lastVerified: datetime | None = None

    @field_validator("lastVerified")
    @classmethod
    def verified_aware(cls, value: datetime | None) -> datetime | None:
        return _optional_aware(value)

    @model_validator(mode="after")
    def no_unverified_completion(self) -> "WorkstreamRecord":
        if (
            self.status in {WorkstreamStatus.COMPLETE, WorkstreamStatus.DEPLOYED}
            and self.verification is not VerificationState.VERIFIED
        ):
            raise ValueError(
                "COMPLETE/DEPLOYED requires VERIFIED evidence-backed registration"
            )
        if self.verification is VerificationState.VERIFIED:
            if self.lastVerified is None or not self.evidenceReferences:
                raise ValueError(
                    "VERIFIED requires lastVerified and evidenceReferences"
                )
        return self


class KnownIssueRecord(ContextModel):
    issueId: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    workstream: str = Field(default="UNKNOWN", max_length=100)
    status: IssueStatus = IssueStatus.UNKNOWN
    references: tuple[str, ...] = ()
    verified: bool = False


class AcceptedTestRecord(ContextModel):
    testId: str = Field(min_length=1, max_length=200)
    command: str | None = Field(default=None, max_length=500)
    workstream: str = Field(default="UNKNOWN", max_length=100)
    status: TestStatus = TestStatus.UNKNOWN
    references: tuple[str, ...] = ()
    verified: bool = False


def _unique(values: tuple[str, ...], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


class ProjectTruth(ContextModel):
    """PROJECT / DECISION truth loaded from the project registry document."""

    schemaVersion: str = PROJECT_SCHEMA_VERSION
    updatedAt: datetime | None = None
    workstreams: tuple[WorkstreamRecord, ...] = ()
    contracts: tuple[ContractRecord, ...] = ()
    knownIssues: tuple[KnownIssueRecord, ...] = ()
    acceptedTests: tuple[AcceptedTestRecord, ...] = ()
    meta: SectionMeta

    @field_validator("schemaVersion")
    @classmethod
    def schema_version_fixed(cls, value: str) -> str:
        if value != PROJECT_SCHEMA_VERSION:
            raise ValueError(f"schemaVersion must be {PROJECT_SCHEMA_VERSION}")
        return value

    @field_validator("updatedAt")
    @classmethod
    def updated_aware(cls, value: datetime | None) -> datetime | None:
        return _optional_aware(value)

    @model_validator(mode="after")
    def identifiers_unique(self) -> "ProjectTruth":
        _unique(tuple(item.workstreamId for item in self.workstreams), "workstreamId")
        _unique(tuple(item.contractId for item in self.contracts), "contractId")
        _unique(tuple(item.issueId for item in self.knownIssues), "issueId")
        _unique(tuple(item.testId for item in self.acceptedTests), "testId")
        return self


class WorkstreamsSection(ContextModel):
    meta: SectionMeta
    items: tuple[WorkstreamRecord, ...] = ()


class ContractsSection(ContextModel):
    meta: SectionMeta
    items: tuple[ContractRecord, ...] = ()


class KnownIssuesSection(ContextModel):
    meta: SectionMeta
    items: tuple[KnownIssueRecord, ...] = ()


class AcceptedTestsSection(ContextModel):
    meta: SectionMeta
    items: tuple[AcceptedTestRecord, ...] = ()


class SafetyContext(ContextModel):
    """Fixed, non-negotiable authority boundary for Phase 1."""

    contextRead: bool = True
    sourceWrite: bool = False
    runtimeWrite: bool = False
    orderWrite: bool = False
    liveOrder: bool = False
    productionDeploy: bool = False
    secretsIncluded: bool = False
    paperLiveAuthorityUnchanged: bool = True
    botManualAuthorityUnchanged: bool = True
    emergencyStateUnchanged: bool = True


class FreshnessSummary(ContextModel):
    overall: Freshness = Freshness.UNKNOWN
    availability: Availability = Availability.UNKNOWN
    evaluatedAt: datetime | None = None
    staleSections: tuple[str, ...] = ()
    unknownSections: tuple[str, ...] = ()
    unavailableSections: tuple[str, ...] = ()
    sectionCount: int = Field(default=0, ge=0)

    @field_validator("evaluatedAt")
    @classmethod
    def evaluated_aware(cls, value: datetime | None) -> datetime | None:
        return _optional_aware(value)


class ProvenanceSummary(ContextModel):
    entries: tuple[ProvenanceEntry, ...] = ()


class CanonicalContext(ContextModel):
    """The single canonical Context Pack exchanged between AI components."""

    schemaVersion: str = SCHEMA_VERSION
    generatedAt: datetime
    generator: GeneratorInfo = Field(default_factory=GeneratorInfo)
    source: SourceTruth
    runtime: ContextObservation
    marketSelection: ContextObservation
    executionControl: ContextObservation
    market: ContextObservation
    moneyManagement: ContextObservation
    governance: ContextObservation
    tradingCycle: ContextObservation
    position: ContextObservation
    orders: ContextObservation
    smallAccount: ContextObservation
    account: ContextObservation
    emergency: ContextObservation
    health: ContextObservation
    contracts: ContractsSection
    workstreams: WorkstreamsSection
    knownIssues: KnownIssuesSection
    acceptedTests: AcceptedTestsSection
    safety: SafetyContext = Field(default_factory=SafetyContext)
    freshness: FreshnessSummary
    provenance: ProvenanceSummary

    @field_validator("schemaVersion")
    @classmethod
    def schema_version_fixed(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schemaVersion must be {SCHEMA_VERSION}")
        return value

    @field_validator("generatedAt")
    @classmethod
    def generated_aware(cls, value: datetime) -> datetime:
        return _aware(value)


def empty_meta(
    *,
    source: str,
    availability: Availability = Availability.UNKNOWN,
    freshness: Freshness = Freshness.UNKNOWN,
    observed_at: datetime | None = None,
    detail: str | None = None,
) -> SectionMeta:
    return SectionMeta(
        source=source,
        observedAt=observed_at,
        freshness=freshness,
        availability=availability,
        provenance=(
            ProvenanceEntry(
                source=source,
                reader="canonical-context",
                observedAt=observed_at,
                detail=detail,
            ),
        ),
        detail=detail,
    )


def unavailable_observation(
    source: str,
    *,
    observed_at: datetime | None = None,
    detail: str = "section was not observable in Phase 1",
) -> ContextObservation:
    return ContextObservation(
        meta=empty_meta(
            source=source,
            availability=Availability.UNAVAILABLE,
            freshness=Freshness.UNKNOWN,
            observed_at=observed_at,
            detail=detail,
        ),
        fields=(),
    )


def unavailable_source_truth(observed_at: datetime | None = None) -> SourceTruth:
    return SourceTruth(
        repository=None,
        repositoryAvailability=Availability.UNAVAILABLE,
        branch=None,
        head=None,
        originMain=None,
        ahead=None,
        behind=None,
        dirty=None,
        worktrees=(),
        deployedCommit=None,
        deployedCommitState=Availability.UNKNOWN,
        deployedCommitEvidence=None,
        meta=empty_meta(
            source="git",
            availability=Availability.UNAVAILABLE,
            freshness=Freshness.UNKNOWN,
            observed_at=observed_at,
            detail="source truth was not supplied to the builder",
        ),
    )


def empty_project_truth(
    observed_at: datetime | None = None,
    *,
    availability: Availability = Availability.UNAVAILABLE,
    detail: str = "project registry was not supplied to the builder",
) -> ProjectTruth:
    meta = empty_meta(
        source="project-registry",
        availability=availability,
        freshness=Freshness.UNKNOWN,
        observed_at=observed_at,
        detail=detail,
    )
    return ProjectTruth(
        schemaVersion=PROJECT_SCHEMA_VERSION,
        updatedAt=None,
        workstreams=(),
        contracts=(),
        knownIssues=(),
        acceptedTests=(),
        meta=meta,
    )
