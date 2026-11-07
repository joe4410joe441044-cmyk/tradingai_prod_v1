"""Test-only, Production-independent release-diff acceptance helpers.

The expected technical diff, actual Git diff, owner decisions, and release
approval are deliberately separate inputs.  Nothing in this module reads the
canonical Production checkout, network, credentials, runtime state, or orders.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Callable, Mapping


DIFF_SCHEMA = "tradingai-release-diff/v1"
APPROVAL_SCHEMA = "tradingai-release-approvals/v1"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODE_RE = re.compile(r"^[0-7]{6}$")
ALLOWED_STATUSES = {"A", "M"}
CLASSIFICATION_BY_STATUS = {
    "A": "NEEDED",
    "M": "SHARED_PATH_REVIEW_REQUIRED",
}
DECISIONS = {"ACCEPT", "REJECT", "NEEDS_CHANGE", "PENDING"}


class ManifestError(ValueError):
    """Raised when a release expectation or approval document is malformed."""


@dataclass(frozen=True)
class TechnicalDiffResult:
    matches: bool
    errors: tuple[str, ...]
    entry_count: int
    counts: Mapping[str, int]
    shared_paths: frozenset[str]


@dataclass(frozen=True)
class ReleaseAcceptance:
    verdict: str
    technical_status: str
    owner_response_status: str
    release_approval_status: str
    blockers: tuple[str, ...]


def _require_exact_fields(value: Mapping, expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise ManifestError(f"{context}: missing={missing}, unknown={unknown}")


def _require_sha(value, pattern: re.Pattern[str], context: str) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ManifestError(f"{context}: invalid hash")


def _require_safe_path(value, context: str) -> None:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{context}: path must be a non-empty string")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ManifestError(f"{context}: unsafe path")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{path.name}: document must be an object")
    return value


def validate_diff_manifest(document: Mapping) -> dict:
    top_fields = {
        "schemaVersion",
        "baseSha",
        "candidateSha",
        "comparison",
        "expectedEntryCount",
        "expectedCounts",
        "provenance",
        "entries",
    }
    _require_exact_fields(document, top_fields, "diff manifest")
    if document["schemaVersion"] != DIFF_SCHEMA:
        raise ManifestError("diff manifest: unsupported schemaVersion")
    _require_sha(document["baseSha"], SHA1_RE, "diff manifest baseSha")
    _require_sha(document["candidateSha"], SHA1_RE, "diff manifest candidateSha")
    if document["baseSha"] == document["candidateSha"]:
        raise ManifestError("diff manifest: baseSha and candidateSha must differ")
    if not isinstance(document["comparison"], str) or not document["comparison"]:
        raise ManifestError("diff manifest: comparison must be a non-empty string")
    if not isinstance(document["provenance"], str) or not document["provenance"]:
        raise ManifestError("diff manifest: provenance must be a non-empty string")
    if not isinstance(document["expectedEntryCount"], int) or document["expectedEntryCount"] < 0:
        raise ManifestError("diff manifest: invalid expectedEntryCount")
    counts = document["expectedCounts"]
    if not isinstance(counts, dict):
        raise ManifestError("diff manifest: expectedCounts must be an object")
    _require_exact_fields(counts, {"A", "M"}, "diff manifest expectedCounts")
    if any(not isinstance(counts[key], int) or counts[key] < 0 for key in ("A", "M")):
        raise ManifestError("diff manifest: invalid expectedCounts")
    entries = document["entries"]
    if not isinstance(entries, list):
        raise ManifestError("diff manifest: entries must be an array")

    entry_fields = {
        "path",
        "status",
        "classification",
        "beforeMode",
        "afterMode",
        "beforeBlob",
        "afterBlob",
        "beforeSha256",
        "afterSha256",
    }
    seen: set[str] = set()
    derived_counts = {"A": 0, "M": 0}
    normalized: list[dict] = []
    for index, item in enumerate(entries):
        context = f"diff manifest entries[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{context}: entry must be an object")
        _require_exact_fields(item, entry_fields, context)
        _require_safe_path(item["path"], context)
        if item["path"] in seen:
            raise ManifestError(f"{context}: duplicate path {item['path']}")
        seen.add(item["path"])
        status = item["status"]
        if status not in ALLOWED_STATUSES:
            raise ManifestError(f"{context}: unsupported status {status!r}")
        if item["classification"] != CLASSIFICATION_BY_STATUS[status]:
            raise ManifestError(f"{context}: classification/status mismatch")
        if status == "A":
            if (
                item["beforeMode"] != "000000"
                or item["beforeBlob"] is not None
                or item["beforeSha256"] is not None
            ):
                raise ManifestError(f"{context}: added entry must have null before values")
        else:
            if not isinstance(item["beforeMode"], str) or not MODE_RE.fullmatch(item["beforeMode"]):
                raise ManifestError(f"{context}: invalid beforeMode")
            if item["beforeMode"] == "000000":
                raise ManifestError(f"{context}: modified entry must have a before mode")
            _require_sha(item["beforeBlob"], SHA1_RE, f"{context} beforeBlob")
            _require_sha(item["beforeSha256"], SHA256_RE, f"{context} beforeSha256")
        if not isinstance(item["afterMode"], str) or not MODE_RE.fullmatch(item["afterMode"]):
            raise ManifestError(f"{context}: invalid afterMode")
        if item["afterMode"] == "000000":
            raise ManifestError(f"{context}: entry must have an after mode")
        _require_sha(item["afterBlob"], SHA1_RE, f"{context} afterBlob")
        _require_sha(item["afterSha256"], SHA256_RE, f"{context} afterSha256")
        derived_counts[status] += 1
        normalized.append(dict(item))

    if document["expectedEntryCount"] != len(normalized):
        raise ManifestError("diff manifest: expectedEntryCount does not match entries")
    if counts != derived_counts:
        raise ManifestError("diff manifest: expectedCounts does not match entries")
    return {**dict(document), "entries": normalized}


def _run_git(repo: Path, args: tuple[str, ...], observer: Callable[[Path, tuple[str, ...]], None] | None = None) -> bytes:
    if observer is not None:
        observer(repo, args)
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def derive_actual_diff(
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    *,
    observer: Callable[[Path, tuple[str, ...]], None] | None = None,
) -> list[dict]:
    raw = _run_git(
        repo,
        ("diff", "--raw", "--no-abbrev", "--no-renames", base_sha, candidate_sha),
        observer,
    ).decode("utf-8")
    entries: list[dict] = []
    for line in raw.splitlines():
        metadata, path = line.split("\t", 1)
        old_mode, new_mode, old_blob, new_blob, status = metadata[1:].split()
        if status not in ALLOWED_STATUSES:
            raise ManifestError(f"actual diff: unsupported status {status!r} for {path}")
        before_blob = None if status == "A" else old_blob
        before_content = None
        if before_blob is not None:
            before_content = _run_git(repo, ("cat-file", "blob", before_blob), observer)
        after_content = _run_git(repo, ("cat-file", "blob", new_blob), observer)
        entries.append(
            {
                "path": path,
                "status": status,
                "classification": CLASSIFICATION_BY_STATUS[status],
                "beforeMode": old_mode,
                "afterMode": new_mode,
                "beforeBlob": before_blob,
                "afterBlob": new_blob,
                "beforeSha256": None if before_content is None else hashlib.sha256(before_content).hexdigest(),
                "afterSha256": hashlib.sha256(after_content).hexdigest(),
            }
        )
    return entries


def compare_entries(expected: list[dict], actual: list[dict]) -> tuple[str, ...]:
    errors: list[str] = []
    expected_by_path = {item["path"]: item for item in expected}
    actual_by_path = {item["path"]: item for item in actual}
    for path in sorted(actual_by_path.keys() - expected_by_path.keys()):
        errors.append(f"UNEXPECTED_PATH:{path}")
    for path in sorted(expected_by_path.keys() - actual_by_path.keys()):
        errors.append(f"MISSING_EXPECTED_PATH:{path}")
    fields = (
        "status",
        "classification",
        "beforeMode",
        "afterMode",
        "beforeBlob",
        "afterBlob",
        "beforeSha256",
        "afterSha256",
    )
    for path in sorted(expected_by_path.keys() & actual_by_path.keys()):
        for field in fields:
            if expected_by_path[path][field] != actual_by_path[path][field]:
                errors.append(f"CONTENT_MISMATCH:{path}:{field}")
    return tuple(errors)


def verify_expected_diff(
    repo: Path,
    document: Mapping,
    *,
    pinned_base_sha: str,
    pinned_candidate_sha: str,
    observer: Callable[[Path, tuple[str, ...]], None] | None = None,
) -> TechnicalDiffResult:
    manifest = validate_diff_manifest(document)
    errors: list[str] = []
    if manifest["baseSha"] != pinned_base_sha:
        errors.append("BASE_SHA_MISMATCH")
    if manifest["candidateSha"] != pinned_candidate_sha:
        errors.append("CANDIDATE_SHA_MISMATCH")
    actual: list[dict] = []
    if not errors:
        actual = derive_actual_diff(repo, pinned_base_sha, pinned_candidate_sha, observer=observer)
        errors.extend(compare_entries(manifest["entries"], actual))
    shared = frozenset(
        item["path"] for item in manifest["entries"] if item["status"] == "M"
    )
    return TechnicalDiffResult(
        matches=not errors,
        errors=tuple(errors),
        entry_count=len(actual) if actual else manifest["expectedEntryCount"],
        counts=dict(manifest["expectedCounts"]),
        shared_paths=shared,
    )


def validate_approval_record(document: Mapping, manifest: Mapping, manifest_sha256: str) -> dict:
    fields = {
        "schemaVersion",
        "baseSha",
        "candidateSha",
        "diffManifestSha256",
        "recordKind",
        "releaseApprovalStatus",
        "decisions",
    }
    _require_exact_fields(document, fields, "approval record")
    if document["schemaVersion"] != APPROVAL_SCHEMA:
        raise ManifestError("approval record: unsupported schemaVersion")
    if document["baseSha"] != manifest["baseSha"]:
        raise ManifestError("approval record: baseSha mismatch")
    if document["candidateSha"] != manifest["candidateSha"]:
        raise ManifestError("approval record: candidateSha mismatch")
    if document["diffManifestSha256"] != manifest_sha256:
        raise ManifestError("approval record: diff manifest hash mismatch")
    if document["recordKind"] not in {"REAL_OWNER_RESPONSES", "SYNTHETIC_TEST_ONLY"}:
        raise ManifestError("approval record: invalid recordKind")
    if document["releaseApprovalStatus"] not in {"PENDING", "APPROVED", "REJECTED"}:
        raise ManifestError("approval record: invalid releaseApprovalStatus")
    decisions = document["decisions"]
    if not isinstance(decisions, list):
        raise ManifestError("approval record: decisions must be an array")
    decision_fields = {"path", "decision", "ownerRole", "evidence"}
    expected_paths = {
        item["path"] for item in manifest["entries"] if item["status"] == "M"
    }
    seen: set[str] = set()
    normalized = []
    for index, item in enumerate(decisions):
        context = f"approval record decisions[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{context}: decision must be an object")
        _require_exact_fields(item, decision_fields, context)
        _require_safe_path(item["path"], context)
        if item["path"] in seen:
            raise ManifestError(f"{context}: duplicate path {item['path']}")
        seen.add(item["path"])
        if item["decision"] not in DECISIONS:
            raise ManifestError(f"{context}: invalid decision")
        if not isinstance(item["ownerRole"], str) or not item["ownerRole"]:
            raise ManifestError(f"{context}: ownerRole required")
        if not isinstance(item["evidence"], str) or not item["evidence"]:
            raise ManifestError(f"{context}: evidence required")
        normalized.append(dict(item))
    if seen != expected_paths:
        raise ManifestError(
            f"approval record: decision paths mismatch missing={sorted(expected_paths-seen)} unknown={sorted(seen-expected_paths)}"
        )
    return {**dict(document), "decisions": normalized}


def evaluate_release_acceptance(
    technical: TechnicalDiffResult,
    approval_record: Mapping | None,
    *,
    integration_passed: bool,
) -> ReleaseAcceptance:
    blockers: list[str] = []
    if not technical.matches:
        blockers.extend(f"TECHNICAL_DIFF:{item}" for item in technical.errors)
    if not integration_passed:
        blockers.append("ISOLATED_INTEGRATION_NOT_PASS")
    if approval_record is None:
        return ReleaseAcceptance(
            verdict="NOT_READY",
            technical_status="MATCH" if technical.matches else "MISMATCH",
            owner_response_status="MISSING",
            release_approval_status="MISSING",
            blockers=tuple(blockers + ["APPROVAL_RECORD_MISSING"]),
        )

    decisions = {item["path"]: item["decision"] for item in approval_record["decisions"]}
    rejected = sorted(path for path, value in decisions.items() if value == "REJECT")
    needs_change = sorted(path for path, value in decisions.items() if value == "NEEDS_CHANGE")
    pending = sorted(path for path, value in decisions.items() if value == "PENDING")
    if rejected:
        blockers.extend(f"OWNER_REJECTED:{path}" for path in rejected)
        owner_status = "REJECTED"
    elif needs_change:
        blockers.extend(f"OWNER_NEEDS_CHANGE:{path}" for path in needs_change)
        owner_status = "NEEDS_CHANGE"
    elif pending:
        blockers.extend(f"OWNER_PENDING:{path}" for path in pending)
        owner_status = "PENDING"
    else:
        owner_status = "ALL_ACCEPTED"
    release_status = approval_record["releaseApprovalStatus"]
    if release_status != "APPROVED":
        blockers.append(f"RELEASE_APPROVAL_{release_status}")
    return ReleaseAcceptance(
        verdict="READY_FOR_APPROVAL" if not blockers else "NOT_READY",
        technical_status="MATCH" if technical.matches else "MISMATCH",
        owner_response_status=owner_status,
        release_approval_status=release_status,
        blockers=tuple(blockers),
    )
