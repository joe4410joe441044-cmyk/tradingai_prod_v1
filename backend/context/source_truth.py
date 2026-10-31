"""READ-ONLY Git Source Truth reader.

Only a fixed, internal set of Git subcommands is executed.  No argument is
interpolated into a shell and ``shell=True`` is never used, so an HTTP request
or user payload cannot inject arbitrary commands through this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence

from .schema import (
    Availability,
    Freshness,
    ProvenanceEntry,
    SectionMeta,
    SourceTruth,
    WorktreeInfo,
)

READER_NAME = "source-truth-reader"
_GIT_EXECUTABLE = "git"
_GIT_TIMEOUT_SECONDS = 10
_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
_WORKTREE_HEADER = "worktree "
_WORKTREE_HEAD = "HEAD "
_WORKTREE_BRANCH = "branch "


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_git(repository: Path, arguments: Sequence[str]) -> str | None:
    """Run one fixed Git argument vector and return stdout on success."""

    try:
        completed = subprocess.run(
            [_GIT_EXECUTABLE, "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_worktrees(output: str | None) -> tuple[WorktreeInfo, ...]:
    if not output:
        return ()
    worktrees: list[WorktreeInfo] = []
    current: dict[str, str | None] = {}

    def flush() -> None:
        path = current.get("path")
        if path:
            worktrees.append(
                WorktreeInfo(
                    path=path,
                    branch=current.get("branch"),
                    head=current.get("head"),
                )
            )
        current.clear()

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith(_WORKTREE_HEADER):
            if current.get("path"):
                flush()
            current["path"] = line[len(_WORKTREE_HEADER):].strip()
        elif line.startswith(_WORKTREE_HEAD):
            current["head"] = line[len(_WORKTREE_HEAD):].strip()
        elif line.startswith(_WORKTREE_BRANCH):
            branch = line[len(_WORKTREE_BRANCH):].strip()
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
            current["branch"] = branch
    flush()
    return tuple(worktrees)


def _divergence(repository: Path) -> tuple[int | None, int | None]:
    output = _run_git(
        repository, ("rev-list", "--left-right", "--count", "origin/main...HEAD")
    )
    if output is None:
        return None, None
    parts = output.split()
    if len(parts) != 2:
        return None, None
    try:
        behind = int(parts[0])
        ahead = int(parts[1])
    except ValueError:
        return None, None
    if behind < 0 or ahead < 0:
        return None, None
    return ahead, behind


def read_source_truth(
    repository: str | Path,
    *,
    deployed_commit: str | None = None,
    observed_at: datetime | None = None,
    clock: Callable[[], datetime] = _now,
) -> SourceTruth:
    """Read Git state without mutating it.

    ``deployed_commit`` is accepted only when a caller has independent
    Production evidence.  It is never derived from the local HEAD.
    """

    if not isinstance(repository, (str, Path)):
        raise TypeError("repository must be a path")
    path = Path(repository).expanduser()
    if not path.is_dir():
        raise ValueError("repository path must be an existing directory")
    path = path.resolve()

    if deployed_commit is not None:
        if not isinstance(deployed_commit, str) or not _SHA_PATTERN.match(
            deployed_commit.strip().lower()
        ):
            raise ValueError("deployed_commit must be a hexadecimal commit id")

    observed = observed_at if observed_at is not None else clock()
    if (
        not isinstance(observed, datetime)
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        raise ValueError("observed_at must be timezone-aware")
    observed = observed.astimezone(timezone.utc)

    top_level = _clean(_run_git(path, ("rev-parse", "--show-toplevel")))
    branch = _clean(_run_git(path, ("branch", "--show-current")))
    head = _clean(_run_git(path, ("rev-parse", "--verify", "--quiet", "HEAD")))
    origin_main = _clean(
        _run_git(path, ("rev-parse", "--verify", "--quiet", "origin/main"))
    )
    status_output = _run_git(
        path, ("status", "--porcelain=v1", "--untracked-files=normal")
    )
    dirty = None if status_output is None else bool(status_output.strip())
    ahead, behind = _divergence(path)
    worktrees = _parse_worktrees(
        _run_git(path, ("worktree", "list", "--porcelain"))
    )

    if head is not None:
        availability = Availability.AVAILABLE
        freshness = Freshness.FRESH
    else:
        availability = Availability.UNKNOWN
        freshness = Freshness.UNKNOWN

    if deployed_commit is not None:
        deployed_value: str | None = deployed_commit.strip().lower()
        deployed_state = Availability.AVAILABLE
        deployed_evidence = "explicit caller-supplied Production evidence"
    else:
        deployed_value = None
        deployed_state = Availability.UNKNOWN
        deployed_evidence = None

    meta = SectionMeta(
        source="git",
        observedAt=observed,
        freshness=freshness,
        availability=availability,
        provenance=(
            ProvenanceEntry(
                source="git",
                reader=READER_NAME,
                observedAt=observed,
                detail="read-only fixed argument Git inspection",
            ),
        ),
    )

    return SourceTruth(
        repository=top_level or str(path),
        repositoryAvailability=availability,
        branch=branch,
        head=head,
        originMain=origin_main,
        ahead=ahead,
        behind=behind,
        dirty=dirty,
        worktrees=worktrees,
        deployedCommit=deployed_value,
        deployedCommitState=deployed_state,
        deployedCommitEvidence=deployed_evidence,
        meta=meta,
    )
