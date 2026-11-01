"""Map detected development history into BC-3 store items.

The store keeps its own allowed truth vocabulary. The semantic truth class
requested by the continuous-sync design is preserved in ``metadata`` so a
``DEVELOPMENT_HISTORY`` or ``OBSERVED_SOURCE_STATE`` record never claims to
be runtime truth.
"""

from __future__ import annotations

import hashlib

from ..knowledge_store import StoreItem
from ..security import secret_bytes, valid_commit_sha
from .models import (
    ACCESS_SCOPE,
    AGENT_CURSOR,
    AGENT_EXPLICIT,
    AGENT_VSCODE,
    REPORT_KEEP_STATUSES,
    TRUST_LABEL,
    TRUTH_CLASS_AGENT_REPORTED_HISTORY,
    TRUTH_CLASS_DEVELOPMENT_HISTORY,
    TRUTH_CLASS_OBSERVED_SOURCE_STATE,
    WORKTREE_MISSING,
    WORKTREE_UNREACHABLE,
    CommitObservation,
    ReportCandidate,
    WorktreeObservation,
)


_PLACEHOLDER = "UNKNOWN"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe(value: str | None, limit: int = 300) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().replace("\x00", "")
    if not cleaned or cleaned == _PLACEHOLDER:
        return None
    return cleaned[:limit]


def _report_source_type(agent: str) -> str:
    if agent == AGENT_CURSOR:
        return "CURSOR_REPORT"
    if agent == AGENT_VSCODE:
        return "VSCODE_REPORT"
    if agent == AGENT_EXPLICIT:
        return "DEVELOPMENT_REPORT"
    return "DEVELOPMENT_REPORT"


def commit_item(commit: CommitObservation) -> StoreItem | None:
    if not valid_commit_sha(commit.sha):
        return None
    subject = _safe(commit.subject) or "REDACTED"
    lines = [
        f"COMMIT {commit.sha}",
        f"SUBJECT {subject}",
    ]
    if commit.parent_sha:
        lines.append(f"PARENT {commit.parent_sha}")
    if commit.branch:
        lines.append(f"BRANCH {commit.branch}")
    if commit.committed_at:
        lines.append(f"COMMITTED_AT {commit.committed_at}")
    lines.append(f"OBSERVED_WORKTREE {commit.worktree_path}")
    for path in commit.changed_paths:
        lines.append(f"CHANGED {path}")
    content = "\n".join(lines)
    if secret_bytes(content.encode("utf-8")):
        return None
    title = f"GIT_COMMIT {commit.sha[:12]} {subject}"[:300]
    if secret_bytes(title.encode("utf-8")):
        return None
    return StoreItem(
        source_type="GIT_COMMIT",
        source_identifier=commit.sha,
        record_type="GIT_COMMIT",
        title=title,
        content=content,
        content_hash=_digest(content),
        collected_at=commit.committed_at or "",
        verification_state="COLLECTED",
        truth_kind="GIT_VERIFIED",
        commit_sha=commit.sha,
        branch=commit.branch,
        worktree=None,
        source_timestamp=commit.committed_at,
        observed_at=commit.committed_at,
        metadata={
            "access_scope": ACCESS_SCOPE,
            "truth_class": TRUTH_CLASS_DEVELOPMENT_HISTORY,
            "trust": TRUST_LABEL,
            "source_agent": "GIT",
            "repository_id": commit.repository_id,
            "observed_worktree": commit.worktree_path,
            "change_reference_count": str(len(commit.changed_paths)),
        },
    )


def worktree_item(observation: WorktreeObservation) -> StoreItem | None:
    lines = [
        f"WORKTREE {observation.worktree_path}",
        f"STATE {observation.state}",
    ]
    if observation.branch:
        lines.append(f"BRANCH {observation.branch}")
    if observation.head:
        lines.append(f"HEAD {observation.head}")
    if observation.clean is not None:
        lines.append(f"CLEAN {'YES' if observation.clean else 'NO'}")
    if observation.history_rewrite_observed:
        lines.append("HISTORY_REWRITE_OBSERVED YES")
    for status_line in observation.status_lines:
        lines.append(f"STATUS {status_line}")
    content = "\n".join(lines)
    if secret_bytes(content.encode("utf-8")):
        return None
    title = f"WORKTREE {observation.worktree_path}"[:300]
    missing = observation.missing or observation.state in {WORKTREE_MISSING, WORKTREE_UNREACHABLE}
    return StoreItem(
        source_type="GIT_WORKTREE",
        source_identifier=observation.worktree_path,
        record_type="WORKTREE_OBSERVATION",
        title=title,
        content=content,
        content_hash=_digest(content),
        collected_at=observation.observed_at,
        verification_state="UNVERIFIED" if missing else "COLLECTED",
        truth_kind="UNKNOWN" if missing else "GIT_VERIFIED",
        commit_sha=observation.head,
        branch=observation.branch,
        worktree=observation.worktree_path,
        observed_at=observation.observed_at,
        metadata={
            "access_scope": ACCESS_SCOPE,
            "truth_class": TRUTH_CLASS_OBSERVED_SOURCE_STATE,
            "trust": TRUST_LABEL,
            "source_agent": "GIT",
            "repository_id": observation.repository_id,
            "worktree_state": observation.state,
            "missing": "YES" if missing else "NO",
            "history_rewrite_observed": "YES" if observation.history_rewrite_observed else "NO",
        },
    )


def _report_content(candidate: ReportCandidate, max_bytes: int) -> str | None:
    if candidate.text:
        text = candidate.text[:max_bytes]
        if secret_bytes(text.encode("utf-8")):
            return None
        return text or None
    parts = []
    for key in sorted(candidate.fields):
        value = candidate.fields[key]
        if not value or value == _PLACEHOLDER:
            continue
        parts.append(f"{key}: {value}")
    content = "\n".join(parts).strip()
    if not content or secret_bytes(content.encode("utf-8")):
        return None
    return content[:max_bytes]


def report_item(candidate: ReportCandidate, *, max_content_bytes: int = 131_072) -> StoreItem | None:
    if candidate.status not in REPORT_KEEP_STATUSES:
        return None
    content = _report_content(candidate, max_content_bytes)
    if content is None:
        return None
    agent = candidate.source_agent
    source_type = _report_source_type(agent)
    record_type = (
        "DEVELOPMENT_DECISION"
        if "decision" in candidate.relative_path.lower()
        else "DEVELOPMENT_REPORT"
    )
    title = candidate.relative_path[:300]
    if secret_bytes(title.encode("utf-8")):
        return None
    fields = candidate.fields or {}
    commit_sha = fields.get("COMMIT_SHA")
    if commit_sha is not None and not valid_commit_sha(commit_sha):
        commit_sha = None
    branch = _safe(fields.get("BRANCH"), 200)
    worktree = _safe(fields.get("WORKTREE"), 400)
    reported_at = _safe(fields.get("REPORTED_AT"), 80)
    workstream = _safe(fields.get("WORKSTREAM"), 120)
    metadata = {
        "access_scope": ACCESS_SCOPE,
        "truth_class": TRUTH_CLASS_AGENT_REPORTED_HISTORY,
        "trust": TRUST_LABEL,
        "source_agent": agent,
        "report_path": candidate.relative_path,
        "task_id": fields.get("TASK_ID", _PLACEHOLDER),
        "phase": fields.get("PHASE", _PLACEHOLDER),
        "verdict": fields.get("VERDICT", _PLACEHOLDER),
        "claimed_verdict": fields.get("VERDICT", _PLACEHOLDER),
        "next_recommended_task": fields.get("NEXT_RECOMMENDED_TASK", _PLACEHOLDER),
        "runtime_truth": "NOT_ASSERTED",
    }
    return StoreItem(
        source_type=source_type,
        source_identifier=candidate.relative_path,
        record_type=record_type,
        title=title,
        content=content,
        content_hash=candidate.content_hash or _digest(content),
        collected_at=candidate.observed_at,
        verification_state="COLLECTED",
        truth_kind="AGENT_REPORTED",
        relative_path=candidate.relative_path,
        commit_sha=commit_sha,
        branch=branch,
        worktree=worktree,
        reported_at=reported_at,
        observed_at=candidate.observed_at,
        workstream=workstream,
        metadata=metadata,
    )


def item_size(item: StoreItem) -> int:
    return len(item.content.encode("utf-8")) + len(item.title.encode("utf-8")) + 512
