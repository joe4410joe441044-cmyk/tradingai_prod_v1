"""Read-only canonical reconciliation and deployment readiness classification.

All Git calls here are inspection only: ``rev-parse``, ``diff --name-status``,
and ``status --porcelain``. Nothing is fetched, merged, rebased, reset, or
committed.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

from .integration_models import (
    ALREADY_CANONICAL,
    CONDITIONAL_READY,
    CONFLICTING,
    NEEDED,
    NOT_READY,
    NO_MISMATCH,
    PRE_EXISTING_MANIFEST_DRIFT,
    READINESS_UNKNOWN,
    READY_FOR_APPROVAL,
    RECONCILIATION_UNKNOWN,
    SHARED_PATH_REVIEW_REQUIRED,
    SOURCE_CONTENT_CHANGED,
    CanonicalReconciliation,
    DeploymentReadiness,
    ReconciliationEntry,
)


def _git(repository: Path, args: tuple[str, ...], timeout: float = 10.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout


def _rev(repository: Path, ref: str) -> str | None:
    code, output = _git(repository, ("rev-parse", ref))
    if code != 0:
        return None
    value = output.strip()
    return value or None


def _classify(status: str) -> str:
    code = status[:1]
    if code == "A":
        return NEEDED
    if code == "M" or code == "T":
        return SHARED_PATH_REVIEW_REQUIRED
    if code == "D":
        return CONFLICTING
    if code == "R" or code == "C":
        return SHARED_PATH_REVIEW_REQUIRED
    if code == "U":
        return CONFLICTING
    if code in {"", " "}:
        return ALREADY_CANONICAL
    return RECONCILIATION_UNKNOWN


def reconcile_with_canonical(
    canonical_repo: str | Path,
    worktree_repo: str | Path,
    *,
    canonical_head: str | None = None,
    worktree_head: str | None = None,
) -> CanonicalReconciliation:
    """Classify the committed difference between two repositories."""

    canonical = Path(canonical_repo)
    worktree = Path(worktree_repo)
    canonical_sha = canonical_head or _rev(canonical, "HEAD") or ""
    worktree_sha = worktree_head or _rev(worktree, "HEAD") or ""
    if not canonical_sha or not worktree_sha:
        return CanonicalReconciliation(
            entries=(
                ReconciliationEntry(
                    path="",
                    git_status="?",
                    classification=RECONCILIATION_UNKNOWN,
                ),
            ),
            canonical_head=canonical_sha,
            worktree_head=worktree_sha,
        )
    code, output = _git(
        worktree,
        ("diff", "--name-status", "--find-renames", f"{canonical_sha}..{worktree_sha}"),
    )
    if code != 0:
        return CanonicalReconciliation(
            entries=(
                ReconciliationEntry(
                    path="",
                    git_status="?",
                    classification=RECONCILIATION_UNKNOWN,
                ),
            ),
            canonical_head=canonical_sha,
            worktree_head=worktree_sha,
        )
    entries: list[ReconciliationEntry] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        path = parts[-1].strip()
        entries.append(
            ReconciliationEntry(
                path=path,
                git_status=status,
                classification=_classify(status),
            )
        )
    return CanonicalReconciliation(
        entries=tuple(entries),
        canonical_head=canonical_sha,
        worktree_head=worktree_sha,
    )


def production_dirty_state(repository: str | Path) -> tuple[str, ...]:
    """Return read-only porcelain status lines. Nothing is cleaned."""

    code, output = _git(Path(repository), ("status", "--porcelain=v1"))
    if code != 0:
        return ()
    return tuple(line for line in output.splitlines() if line.strip())


def assess_deployment_readiness(
    *,
    integration_passed: bool,
    reconciliation: CanonicalReconciliation | None,
    hash_classification=None,
    canonical_dirty: tuple[str, ...] = (),
    bb_compatible: bool = True,
    production_unchanged: bool = True,
) -> DeploymentReadiness:
    """Independent verdict. Isolated PASS never implies production READY."""

    blockers: list[str] = []
    notes: list[str] = []

    if not integration_passed:
        blockers.append("ISOLATED_INTEGRATION_NOT_PASS")
    if not bb_compatible:
        blockers.append("BB_CONTRACT_INCOMPATIBLE")
    if not production_unchanged:
        blockers.append("PRODUCTION_CHANGED_DURING_ACCEPTANCE")
    if reconciliation is None:
        blockers.append("CANONICAL_RECONCILIATION_MISSING")
    else:
        if reconciliation.blocked:
            for item in reconciliation.blocked:
                blockers.append(f"CANONICAL_{item.classification}:{item.path or 'UNRESOLVED'}")
        else:
            counts = reconciliation.counts()
            notes.append(
                "CANONICAL_RECONCILIATION:"
                + ",".join(f"{key}={value}" for key, value in sorted(counts.items()))
            )

    if hash_classification is not None:
        overall = hash_classification.overall
        if overall == NO_MISMATCH:
            notes.append("ADVISOR_HASH_MISMATCH:NONE")
        elif overall in {SOURCE_CONTENT_CHANGED, PRE_EXISTING_MANIFEST_DRIFT}:
            notes.append(f"KNOWN_PRE_EXISTING_ADVISOR_HASH_MISMATCH:{overall}")
            notes.append("ADVISOR_HASH_MISMATCH_DOES_NOT_BLOCK_KNOWLEDGE_HUB_READER")
        else:
            notes.append(f"UNCLASSIFIED_ADVISOR_HASH_MISMATCH:{overall}")

    if canonical_dirty:
        notes.append(f"PRODUCTION_DIRTY_STATE_ENTRIES:{len(canonical_dirty)}")
        notes.append("PRODUCTION_DIRTY_STATE_LEFT_UNTOUCHED")

    if blockers:
        if any(item == "ISOLATED_INTEGRATION_NOT_PASS" for item in blockers):
            return DeploymentReadiness(verdict=NOT_READY, blockers=tuple(blockers), notes=tuple(notes))
        return DeploymentReadiness(verdict=NOT_READY, blockers=tuple(blockers), notes=tuple(notes))

    if hash_classification is None:
        return DeploymentReadiness(
            verdict=READINESS_UNKNOWN,
            blockers=("HASH_MISMATCH_CLASSIFICATION_MISSING",),
            notes=tuple(notes),
        )
    if hash_classification.overall not in {
        NO_MISMATCH,
        SOURCE_CONTENT_CHANGED,
        PRE_EXISTING_MANIFEST_DRIFT,
    }:
        return DeploymentReadiness(
            verdict=CONDITIONAL_READY,
            blockers=(),
            notes=tuple(notes),
        )
    return DeploymentReadiness(verdict=READY_FOR_APPROVAL, blockers=(), notes=tuple(notes))
