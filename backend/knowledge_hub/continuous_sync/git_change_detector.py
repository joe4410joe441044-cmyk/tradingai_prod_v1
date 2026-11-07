"""Read-only Git change detection.

Only fixed Git argument vectors are passed to the BC-2 runner. A caller
cannot supply arbitrary Git text. Commit metadata is normalized so one commit
is one record regardless of how many worktrees reference it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from ..config import CollectorConfig
from ..git_collector import collect_git, default_git_runner, read_head
from ..provenance import stamp
from ..security import valid_commit_sha
from .models import (
    SCAN_MISSING,
    SCAN_OK,
    SCAN_PARTIAL,
    SCAN_REJECTED,
    SOURCE_KIND_REPOSITORY,
    CommitObservation,
    SourceScan,
    SyncLimits,
    WorktreeObservation,
)
from .worktree_tracker import (
    list_worktrees,
    normalize_branch,
    observe_worktree,
    worktree_allowed,
)


def validate_repository(path: Path, limits: SyncLimits) -> str | None:
    requested = Path(path)
    if requested.is_symlink():
        return "SYMLINK_REJECTED"
    if not requested.exists() or not requested.is_dir():
        return "SOURCE_NOT_FOUND"
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError):
        return "PATH_REJECTED"
    roots = limits.allowed_repository_roots
    if not roots:
        if resolved in {Path("/"), Path("/tmp"), Path.home()}:
            return "SOURCE_NOT_ALLOWLISTED"
        return None
    for root in roots:
        candidate = Path(root)
        if candidate.is_symlink():
            continue
        try:
            root_resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if root_resolved in {Path("/"), Path("/tmp"), Path.home()}:
            continue
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return None
    return "SOURCE_NOT_ALLOWLISTED"


def _is_ancestor(
    repository: Path,
    older: str,
    newer: str,
    *,
    timeout: float,
    runner,
) -> bool | None:
    if not valid_commit_sha(older) or not valid_commit_sha(newer):
        return None
    try:
        completed = runner(repository, ("merge-base", "--is-ancestor", older, newer), timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if not isinstance(completed, subprocess.CompletedProcess):
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


def _observation_key(observation: WorktreeObservation) -> tuple[str, str, str | None, str | None]:
    return (
        observation.worktree_path,
        observation.state,
        observation.branch,
        observation.head,
    )


def scan_repository(
    source,
    *,
    limits: SyncLimits,
    config: CollectorConfig,
    checkpoint: dict | None = None,
    known_commits: frozenset[str] = frozenset(),
    clock=None,
    runner=default_git_runner,
) -> SourceScan:
    collected_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    root = Path(source.path)
    code = validate_repository(root, limits)
    if code is not None:
        status = SCAN_MISSING if code == "SOURCE_NOT_FOUND" else SCAN_REJECTED
        observations = ()
        if status == SCAN_MISSING:
            observations = (
                observe_worktree(
                    root,
                    repository_id=source.source_id,
                    head=None,
                    branch=None,
                    limits=limits,
                    runner=runner,
                    clock=clock,
                ),
            )
        return SourceScan(
            source_id=source.source_id,
            kind=SOURCE_KIND_REPOSITORY,
            status=status,
            error=code,
            worktrees=observations,
        )
    batch = collect_git(root, config=config, runner=runner, clock=clock)
    if batch.error == "SOURCE_ROOT_NOT_FOUND":
        return SourceScan(
            source_id=source.source_id,
            kind=SOURCE_KIND_REPOSITORY,
            status=SCAN_MISSING,
            error=batch.error,
            worktrees=(
                observe_worktree(
                    root,
                    repository_id=source.source_id,
                    head=None,
                    branch=None,
                    limits=limits,
                    runner=runner,
                    clock=clock,
                ),
            ),
        )
    if not batch.records:
        return SourceScan(
            source_id=source.source_id,
            kind=SOURCE_KIND_REPOSITORY,
            status=SCAN_REJECTED,
            error=batch.error or "GIT_READ_FAILED",
        )

    commits: list[CommitObservation] = []
    branch: str | None = None
    head = read_head(root, config=config, runner=runner)
    for record in batch.records:
        provenance = record.provenance
        if provenance.record_type == "GIT_COMMIT" and record.collection_status == "METADATA_ONLY":
            sha = provenance.commit_sha
            if sha is None or not valid_commit_sha(sha):
                continue
            fields = record.fields or {}
            parent = fields.get("parent_sha") or None
            if parent is not None and not valid_commit_sha(parent):
                parent = None
            changed = tuple(
                path
                for path in (fields.get("changed_paths") or "").splitlines()
                if path.strip()
            )
            if branch is None and provenance.branch:
                branch = provenance.branch
            commits.append(
                CommitObservation(
                    repository_id=source.source_id,
                    worktree_path=str(root),
                    branch=provenance.branch,
                    sha=sha,
                    parent_sha=parent,
                    committed_at=provenance.source_timestamp,
                    subject=fields.get("subject") or "REDACTED",
                    changed_paths=changed,
                )
            )

    worktree_rows = list(
        list_worktrees(
            root,
            timeout=limits.max_git_command_seconds,
            runner=runner,
        )
    )

    for path, row_head, row_branch in worktree_rows:
        if Path(path).resolve(strict=False) == root.resolve(strict=False):
            branch = normalize_branch(row_branch)
            if row_head and valid_commit_sha(row_head):
                head = row_head
            break
    if branch is None and commits and commits[0].branch:
        branch = commits[0].branch

    history_rewrite = False
    if checkpoint:
        previous = checkpoint.get("last_seen_commit")
        previous_branch = checkpoint.get("branch")
        if (
            previous
            and valid_commit_sha(previous)
            and head
            and previous != head
            and (previous_branch is None or previous_branch == branch)
        ):
            ancestor = _is_ancestor(
                root,
                previous,
                head,
                timeout=limits.max_git_command_seconds,
                runner=runner,
            )
            history_rewrite = ancestor is False
    branch_changed = bool(
        checkpoint and checkpoint.get("branch") and branch and checkpoint.get("branch") != branch
    )

    observations: list[WorktreeObservation] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for path, row_head, row_branch in worktree_rows:
        if not worktree_allowed(Path(path), root, limits):
            continue
        observation = observe_worktree(
            path,
            repository_id=source.source_id,
            head=row_head,
            branch=row_branch,
            limits=limits,
            runner=runner,
            clock=clock,
        )
        key = _observation_key(observation)
        if key in seen:
            continue
        seen.add(key)
        observations.append(observation)
    if not observations:
        observations.append(
            observe_worktree(
                root,
                repository_id=source.source_id,
                head=head,
                branch=branch,
                limits=limits,
                runner=runner,
                clock=clock,
            )
        )
    if history_rewrite:
        observations = [
            WorktreeObservation(
                repository_id=observation.repository_id,
                worktree_path=observation.worktree_path,
                branch=observation.branch,
                head=observation.head,
                state=observation.state,
                observed_at=observation.observed_at,
                clean=observation.clean,
                status_lines=observation.status_lines,
                missing=observation.missing,
                history_rewrite_observed=True,
            )
            for observation in observations
        ]

    new_commits = tuple(commit for commit in commits if commit.sha not in known_commits)
    unchanged = len(commits) - len(new_commits)
    status = SCAN_PARTIAL if batch.stopped_reason else SCAN_OK
    return SourceScan(
        source_id=source.source_id,
        kind=SOURCE_KIND_REPOSITORY,
        status=status,
        error=batch.error,
        branch=branch,
        head=head,
        commits=tuple(commits),
        new_commits=new_commits,
        unchanged_commit_count=unchanged,
        worktrees=tuple(observations),
        branch_changed=branch_changed,
        history_rewrite_observed=history_rewrite,
        stopped_reason=batch.stopped_reason,
    )
