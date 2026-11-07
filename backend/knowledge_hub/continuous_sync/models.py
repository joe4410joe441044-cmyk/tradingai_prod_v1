"""Value objects for the continuous development-history synchronizer.

Importing this package does not scan a repository, run Git, read a report,
create a database, or contact a network. All bounds are explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import DEFAULT_REPORT_ROOTS


SYNC_SCHEMA_VERSION = "tradingai-continuous-sync/v1"

SOURCE_KIND_REPOSITORY = "REPOSITORY"
SOURCE_KIND_REPORT_DIR = "REPORT_DIR"

AGENT_GIT = "GIT"
AGENT_CURSOR = "CURSOR"
AGENT_VSCODE = "VSCODE"
AGENT_EXPLICIT = "EXPLICIT"

TRUTH_CLASS_SOURCE = "SOURCE_TRUTH"
TRUTH_CLASS_DEVELOPMENT_HISTORY = "DEVELOPMENT_HISTORY"
TRUTH_CLASS_OBSERVED_SOURCE_STATE = "OBSERVED_SOURCE_STATE"
TRUTH_CLASS_AGENT_REPORTED_HISTORY = "AGENT_REPORTED_HISTORY"

ACCESS_SCOPE = "OPERATOR"
TRUST_LABEL = "UNTRUSTED_KNOWLEDGE"

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_ERROR = "ERROR"

SCAN_OK = "OK"
SCAN_MISSING = "MISSING"
SCAN_REJECTED = "REJECTED"
SCAN_PARTIAL = "PARTIAL"

WORKTREE_CLEAN = "CLEAN"
WORKTREE_DIRTY = "DIRTY"
WORKTREE_DETACHED = "DETACHED_HEAD"
WORKTREE_MISSING = "MISSING"
WORKTREE_UNREACHABLE = "UNREACHABLE"

REPORT_KEEP_STATUSES = frozenset({"METADATA_ONLY", "TEXT_INCLUDED", "UNSUPPORTED_ENCODING"})
REPORT_PRIVACY_STATUSES = frozenset({"SECRET_EXCLUDED"})


@dataclass(frozen=True)
class SourceSpec:
    """An explicitly allowlisted source. Nothing is discovered implicitly."""

    path: Path
    kind: str = SOURCE_KIND_REPOSITORY
    identifier: str | None = None
    agent: str | None = None

    @property
    def source_id(self) -> str:
        return self.identifier or str(self.path)


@dataclass(frozen=True)
class SyncLimits:
    max_repositories: int = 8
    max_worktrees: int = 20
    max_commit_scan_depth: int = 50
    max_report_files: int = 50
    max_report_file_bytes: int = 262_144
    max_report_content_bytes: int = 131_072
    max_batch_size: int = 200
    max_scan_seconds: float = 10.0
    max_database_growth_bytes: int = 5_000_000
    max_preview_entries: int = 100
    max_git_command_seconds: float = 5.0
    allowed_repository_roots: tuple[Path, ...] = ()
    allowed_worktree_roots: tuple[Path, ...] = ()
    allowed_report_roots: tuple[Path, ...] = DEFAULT_REPORT_ROOTS


@dataclass(frozen=True)
class CommitObservation:
    repository_id: str
    worktree_path: str
    branch: str | None
    sha: str
    parent_sha: str | None
    committed_at: str | None
    subject: str
    changed_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorktreeObservation:
    repository_id: str
    worktree_path: str
    branch: str | None
    head: str | None
    state: str
    observed_at: str
    clean: bool | None = None
    status_lines: tuple[str, ...] = ()
    missing: bool = False
    history_rewrite_observed: bool = False


@dataclass(frozen=True)
class ReportCandidate:
    path: Path
    relative_path: str
    source_agent: str
    status: str
    fields: dict[str, str]
    content_hash: str | None
    size_bytes: int | None
    text: str | None
    observed_at: str


@dataclass(frozen=True)
class SourceScan:
    source_id: str
    kind: str
    status: str
    error: str | None = None
    branch: str | None = None
    head: str | None = None
    commits: tuple[CommitObservation, ...] = ()
    new_commits: tuple[CommitObservation, ...] = ()
    unchanged_commit_count: int = 0
    worktrees: tuple[WorktreeObservation, ...] = ()
    reports: tuple[ReportCandidate, ...] = ()
    privacy_review_count: int = 0
    rejected_count: int = 0
    branch_changed: bool = False
    history_rewrite_observed: bool = False
    stopped_reason: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    source_kind: str
    source_id: str
    last_scan_at: str
    branch: str | None = None
    last_seen_commit: str | None = None
    report_path: str | None = None
    report_content_hash: str | None = None
    last_imported_version: str | None = None
    source_agent: str | None = None


@dataclass(frozen=True)
class ExistingState:
    record_ids: frozenset[str]
    by_logical: dict[str, frozenset[str]]


@dataclass(frozen=True)
class SyncPreview:
    status: str
    source_count: int
    repository_count: int
    worktree_count: int
    commit_candidate_count: int
    report_candidate_count: int
    new_record_count: int
    updated_record_count: int
    unchanged_record_count: int
    missing_source_count: int
    rejected_source_count: int
    privacy_review_count: int
    estimated_database_growth_bytes: int
    entries: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_count": self.source_count,
            "repository_count": self.repository_count,
            "worktree_count": self.worktree_count,
            "commit_candidate_count": self.commit_candidate_count,
            "report_candidate_count": self.report_candidate_count,
            "new_record_count": self.new_record_count,
            "updated_record_count": self.updated_record_count,
            "unchanged_record_count": self.unchanged_record_count,
            "missing_source_count": self.missing_source_count,
            "rejected_source_count": self.rejected_source_count,
            "privacy_review_count": self.privacy_review_count,
            "estimated_database_growth_bytes": self.estimated_database_growth_bytes,
            "entries": [dict(entry) for entry in self.entries],
            "error": self.error,
        }


@dataclass(frozen=True)
class SyncReport:
    status: str
    source_count: int
    repository_count: int
    worktree_count: int
    commit_count: int
    report_count: int
    inserted: int
    skipped: int
    superseded: int
    missing: int
    rejected: int
    missing_source_count: int
    rejected_source_count: int
    privacy_review_count: int
    branch_changes: int
    history_rewrites: int
    checkpoints_updated: int
    estimated_database_growth_bytes: int
    errors: tuple[str, ...] = ()
    rejected_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_count": self.source_count,
            "repository_count": self.repository_count,
            "worktree_count": self.worktree_count,
            "commit_count": self.commit_count,
            "report_count": self.report_count,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "superseded": self.superseded,
            "missing": self.missing,
            "rejected": self.rejected,
            "missing_source_count": self.missing_source_count,
            "rejected_source_count": self.rejected_source_count,
            "privacy_review_count": self.privacy_review_count,
            "branch_changes": self.branch_changes,
            "history_rewrites": self.history_rewrites,
            "checkpoints_updated": self.checkpoints_updated,
            "estimated_database_growth_bytes": self.estimated_database_growth_bytes,
            "errors": list(self.errors),
            "rejected_codes": list(self.rejected_codes),
        }
