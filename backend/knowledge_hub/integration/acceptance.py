"""Acceptance helpers for BC-8.

The hash classifier is read-only. It never edits a manifest, never edits a
source document, and never copies document content into its result.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

from .integration_models import (
    MATCH,
    MISMATCH,
    NO_MISMATCH,
    PRE_EXISTING_MANIFEST_DRIFT,
    SOURCE_CONTENT_CHANGED,
    SOURCE_MISSING,
    HashMismatchClassification,
    HashMismatchEntry,
    IntegrationResult,
)


def _field(entry: Any, name: str) -> str:
    if isinstance(entry, Mapping):
        return str(entry.get(name, ""))
    return str(getattr(entry, name, ""))


def _git_bytes(repository: Path, args: tuple[str, ...], timeout: float) -> bytes | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _expected_hash_in_history(
    repository: Path,
    relative_path: str,
    expected_hash: str,
    *,
    timeout: float = 5.0,
    max_revisions: int = 100,
) -> bool:
    """Return True when the expected hash is a historical blob of the path.

    Only Git metadata is inspected. Working tree files are never rewritten.
    """

    listing = _git_bytes(repository, ("rev-list", f"-n{max_revisions}", "HEAD", "--", relative_path), timeout)
    if listing is None:
        return False
    for revision in listing.decode("utf-8", errors="ignore").splitlines():
        revision = revision.strip()
        if not revision:
            continue
        blob = _git_bytes(repository, ("cat-file", "-p", f"{revision}:{relative_path}"), timeout)
        if blob is None:
            continue
        if "sha256:" + hashlib.sha256(blob).hexdigest() == expected_hash:
            return True
    return False


def classify_hash_mismatch(
    entries: Iterable[Any],
    *,
    repository_root: str | Path,
    source_manifest: str = "production_knowledge_manifest",
    timeout: float = 5.0,
) -> HashMismatchClassification:
    """Compare manifest hashes to current files without modifying anything."""

    root = Path(repository_root)
    classified: list[HashMismatchEntry] = []
    for entry in entries:
        source_id = _field(entry, "sourceId")
        relative_path = _field(entry, "relativePath")
        expected_hash = _field(entry, "expectedHash")
        candidate = root / relative_path
        actual_hash: str | None = None
        if candidate.is_file() and not candidate.is_symlink():
            actual_hash = "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_hash is None:
            status = SOURCE_MISSING
            classification = SOURCE_CONTENT_CHANGED
        elif actual_hash == expected_hash:
            status = MATCH
            classification = NO_MISMATCH
        else:
            status = MISMATCH
            if _expected_hash_in_history(root, relative_path, expected_hash, timeout=timeout):
                classification = SOURCE_CONTENT_CHANGED
            else:
                classification = PRE_EXISTING_MANIFEST_DRIFT
        classified.append(
            HashMismatchEntry(
                source_id=source_id,
                relative_path=relative_path,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                status=status,
                classification=classification,
            )
        )
    return HashMismatchClassification(entries=tuple(classified), source_manifest=source_manifest)


def _attachment_safe(attachment: Mapping[str, Any]) -> bool:
    return (
        attachment.get("authority") == "NONE"
        and attachment.get("trading_control") == "FORBIDDEN"
        and attachment.get("system_instruction") is False
        and attachment.get("bb_context_unchanged") is True
        and not attachment.get("executed_commands")
    )


def _search_ok(result: IntegrationResult, label: str) -> bool:
    payload = result.search.get(label) or {}
    return bool(payload.get("returned_count", 0) > 0) and bool(payload.get("provenance_complete"))


def evaluate_acceptance(
    result: IntegrationResult,
    *,
    reconciliation=None,
    hash_classification=None,
    environment: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Map the A01-A24 acceptance criteria to explicit booleans.

    Criteria that cannot be observed from a single isolated run must be passed
    explicitly through ``environment``. They are never assumed to be true.
    """

    env = dict(environment or {})

    def flag(name: str) -> bool:
        return bool(env.get(name, False))

    criteria: dict[str, bool] = {
        "A01_BC7_COMMIT_ANCESTRY": flag("bc7_ancestor"),
        "A02_ISOLATED_WORKTREE": flag("isolated_worktree"),
        "A03_BC2_TO_BC7_E2E": result.passed,
        "A04_ADVISOR_READ_ONLY_QUERY": _attachment_safe(result.advisor)
        and result.advisor.get("knowledge_status") in {"OK", "EMPTY"},
        "A05_SUPERVISOR_READ_ONLY_QUERY": _attachment_safe(result.supervisor)
        and result.supervisor.get("knowledge_status") in {"OK", "EMPTY"},
        "A06_CHATGPT_ACCOUNT_A_B": _search_ok(result, "chatgpt_a")
        and _search_ok(result, "chatgpt_b"),
        "A07_CURSOR_VSCODE_SYNC": _search_ok(result, "cursor") and _search_ok(result, "vscode"),
        "A08_KNOWLEDGE_SEARCH": all(
            _search_ok(result, label)
            for label in ("source", "git", "worktree", "cursor", "vscode", "chatgpt_a", "chatgpt_b")
        ),
        "A09_PROVENANCE": (result.stage("PROVENANCE_AND_TRUTH_BOUNDARY") is not None)
        and result.stage("PROVENANCE_AND_TRUTH_BOUNDARY").status == "OK",
        "A10_BB_CONTEXT_SEPARATION": bool(result.bb_context)
        and result.advisor.get("bb_context_unchanged") is True
        and result.supervisor.get("bb_context_unchanged") is True,
        "A11_OPERATOR_PUBLIC_BOUNDARY": bool(result.access.get("privilege_escalation_denied"))
        and result.access.get("public_returns_operator_only") is False,
        "A12_SECURITY_ACCEPTANCE": flag("security_ok"),
        "A13_FAILURE_DEGRADATION": flag("failure_degradation_ok"),
        "A14_PERFORMANCE_MEASUREMENT": bool(result.latencies),
        "A15_HASH_MISMATCH_CLASSIFICATION": hash_classification is not None,
        "A16_CANONICAL_RECONCILIATION": reconciliation is not None,
        "A17_DEPLOYMENT_READINESS_CLASSIFIED": flag("readiness_classified"),
        "A18_DEPLOYMENT_HANDOFF": flag("handoff_written"),
        "A19_BC2_TO_BC7_REGRESSION": flag("regressions_ok"),
        "A20_BB_COMPATIBILITY": flag("bb_compatible"),
        "A21_PRODUCTION_UNCHANGED": flag("production_unchanged"),
        "A22_BRANCH_COMMIT": flag("committed"),
        "A23_FINAL_REPORT": flag("report_written"),
        "A24_NO_PRODUCTION_DEPLOY": flag("deploy_not_performed"),
    }
    failed = [name for name, ok in criteria.items() if not ok]
    return {
        "criteria": criteria,
        "failed": failed,
        "passed": not failed,
        "verdict": result.verdict if not failed else "ACCEPTANCE_INCOMPLETE",
    }
