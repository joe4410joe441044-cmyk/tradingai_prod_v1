"""Read-only worktree observation.

Only paths returned by Git or named by an explicit source are observed, and
only when they are inside the configured worktree allowlist. Uncommitted file
contents are never read; only filtered status lines are kept.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from ..git_collector import default_git_runner
from ..provenance import stamp
from ..security import secret_filename, valid_commit_sha
from .models import (
    WORKTREE_CLEAN,
    WORKTREE_DETACHED,
    WORKTREE_DIRTY,
    WORKTREE_MISSING,
    WORKTREE_UNREACHABLE,
    SyncLimits,
    WorktreeObservation,
)


_STATUS_ARGS = ("status", "--porcelain=v1", "--untracked-files=no")
_WORKTREE_LIST_ARGS = ("worktree", "list", "--porcelain")
_MISSING_HEAD = None


def normalize_branch(branch: str | None) -> str | None:
    if branch in {None, "", "DETACHED"}:
        return None
    if branch.startswith("refs/heads/"):
        return branch[len("refs/heads/") :]
    if branch.startswith("refs/"):
        return None
    return branch


def _status_lines(path: Path, *, timeout: float, limit: int, runner) -> tuple[str, ...]:
    try:
        completed = runner(path, _STATUS_ARGS, timeout)
    except (OSError, subprocess.SubprocessError):
        return ()
    if not isinstance(completed, subprocess.CompletedProcess) or completed.returncode != 0:
        return ()
    lines: list[str] = []
    for raw in (completed.stdout or "").splitlines():
        if len(raw) < 4:
            continue
        candidate = raw[3:].strip().replace("\\", "/")
        leaf = candidate.rsplit("/", 1)[-1]
        if not candidate or secret_filename(leaf) or leaf.startswith("."):
            continue
        if ".." in candidate.split("/"):
            continue
        lines.append(raw[:3] + candidate)
        if len(lines) >= limit:
            break
    return tuple(lines)


def list_worktrees(repository: Path, *, timeout: float, runner) -> tuple[tuple[str, str | None, str | None], ...]:
    """Return ``(path, head, branch)`` rows from a bounded read-only call."""

    try:
        completed = runner(Path(repository), _WORKTREE_LIST_ARGS, timeout)
    except (OSError, subprocess.SubprocessError):
        return ()
    if not isinstance(completed, subprocess.CompletedProcess) or completed.returncode != 0:
        return ()
    rows: list[tuple[str, str | None, str | None]] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if current.get("worktree"):
            head = current.get("HEAD")
            if head is not None and not valid_commit_sha(head):
                head = None
            rows.append((current["worktree"], head, current.get("branch")))
        current.clear()

    for line in (completed.stdout or "").splitlines():
        if line.startswith("worktree "):
            flush()
            current["worktree"] = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].strip()
        elif line == "detached":
            current["branch"] = "DETACHED"
        elif line == "":
            flush()
    flush()
    return tuple(rows)


def worktree_allowed(path: Path, repository: Path, limits: SyncLimits) -> bool:
    requested = Path(path)
    if requested.is_symlink():
        return False
    try:
        resolved = requested.resolve(strict=False)
        repository_resolved = Path(repository).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    if resolved == repository_resolved:
        return True
    for root in limits.allowed_worktree_roots:
        try:
            root_resolved = Path(root).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if root_resolved in {Path("/"), Path("/tmp"), Path.home()}:
            continue
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return True
    return False


def observe_worktree(
    worktree_path: str | Path,
    *,
    repository_id: str,
    head: str | None,
    branch: str | None,
    limits: SyncLimits,
    runner=default_git_runner,
    clock=None,
) -> WorktreeObservation:
    path = Path(worktree_path)
    observed_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    normalized_branch = normalize_branch(branch)
    if path.is_symlink():
        return WorktreeObservation(
            repository_id=repository_id,
            worktree_path=str(path),
            branch=normalized_branch,
            head=head if head and valid_commit_sha(head) else _MISSING_HEAD,
            state=WORKTREE_UNREACHABLE,
            observed_at=observed_at,
            clean=None,
            missing=True,
        )
    if not path.exists() or not path.is_dir():
        return WorktreeObservation(
            repository_id=repository_id,
            worktree_path=str(path),
            branch=normalized_branch,
            head=head if head and valid_commit_sha(head) else _MISSING_HEAD,
            state=WORKTREE_MISSING,
            observed_at=observed_at,
            clean=None,
            missing=True,
        )
    lines = _status_lines(
        path,
        timeout=limits.max_git_command_seconds,
        limit=50,
        runner=runner,
    )
    clean = not lines
    if normalized_branch is None:
        state = WORKTREE_DETACHED
    else:
        state = WORKTREE_CLEAN if clean else WORKTREE_DIRTY
    return WorktreeObservation(
        repository_id=repository_id,
        worktree_path=str(path),
        branch=normalized_branch,
        head=head if head and valid_commit_sha(head) else None,
        state=state,
        observed_at=observed_at,
        clean=clean,
        status_lines=lines,
        missing=False,
    )
