"""Isolated continuous sync for Cursor, VS Code, and Git development history.

Importing this package performs no scan, no Git call, no report read, no
database write, and no scheduler registration. A caller must invoke the
engine explicitly.
"""

from .git_change_detector import scan_repository
from .models import (
    ACCESS_SCOPE,
    AGENT_CURSOR,
    AGENT_EXPLICIT,
    AGENT_GIT,
    AGENT_VSCODE,
    REPORT_KEEP_STATUSES,
    SOURCE_KIND_REPORT_DIR,
    SOURCE_KIND_REPOSITORY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    SYNC_SCHEMA_VERSION,
    TRUST_LABEL,
    TRUTH_CLASS_AGENT_REPORTED_HISTORY,
    TRUTH_CLASS_DEVELOPMENT_HISTORY,
    TRUTH_CLASS_OBSERVED_SOURCE_STATE,
    TRUTH_CLASS_SOURCE,
    Checkpoint,
    CommitObservation,
    ExistingState,
    ReportCandidate,
    SourceScan,
    SourceSpec,
    SyncLimits,
    SyncPreview,
    SyncReport,
    WorktreeObservation,
)
from .normalizer import commit_item, report_item, worktree_item
from .report_scanner import scan_reports
from .sync_checkpoint import CheckpointStore
from .sync_engine import ContinuousSyncEngine, build_collector_config, scan_sources
from .sync_preview import preview_sync
from .worktree_tracker import observe_worktree


__all__ = [
    "ACCESS_SCOPE",
    "AGENT_CURSOR",
    "AGENT_EXPLICIT",
    "AGENT_GIT",
    "AGENT_VSCODE",
    "Checkpoint",
    "CheckpointStore",
    "CommitObservation",
    "ContinuousSyncEngine",
    "ExistingState",
    "REPORT_KEEP_STATUSES",
    "ReportCandidate",
    "SOURCE_KIND_REPORT_DIR",
    "SOURCE_KIND_REPOSITORY",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "SYNC_SCHEMA_VERSION",
    "SourceScan",
    "SourceSpec",
    "SyncLimits",
    "SyncPreview",
    "SyncReport",
    "TRUST_LABEL",
    "TRUTH_CLASS_AGENT_REPORTED_HISTORY",
    "TRUTH_CLASS_DEVELOPMENT_HISTORY",
    "TRUTH_CLASS_OBSERVED_SOURCE_STATE",
    "TRUTH_CLASS_SOURCE",
    "WorktreeObservation",
    "build_collector_config",
    "commit_item",
    "observe_worktree",
    "preview_sync",
    "report_item",
    "scan_reports",
    "scan_repository",
    "scan_sources",
    "worktree_item",
]
