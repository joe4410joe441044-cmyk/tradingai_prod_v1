"""Read-only Git metadata.

Arguments passed to Git are fixed vectors plus a SHA that has already
matched ``^[0-9a-f]{7,40}$``. The shell is not invoked. User text is
not accepted as an option.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Callable, Sequence

from .config import CollectorConfig
from .models import CollectionBatch, KnowledgeRecord
from .provenance import build_provenance, stamp
from .security import redact_text, secret_filename, valid_commit_sha


GitRunner = Callable[[Path, Sequence[str], float], subprocess.CompletedProcess[str]]

_LOG_FORMAT = "%H%x1f%cI%x1f%P%x1f%s"
_STATUS_ARGS = ("status", "--porcelain=v1", "--untracked-files=no")


def default_git_runner(
    repository: Path,
    args: Sequence[str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def _failed(collected_at: str, code: str, worktree: str | None = None) -> CollectionBatch:
    record = KnowledgeRecord(
        provenance=build_provenance(
            source_type="GIT_COMMIT",
            source_identifier=worktree or "git",
            collected_at=collected_at,
            truth_kind="UNKNOWN",
            record_type="GIT_COMMIT",
            verification_state="REJECTED",
            worktree=worktree,
        ),
        collection_status=code,
    )
    return CollectionBatch((record,), error=code)


def _owned_args(args: Sequence[str]) -> bool:
    allowed_prefix = {
        "rev-parse",
        "log",
        "worktree",
        "status",
        "diff-tree",
    }
    if not args or args[0] not in allowed_prefix:
        return False
    for arg in args[1:]:
        if arg.startswith("-") and arg not in {
            "--abbrev-ref",
            "--porcelain",
            "--porcelain=v1",
            "--untracked-files=no",
            "--no-commit-id",
            "--name-only",
            "--root",
            "-r",
            "HEAD",
        } and not arg.startswith("--format=") and not (
            arg.startswith("-n") and arg[2:].isdigit()
        ):
            return False
        if arg == "--" or "\x00" in arg or "\n" in arg:
            return False
    if args[0] == "diff-tree":
        sha = args[-1]
        return valid_commit_sha(sha)
    return True


def _invoke(
    runner: GitRunner,
    repository: Path,
    args: tuple[str, ...],
    timeout: float,
) -> subprocess.CompletedProcess[str] | None:
    if not _owned_args(args):
        return None
    try:
        completed = runner(repository, args, timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if not isinstance(completed, subprocess.CompletedProcess):
        return None
    return completed


def read_head(repository: Path, *, config: CollectorConfig, runner: GitRunner) -> str | None:
    completed = _invoke(
        runner,
        repository,
        ("rev-parse", "HEAD"),
        config.git_timeout_seconds,
    )
    if completed is None or completed.returncode != 0:
        return None
    sha = (completed.stdout or "").strip()
    if not valid_commit_sha(sha):
        return None
    return sha


def _branch(repository: Path, config: CollectorConfig, runner: GitRunner) -> str | None:
    completed = _invoke(
        runner,
        repository,
        ("rev-parse", "--abbrev-ref", "HEAD"),
        config.git_timeout_seconds,
    )
    if completed is None or completed.returncode != 0:
        return None
    name = (completed.stdout or "").strip()
    if not name or name == "HEAD" or name.startswith("-") or "\n" in name or len(name) > 200:
        return None
    return name


def _names(repository: Path, sha: str, config: CollectorConfig, runner: GitRunner) -> tuple[str, ...]:
    completed = _invoke(
        runner,
        repository,
        ("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha),
        config.git_timeout_seconds,
    )
    if completed is None or completed.returncode != 0:
        return ()
    names: list[str] = []
    for line in (completed.stdout or "").splitlines():
        candidate = line.strip().replace("\\", "/")
        if not candidate or candidate.startswith("-") or ".." in candidate.split("/"):
            continue
        leaf = candidate.rsplit("/", 1)[-1]
        if secret_filename(leaf) or leaf.startswith(".env"):
            continue
        names.append(candidate)
        if len(names) >= config.max_status_lines:
            break
    return tuple(names)


def _status_lines(repository: Path, config: CollectorConfig, runner: GitRunner) -> tuple[str, ...]:
    completed = _invoke(runner, repository, _STATUS_ARGS, config.git_timeout_seconds)
    if completed is None or completed.returncode != 0:
        return ()
    lines: list[str] = []
    for raw in (completed.stdout or "").splitlines():
        if len(raw) < 4:
            continue
        path = raw[3:].strip().replace("\\", "/")
        leaf = path.rsplit("/", 1)[-1]
        if secret_filename(leaf) or leaf.startswith("."):
            continue
        lines.append(raw[:3] + path)
        if len(lines) >= config.max_status_lines:
            break
    return tuple(lines)


def _parse_worktrees(stdout: str, limit: int) -> list[dict[str, str]] | None:
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if current.get("worktree") and current.get("HEAD"):
            rows.append(dict(current))
        current.clear()

    for line in stdout.splitlines():
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
        else:
            return None
    flush()
    if any(not valid_commit_sha(row.get("HEAD", "")) for row in rows):
        return None
    return rows[:limit]


def collect_commit(
    repository: Path,
    commit_sha: str,
    *,
    config: CollectorConfig | None = None,
    runner: GitRunner = default_git_runner,
    clock=None,
) -> CollectionBatch:
    """Read one commit's metadata. A non-SHA argument never reaches Git."""

    settings = config or CollectorConfig()
    collected_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    root = Path(repository)
    if not valid_commit_sha(commit_sha):
        return _failed(collected_at, "GIT_OPTION_REJECTED", str(root))
    if not root.is_dir() or root.is_symlink():
        return _failed(collected_at, "SOURCE_ROOT_NOT_FOUND", str(root))
    checked = _invoke(
        runner,
        root,
        ("log", "-n1", f"--format={_LOG_FORMAT}", commit_sha),
        settings.git_timeout_seconds,
    )
    if checked is None:
        return _failed(collected_at, "TIMEOUT", str(root))
    if checked.returncode != 0:
        return _failed(collected_at, "GIT_READ_FAILED", str(root))
    names = _names(root, commit_sha, settings, runner)
    record = KnowledgeRecord(
        provenance=build_provenance(
            source_type="GIT_COMMIT",
            source_identifier=commit_sha,
            collected_at=collected_at,
            truth_kind="GIT_VERIFIED",
            record_type="GIT_COMMIT",
            verification_state="COLLECTED",
            commit_sha=commit_sha,
            worktree=str(root),
            observed_at=collected_at,
        ),
        collection_status="METADATA_ONLY",
        fields={"changed_paths": "\n".join(names)},
    )
    return CollectionBatch((record,))


def collect_git(
    repository: Path,
    *,
    config: CollectorConfig | None = None,
    runner: GitRunner = default_git_runner,
    require_unique: bool = False,
    clock=None,
) -> CollectionBatch:
    """Collect bounded commit and worktree metadata for one repository."""

    settings = config or CollectorConfig()
    collected_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    root = Path(repository)
    if not root.is_dir() or root.is_symlink():
        return _failed(collected_at, "SOURCE_ROOT_NOT_FOUND", str(root))

    count = settings.max_commits if settings.max_commits > 0 else 1
    log = _invoke(
        runner,
        root,
        ("log", f"-n{count}", f"--format={_LOG_FORMAT}"),
        settings.git_timeout_seconds,
    )
    if log is None:
        return _failed(collected_at, "TIMEOUT", str(root))
    if log.returncode != 0:
        return _failed(collected_at, "GIT_READ_FAILED", str(root))

    branch = _branch(root, settings, runner)
    status_lines = _status_lines(root, settings, runner)
    records: list[KnowledgeRecord] = []
    for line in (log.stdout or "").splitlines():
        pieces = line.split("\x1f", 3)
        if len(pieces) != 4 or not valid_commit_sha(pieces[0]):
            records.append(
                KnowledgeRecord(
                    provenance=build_provenance(
                        source_type="GIT_COMMIT",
                        source_identifier="malformed",
                        collected_at=collected_at,
                        truth_kind="UNKNOWN",
                        record_type="GIT_COMMIT",
                        verification_state="UNVERIFIED",
                        worktree=str(root),
                    ),
                    collection_status="MALFORMED",
                )
            )
            continue
        sha, when, parents, subject = pieces
        parent = parents.split(" ")[0] if parents and valid_commit_sha(parents.split(" ")[0]) else ""
        safe_subject = redact_text(subject) or "REDACTED"
        changed = _names(root, sha, settings, runner)
        records.append(
            KnowledgeRecord(
                provenance=build_provenance(
                    source_type="GIT_COMMIT",
                    source_identifier=sha,
                    collected_at=collected_at,
                    truth_kind="GIT_VERIFIED",
                    record_type="GIT_COMMIT",
                    verification_state="COLLECTED",
                    commit_sha=sha,
                    branch=branch,
                    worktree=str(root),
                    observed_at=collected_at,
                    source_timestamp=when,
                ),
                collection_status="METADATA_ONLY",
                fields={
                    "subject": safe_subject,
                    "parent_sha": parent,
                    "changed_paths": "\n".join(changed),
                    "status": "\n".join(status_lines),
                },
            )
        )

    listing = _invoke(
        runner,
        root,
        ("worktree", "list", "--porcelain"),
        settings.git_timeout_seconds,
    )
    if listing is None:
        return CollectionBatch(tuple(records), error="TIMEOUT")
    parsed = _parse_worktrees(listing.stdout or "", settings.max_worktrees) if listing.returncode == 0 else None
    if parsed is None:
        records.append(
            KnowledgeRecord(
                provenance=build_provenance(
                    source_type="GIT_WORKTREE",
                    source_identifier=str(root),
                    collected_at=collected_at,
                    truth_kind="UNKNOWN",
                    record_type="GIT_WORKTREE",
                    verification_state="UNVERIFIED",
                    worktree=str(root),
                ),
                collection_status="MALFORMED",
            )
        )
        return CollectionBatch(tuple(records))
    if require_unique and len(parsed) != 1:
        return CollectionBatch((), error="WORKTREE_AMBIGUOUS")
    for row in parsed:
        records.append(
            KnowledgeRecord(
                provenance=build_provenance(
                    source_type="GIT_WORKTREE",
                    source_identifier=row["worktree"],
                    collected_at=collected_at,
                    truth_kind="GIT_VERIFIED",
                    record_type="GIT_WORKTREE",
                    verification_state="COLLECTED",
                    commit_sha=row["HEAD"],
                    branch=row.get("branch"),
                    worktree=row["worktree"],
                    observed_at=collected_at,
                ),
                collection_status="METADATA_ONLY",
                fields={"canonical_same_path": "YES" if row["worktree"] == str(root) else "NO"},
            )
        )
    stopped = "LIMIT_REACHED" if len(parsed) >= settings.max_worktrees else None
    return CollectionBatch(tuple(records), stopped_reason=stopped)
