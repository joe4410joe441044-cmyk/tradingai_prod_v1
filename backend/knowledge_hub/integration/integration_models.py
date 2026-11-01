"""Value objects for BC-8 integration acceptance and deployment readiness.

Nothing in this module reads a file, runs Git, or writes a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


VERDICT_PASS = "BC8_ISOLATED_INTEGRATION_ACCEPTANCE_COMPLETE"
VERDICT_PARTIAL = "BC8_ISOLATED_INTEGRATION_ACCEPTANCE_PARTIAL"
VERDICT_BLOCKED = "BC8_ISOLATED_INTEGRATION_ACCEPTANCE_BLOCKED"

STAGE_OK = "OK"
STAGE_FAILED = "FAILED"
STAGE_SKIPPED = "SKIPPED"

READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
CONDITIONAL_READY = "CONDITIONAL_READY"
NOT_READY = "NOT_READY"
READINESS_UNKNOWN = "UNKNOWN"

NEEDED = "NEEDED"
ALREADY_CANONICAL = "ALREADY_CANONICAL"
CONFLICTING = "CONFLICTING"
SUPERSEDED = "SUPERSEDED"
SHARED_PATH_REVIEW_REQUIRED = "SHARED_PATH_REVIEW_REQUIRED"
RECONCILIATION_UNKNOWN = "UNKNOWN"

MATCH = "MATCH"
MISMATCH = "MISMATCH"
SOURCE_MISSING = "SOURCE_MISSING"
NO_MISMATCH = "NO_MISMATCH"
SOURCE_CONTENT_CHANGED = "SOURCE_CONTENT_CHANGED"
PRE_EXISTING_MANIFEST_DRIFT = "PRE_EXISTING_MANIFEST_DRIFT"
TEST_FIXTURE_MISMATCH = "TEST_FIXTURE_MISMATCH"
ENVIRONMENT_DEPENDENCY = "ENVIRONMENT_DEPENDENCY"


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    detail: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True)
class IntegrationConfig:
    """Explicit caller-supplied paths. No production default is assumed."""

    workdir: Path
    store_path: Path
    repository: Path
    report_sources: tuple[tuple[Path, str], ...]
    account_a_export: Path
    account_b_export: Path
    account_a: str = "chatgpt_account_a"
    account_b: str = "chatgpt_account_b"
    refresh_a_export: Path | None = None
    refresh_b_export: Path | None = None
    indexed_at: str = "2026-11-01T01:00:00+00:00"
    observed_at: str = "2026-11-01T00:59:00+00:00"
    refresh_indexed_at: str = "2026-11-01T03:00:00+00:00"
    refresh_observed_at: str = "2026-11-01T02:59:00+00:00"
    search_question: str = "TradingAI"
    advisor_question: str = "TradingAI knowledge hub"
    supervisor_question: str = "TradingAI knowledge hub"
    bb_context: Mapping[str, Any] = field(
        default_factory=lambda: {
            "schemaVersion": "tradingai-context/v1",
            "runtimeState": "UNKNOWN",
            "authority": "READ_ONLY",
        }
    )


@dataclass(frozen=True)
class IntegrationResult:
    stages: tuple[StageResult, ...]
    store_path: str
    record_count: int
    source_type_counts: Mapping[str, int]
    search: Mapping[str, Any]
    advisor: Mapping[str, Any]
    supervisor: Mapping[str, Any]
    access: Mapping[str, Any]
    latencies: Mapping[str, float]
    bb_context: Mapping[str, Any]

    def stage(self, name: str) -> StageResult | None:
        for item in self.stages:
            if item.name == name:
                return item
        return None

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(
            item.name
            for item in self.stages
            if item.status not in {STAGE_OK, STAGE_SKIPPED}
        )

    @property
    def passed(self) -> bool:
        return bool(self.stages) and not self.failed_stages

    @property
    def verdict(self) -> str:
        if self.passed:
            return VERDICT_PASS
        if any(item.status == STAGE_OK for item in self.stages):
            return VERDICT_PARTIAL
        return VERDICT_BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "stages": [item.to_dict() for item in self.stages],
            "failed_stages": list(self.failed_stages),
            "store_path": self.store_path,
            "record_count": self.record_count,
            "source_type_counts": dict(self.source_type_counts),
            "search": dict(self.search),
            "advisor": dict(self.advisor),
            "supervisor": dict(self.supervisor),
            "access": dict(self.access),
            "latencies": dict(self.latencies),
            "bb_context": dict(self.bb_context),
        }


@dataclass(frozen=True)
class HashMismatchEntry:
    source_id: str
    relative_path: str
    expected_hash: str
    actual_hash: str | None
    status: str
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "status": self.status,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class HashMismatchClassification:
    entries: tuple[HashMismatchEntry, ...]
    source_manifest: str

    @property
    def matched(self) -> tuple[HashMismatchEntry, ...]:
        return tuple(item for item in self.entries if item.status == MATCH)

    @property
    def mismatched(self) -> tuple[HashMismatchEntry, ...]:
        return tuple(item for item in self.entries if item.status != MATCH)

    @property
    def classifications(self) -> tuple[str, ...]:
        return tuple(sorted({item.classification for item in self.mismatched}))

    @property
    def overall(self) -> str:
        if not self.mismatched:
            return NO_MISMATCH
        values = self.classifications
        if len(values) == 1:
            return values[0]
        return "MIXED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_manifest": self.source_manifest,
            "overall": self.overall,
            "matched_count": len(self.matched),
            "mismatched_count": len(self.mismatched),
            "entries": [item.to_dict() for item in self.entries],
        }


@dataclass(frozen=True)
class ReconciliationEntry:
    path: str
    git_status: str
    classification: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "git_status": self.git_status,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class CanonicalReconciliation:
    entries: tuple[ReconciliationEntry, ...]
    canonical_head: str
    worktree_head: str

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.entries:
            result[item.classification] = result.get(item.classification, 0) + 1
        return result

    @property
    def blocked(self) -> tuple[ReconciliationEntry, ...]:
        return tuple(
            item
            for item in self.entries
            if item.classification
            in {CONFLICTING, SHARED_PATH_REVIEW_REQUIRED, RECONCILIATION_UNKNOWN}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_head": self.canonical_head,
            "worktree_head": self.worktree_head,
            "counts": self.counts(),
            "blocked": [item.to_dict() for item in self.blocked],
            "entries": [item.to_dict() for item in self.entries],
        }


@dataclass(frozen=True)
class DeploymentReadiness:
    verdict: str
    blockers: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "blockers": list(self.blockers),
            "notes": list(self.notes),
        }
