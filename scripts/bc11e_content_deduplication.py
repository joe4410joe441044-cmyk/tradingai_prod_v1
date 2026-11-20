#!/usr/bin/env python3
"""BC-11E-5 historical report content deduplication, staged and approval gated.

The work is deliberately split into two operator gates:

STAGE_A (default, ``--stage-a``)
    Consume the already-produced BC-11E-3/BC-11E-4 artefacts, re-validate their
    internal consistency, stat every candidate file (metadata only), apply the
    approved-root and path-security gates, and produce a hash execution plan.
    No file body is opened. No content hash is computed. No import happens.

STAGE_B (``--stage-b --stage-b-approval STAGE_B_APPROVED``)
    Execute the plan with chunked SHA-256 streaming, group identical hashes, and
    emit content deduplication evidence. This gate can only be opened with an
    explicit operator token; running STAGE_A never opens it automatically.

Safety invariants for both stages: no source file is deleted, moved, or
modified; every storage location is preserved; provenance is never confirmed by
a hash; nothing is written outside the requested output directory; no import or
production database access occurs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat as stat_module
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.config import DEFAULT_REPORT_ROOTS  # noqa: E402
from backend.knowledge_hub.security import secret_filename  # noqa: E402

PLAN_SCHEMA_VERSION = "tradingai-bc11e5-hash-execution-plan/v1"
SCOPE_SCHEMA_VERSION = "tradingai-bc11e5-hash-scope-review/v1"
RESULTS_SCHEMA_VERSION = "tradingai-bc11e5-content-hash-results/v1"
CONFIRMED_SCHEMA_VERSION = "tradingai-bc11e5-confirmed-duplicates/v1"
UNIQUE_SCHEMA_VERSION = "tradingai-bc11e5-unique-content-candidates/v1"

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_UNIFIED_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_UNIFIED_INVENTORY.json"
DEFAULT_DUPLICATE_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_DUPLICATE_REVIEW.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "BC11E3_IMPORT_MANIFEST_CANDIDATE.json"
DEFAULT_VERIFICATION_PLAN_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E4_DUPLICATE_VERIFICATION_PLAN.json"
)
DEFAULT_PROVENANCE_PLAN_PATH = DEFAULT_OUTPUT_DIR / "BC11E4_PROVENANCE_REVIEW_PLAN.json"
DEFAULT_QUEUE_PATH = DEFAULT_OUTPUT_DIR / "BC11E4_VERIFICATION_QUEUE.json"
DEFAULT_READINESS_PATH = DEFAULT_OUTPUT_DIR / "BC11E4_IMPORT_READINESS_CANDIDATE.json"

PLAN_JSON_NAME = "BC11E5_HASH_EXECUTION_PLAN.json"
SCOPE_JSON_NAME = "BC11E5_HASH_SCOPE_REVIEW.json"
APPROVAL_MD_NAME = "BC11E5_HASH_APPROVAL_REQUEST.md"
STAGE_A_FINAL_MD_NAME = "BC11E5_STAGE_A_FINAL.md"
RESULTS_JSON_NAME = "BC11E5_CONTENT_HASH_RESULTS.json"
CONFIRMED_JSON_NAME = "BC11E5_CONFIRMED_DUPLICATES.json"
UNIQUE_JSON_NAME = "BC11E5_UNIQUE_CONTENT_CANDIDATES.json"
STAGE_B_FINAL_MD_NAME = "BC11E5_CONTENT_VERIFICATION_FINAL.md"

MODE_STAGE_A = "OFFLINE_CONTENT_HASH_PLAN_ONLY"
MODE_STAGE_B = "OFFLINE_CONTENT_HASH_VERIFICATION"

STAGE_B_APPROVAL_TOKEN = "STAGE_B_APPROVED"
STAGE_B_APPROVED_NO = "NO"

WORKTREE_ROOT = Path("/home/joe4410joe/tradingai_prod_v1.worktrees")
CANONICAL_ROOT = Path("/home/joe4410joe/tradingai_prod_v1")
ADDITIONAL_APPROVED_ROOTS: tuple[Path, ...] = tuple(DEFAULT_REPORT_ROOTS)

REPORT_ROOTS: tuple[str, ...] = (
    "docs/reports",
    "docs/opencode/reports",
    "reports",
    "tmp/reports",
    "tmp/chatgpt_reviews",
)

HASH_CHUNK_SIZE = 1024 * 1024
MTIME_TOLERANCE_SECONDS = 1e-5

SOURCE_PRESENT = "SOURCE_PRESENT"
SOURCE_MISSING = "SOURCE_MISSING"
SOURCE_CHANGED_SINCE_INVENTORY = "SOURCE_CHANGED_SINCE_INVENTORY"
SOURCE_REJECTED = "SOURCE_REJECTED"

HASH_NOT_STARTED = "NOT_STARTED"

CONTENT_IDENTICAL = "CONTENT_IDENTICAL"
CONTENT_DIFFERENT = "CONTENT_DIFFERENT"
READ_FAILED = "READ_FAILED"
SOURCE_CHANGED_DURING_HASH = "SOURCE_CHANGED_DURING_HASH"
NOT_VERIFIED = "NOT_VERIFIED"
HASHED = "HASHED"

REJECT_ABSOLUTE_PATH_REQUIRED = "ABSOLUTE_PATH_REQUIRED"
REJECT_PATH_TRAVERSAL = "PATH_TRAVERSAL"
REJECT_FILENAME_MISMATCH = "FILENAME_MISMATCH"
REJECT_SECRET_FILENAME = "SECRET_FILENAME"
REJECT_SOURCE_ROOT_NOT_ABSOLUTE = "SOURCE_ROOT_NOT_ABSOLUTE"
REJECT_SOURCE_ROOT_NOT_APPROVED = "SOURCE_ROOT_NOT_APPROVED"
REJECT_PATH_ESCAPE = "PATH_ESCAPE"
REJECT_CANONICAL_EXCLUDED = "CANONICAL_EXCLUDED"
REJECT_SYMLINK = "SYMLINK_REJECTED"
REJECT_NOT_REGULAR_FILE = "NOT_REGULAR_FILE"
REJECT_STAT_FAILED = "STAT_FAILED"
REJECT_PATH_RESOLUTION_FAILED = "PATH_RESOLUTION_FAILED"

INPUTS_VALID = "INPUTS_VALID"
INPUT_COUNT_MISMATCH = "INPUT_COUNT_MISMATCH"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"

VERDICT_STAGE_A_READY = "BC11E5_STAGE_A_HASH_PLAN_READY"
VERDICT_INPUT_BLOCKED = "BC11E5_INPUT_BLOCKED"
VERDICT_SECURITY_BLOCKED = "BC11E5_SECURITY_BLOCKED"

CLASS_CURSOR = "CURSOR_CANDIDATE"
CLASS_OTHER_AGENT = "OTHER_AGENT_CANDIDATE"
CLASS_CHATGPT = "CHATGPT_CANDIDATE"
CLASS_UNKNOWN = "UNKNOWN_CANDIDATE"

PROVENANCE_UNKNOWN = "UNKNOWN"
APPROVAL_UNAPPROVED = "UNAPPROVED"

VERIFICATION_NOT_STARTED = "NOT_STARTED"
REVIEW_NOT_STARTED = "NOT_STARTED"

EXPECTED_BASELINE = {
    "UNIFIED_CANDIDATE_COUNT": 6646,
    "MANIFEST_CANDIDATE_COUNT": 6646,
    "DUPLICATE_CANDIDATE_COUNT": 6174,
    "SOURCE_DUPLICATE_GROUP_COUNT": 52,
    "NAME_COLLISION_GROUP_COUNT": 26,
    "VERIFICATION_GROUP_COUNT": 26,
    "VERIFICATION_QUEUE_COUNT": 6646,
    "PROVENANCE_REVIEW_COUNT": 6646,
    "IMPORT_READINESS_CANDIDATE_COUNT": 6646,
    "ALL_APPROVED_FALSE": True,
    "ALL_VERIFICATION_NOT_STARTED": True,
    "ALL_IMPORT_READY_FALSE": True,
}

REQUIRED_CANDIDATE_FIELDS = (
    "source_id",
    "absolute_path",
    "filename",
    "size_bytes",
    "mtime",
    "source_root",
    "inventory_origin",
    "source_classification",
    "provenance_status",
)

REQUIRED_MANIFEST_ENTRY_FIELDS = (
    "sourceId",
    "path",
    "provenanceStatus",
    "duplicateGroup",
    "selectionStatus",
    "approved",
    "sourceStatus",
)

REQUIRED_QUEUE_ITEM_FIELDS = (
    "source_id",
    "verification_priority",
    "verification_status",
)

REQUIRED_PROVENANCE_ENTRY_FIELDS = (
    "source_id",
    "provenance_status",
    "confirmed_cursor",
    "confirmed_other_agent",
    "confirmed_chatgpt",
)

REQUIRED_READINESS_ENTRY_FIELDS = (
    "source_id",
    "approved",
    "import_ready",
    "real_import_allowed",
)


class InputError(Exception):
    """A required input is missing or structurally invalid."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        super().__init__(f"{code}: {path}: {detail}")
        self.code = code
        self.path = path
        self.detail = detail


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _epoch_from_iso(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _mtime_matches(recorded_iso: str, observed_epoch: float) -> bool:
    try:
        recorded_epoch = _epoch_from_iso(str(recorded_iso))
    except (TypeError, ValueError):
        return False
    return abs(recorded_epoch - observed_epoch) <= MTIME_TOLERANCE_SECONDS


def load_input(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        raise InputError(BLOCKED_MISSING_INPUT, str(target), "file does not exist")
    if not target.is_file():
        raise InputError(BLOCKED_INVALID_INPUT, str(target), "not a regular file")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(BLOCKED_INVALID_INPUT, str(target), type(exc).__name__) from None
    if not isinstance(payload, dict):
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), "top-level JSON is not an object"
        )
    return payload


def _require(condition: bool, origin: str, detail: str) -> None:
    if not condition:
        raise InputError(BLOCKED_INVALID_INPUT, origin, detail)


def _require_fields(entries: list, fields: tuple[str, ...], origin: str) -> None:
    for index, entry in enumerate(entries):
        _require(isinstance(entry, dict), origin, f"entry {index} is not an object")
        missing = [key for key in fields if key not in entry]
        _require(
            not missing,
            origin,
            f"entry {index} missing fields: {','.join(missing)}",
        )


def validate_shapes(fixtures: dict) -> None:
    unified = fixtures["unified"]
    duplicate_review = fixtures["duplicate_review"]
    manifest = fixtures["manifest"]
    verification_plan = fixtures["verification_plan"]
    provenance_plan = fixtures["provenance_plan"]
    verification_queue = fixtures["verification_queue"]
    readiness = fixtures["readiness"]

    _require(isinstance(unified.get("candidates"), list), "unified", "candidates is not a list")
    _require(isinstance(unified.get("counts"), dict), "unified", "counts is not an object")
    _require_fields(unified["candidates"], REQUIRED_CANDIDATE_FIELDS, "unified")

    _require(
        isinstance(duplicate_review.get("groups"), list),
        "duplicate_review",
        "groups is not a list",
    )
    for index, group in enumerate(duplicate_review["groups"]):
        _require(isinstance(group, dict), "duplicate_review", f"group {index} is not an object")
        _require(
            isinstance(group.get("members"), list),
            "duplicate_review",
            f"group {index} members is not a list",
        )

    _require(isinstance(manifest.get("entries"), list), "manifest", "entries is not a list")
    _require_fields(manifest["entries"], REQUIRED_MANIFEST_ENTRY_FIELDS, "manifest")

    _require(
        isinstance(verification_plan.get("groups"), list),
        "verification_plan",
        "groups is not a list",
    )

    _require(
        isinstance(provenance_plan.get("entries"), list),
        "provenance_plan",
        "entries is not a list",
    )
    _require_fields(provenance_plan["entries"], REQUIRED_PROVENANCE_ENTRY_FIELDS, "provenance_plan")

    _require(
        isinstance(verification_queue.get("items"), list),
        "verification_queue",
        "items is not a list",
    )
    _require_fields(verification_queue["items"], REQUIRED_QUEUE_ITEM_FIELDS, "verification_queue")

    _require(
        isinstance(readiness.get("entries"), list),
        "readiness",
        "entries is not a list",
    )
    _require_fields(readiness["entries"], REQUIRED_READINESS_ENTRY_FIELDS, "readiness")


def _mismatch(key: str, expected: object, actual: object, detail: str = "") -> dict:
    return {
        "key": key,
        "expected": expected,
        "actual": actual,
        "match": expected == actual,
        "detail": detail,
    }


def validate_inputs(fixtures: dict, *, expected: dict) -> dict:
    """Reconcile all BC-11E-3/BC-11E-4 artefacts against the baseline."""

    validate_shapes(fixtures)
    unified = fixtures["unified"]
    duplicate_review = fixtures["duplicate_review"]
    manifest = fixtures["manifest"]
    verification_plan = fixtures["verification_plan"]
    provenance_plan = fixtures["provenance_plan"]
    verification_queue = fixtures["verification_queue"]
    readiness = fixtures["readiness"]

    candidates = unified["candidates"]
    candidate_ids = {str(candidate["source_id"]) for candidate in candidates}
    comparisons: list[dict] = []

    def _cmp(key: str, actual: object) -> None:
        if key in expected:
            comparisons.append(_mismatch(key, expected[key], actual))

    _cmp("UNIFIED_CANDIDATE_COUNT", len(candidates))
    _cmp("MANIFEST_CANDIDATE_COUNT", len(manifest["entries"]))
    _cmp("VERIFICATION_QUEUE_COUNT", len(verification_queue["items"]))
    _cmp("PROVENANCE_REVIEW_COUNT", len(provenance_plan["entries"]))
    _cmp("IMPORT_READINESS_CANDIDATE_COUNT", len(readiness["entries"]))
    _cmp("DUPLICATE_CANDIDATE_COUNT", sum(1 for c in candidates if c.get("duplicate_group") is not None))
    _cmp("SOURCE_DUPLICATE_GROUP_COUNT", len(duplicate_review["groups"]))
    _cmp("VERIFICATION_GROUP_COUNT", len(verification_plan["groups"]))
    _cmp(
        "NAME_COLLISION_GROUP_COUNT",
        sum(
            1
            for group in duplicate_review["groups"]
            if group.get("duplicate_kind") == "NAME_COLLISION"
        ),
    )

    comparisons.append(
        _mismatch(
            "MANIFEST_ENTRY_ID_SET",
            len(candidate_ids),
            len(candidate_ids & {str(e["sourceId"]) for e in manifest["entries"]}),
        )
    )
    comparisons.append(
        _mismatch(
            "QUEUE_ITEM_ID_SET",
            len(candidate_ids),
            len(candidate_ids & {str(i["source_id"]) for i in verification_queue["items"]}),
        )
    )
    comparisons.append(
        _mismatch(
            "PROVENANCE_ENTRY_ID_SET",
            len(candidate_ids),
            len(candidate_ids & {str(e["source_id"]) for e in provenance_plan["entries"]}),
        )
    )
    comparisons.append(
        _mismatch(
            "READINESS_ENTRY_ID_SET",
            len(candidate_ids),
            len(candidate_ids & {str(e["source_id"]) for e in readiness["entries"]}),
        )
    )

    approved_true = sum(1 for entry in manifest["entries"] if entry.get("approved") is not False)
    readiness_approved = sum(1 for entry in readiness["entries"] if entry.get("approved") is not False)
    readiness_ready = sum(1 for entry in readiness["entries"] if entry.get("import_ready") is not False)
    readiness_allowed = sum(
        1 for entry in readiness["entries"] if entry.get("real_import_allowed") is not False
    )
    all_approved_false = (
        approved_true == 0
        and readiness_approved == 0
        and manifest.get("approved") is False
        and manifest.get("import_ready") is False
        and manifest.get("real_import_allowed") is False
    )
    all_import_ready_false = (
        readiness_ready == 0
        and readiness_allowed == 0
        and readiness.get("import_ready") is False
    )
    not_started = (
        all(
            group.get("verification_status") == VERIFICATION_NOT_STARTED
            for group in verification_plan["groups"]
        )
        and all(
            item.get("verification_status") == VERIFICATION_NOT_STARTED
            for item in verification_queue["items"]
        )
        and all(
            entry.get("review_status") == REVIEW_NOT_STARTED
            for entry in provenance_plan["entries"]
        )
        and all(
            entry.get("verification_status") == VERIFICATION_NOT_STARTED
            for entry in readiness["entries"]
        )
    )

    if "ALL_APPROVED_FALSE" in expected:
        comparisons.append(_mismatch("ALL_APPROVED_FALSE", expected["ALL_APPROVED_FALSE"], all_approved_false))
    if "ALL_IMPORT_READY_FALSE" in expected:
        comparisons.append(
            _mismatch("ALL_IMPORT_READY_FALSE", expected["ALL_IMPORT_READY_FALSE"], all_import_ready_false)
        )
    if "ALL_VERIFICATION_NOT_STARTED" in expected:
        comparisons.append(
            _mismatch(
                "ALL_VERIFICATION_NOT_STARTED",
                expected["ALL_VERIFICATION_NOT_STARTED"],
                not_started,
            )
        )

    mismatches = [item for item in comparisons if not item["match"]]
    return {
        "status": INPUTS_VALID if not mismatches else INPUT_COUNT_MISMATCH,
        "inputs_valid": not mismatches,
        "all_approved_false": all_approved_false,
        "all_import_ready_false": all_import_ready_false,
        "all_verification_not_started": not_started,
        "comparisons": comparisons,
        "mismatches": mismatches,
    }


def compute_inventory_roots(unified: dict) -> tuple[Path, ...]:
    roots = {str(candidate.get("source_root")) for candidate in unified["candidates"]}
    roots.discard("None")
    return tuple(sorted(Path(root) for root in roots))


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _is_under(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def is_approved_root(root: str | Path, *, extra_approved_roots: tuple[str | Path, ...] = ()) -> bool:
    candidate = Path(root)
    if not candidate.is_absolute():
        return False
    resolved = _resolved(candidate)
    if resolved is None:
        return False
    canonical = _resolved(CANONICAL_ROOT)
    if canonical is not None and _is_under(resolved, canonical):
        return False
    if candidate.is_symlink():
        return False
    for extra in extra_approved_roots:
        extra_path = Path(extra)
        if not extra_path.is_absolute():
            continue
        extra_resolved = _resolved(extra_path)
        if extra_resolved is None:
            continue
        if canonical is not None and _is_under(extra_resolved, canonical):
            continue
        if _is_under(resolved, extra_resolved):
            return True
    for approved in ADDITIONAL_APPROVED_ROOTS:
        approved_resolved = _resolved(approved)
        if approved_resolved is not None and _is_under(resolved, approved_resolved):
            return True
    worktree_root = _resolved(WORKTREE_ROOT)
    if worktree_root is None or not _is_under(resolved, worktree_root):
        return False
    try:
        relative = resolved.relative_to(worktree_root)
    except ValueError:
        return False
    parts = relative.parts
    for report_root in REPORT_ROOTS:
        report_parts = Path(report_root).parts
        if len(parts) > len(report_parts) and parts[-len(report_parts):] == report_parts:
            return True
    return False


def _candidate_priority_map(verification_queue: dict) -> dict[str, dict]:
    return {
        str(item["source_id"]): {
            "verification_priority": item.get("verification_priority"),
            "duplicate_group": item.get("duplicate_group"),
        }
        for item in verification_queue["items"]
    }


def _reject(
    candidate: dict,
    *,
    rejection_reason: str,
    source_status: str = SOURCE_REJECTED,
) -> dict:
    return {
        "metadata_status": source_status,
        "source_status": source_status,
        "rejection_reason": rejection_reason,
        "hash_required": False,
        "observed_size_bytes": None,
        "observed_mtime": None,
    }


def inspect_candidate(
    candidate: dict,
    *,
    extra_approved_roots: tuple[str | Path, ...] = (),
) -> dict:
    """Validate one candidate using metadata only. Never opens the file body."""

    raw_path = str(candidate.get("absolute_path", ""))
    path = Path(raw_path)
    if not path.is_absolute():
        return _reject(candidate, rejection_reason=REJECT_ABSOLUTE_PATH_REQUIRED)
    if any(part in {".", ".."} for part in path.parts):
        return _reject(candidate, rejection_reason=REJECT_PATH_TRAVERSAL)
    if path.name != str(candidate.get("filename")):
        return _reject(candidate, rejection_reason=REJECT_FILENAME_MISMATCH)
    if secret_filename(path.name):
        return _reject(candidate, rejection_reason=REJECT_SECRET_FILENAME)

    root_raw = str(candidate.get("source_root", ""))
    root = Path(root_raw)
    if not root.is_absolute():
        return _reject(candidate, rejection_reason=REJECT_SOURCE_ROOT_NOT_ABSOLUTE)
    if not is_approved_root(root, extra_approved_roots=extra_approved_roots):
        return _reject(candidate, rejection_reason=REJECT_SOURCE_ROOT_NOT_APPROVED)

    resolved_path = _resolved(path)
    resolved_root = _resolved(root)
    if resolved_path is None or resolved_root is None:
        return _reject(candidate, rejection_reason=REJECT_PATH_RESOLUTION_FAILED)
    if not _is_under(resolved_path, resolved_root):
        return _reject(candidate, rejection_reason=REJECT_PATH_ESCAPE)
    canonical = _resolved(CANONICAL_ROOT)
    if canonical is not None and _is_under(resolved_path, canonical):
        return _reject(candidate, rejection_reason=REJECT_CANONICAL_EXCLUDED)

    try:
        stat_result = os.lstat(path)
    except FileNotFoundError:
        return _reject(
            candidate,
            rejection_reason="FILE_NOT_FOUND",
            source_status=SOURCE_MISSING,
        )
    except OSError:
        return _reject(candidate, rejection_reason=REJECT_STAT_FAILED)

    if stat_module.S_ISLNK(stat_result.st_mode):
        return _reject(candidate, rejection_reason=REJECT_SYMLINK)
    if not stat_module.S_ISREG(stat_result.st_mode):
        return _reject(candidate, rejection_reason=REJECT_NOT_REGULAR_FILE)

    observed_size = stat_result.st_size
    observed_mtime = _iso_from_epoch(stat_result.st_mtime)
    metadata_changed = (
        observed_size != candidate.get("size_bytes")
        or not _mtime_matches(str(candidate.get("mtime")), stat_result.st_mtime)
    )
    if metadata_changed:
        return {
            "metadata_status": SOURCE_CHANGED_SINCE_INVENTORY,
            "source_status": SOURCE_CHANGED_SINCE_INVENTORY,
            "rejection_reason": None,
            "hash_required": False,
            "observed_size_bytes": observed_size,
            "observed_mtime": observed_mtime,
        }

    return {
        "metadata_status": SOURCE_PRESENT,
        "source_status": SOURCE_PRESENT,
        "rejection_reason": None,
        "hash_required": True,
        "observed_size_bytes": observed_size,
        "observed_mtime": observed_mtime,
    }


def build_hash_plan(
    fixtures: dict,
    *,
    generated_at: str,
    extra_approved_roots: tuple[str | Path, ...] = (),
) -> dict:
    unified = fixtures["unified"]
    priority_map = _candidate_priority_map(fixtures["verification_queue"])

    ordered_candidates = sorted(
        unified["candidates"], key=lambda candidate: str(candidate["source_id"])
    )
    seen_paths: dict[str, str] = {}
    plan_candidates: list[dict] = []
    rejection_counts: dict[str, int] = {}

    for candidate in ordered_candidates:
        source_id = str(candidate["source_id"])
        inspection = inspect_candidate(
            candidate, extra_approved_roots=extra_approved_roots
        )
        if inspection["rejection_reason"]:
            rejection_counts[inspection["rejection_reason"]] = (
                rejection_counts.get(inspection["rejection_reason"], 0) + 1
            )

        queue_meta = priority_map.get(source_id, {})
        normalized_path = os.path.normpath(str(candidate["absolute_path"]))
        first_owner = seen_paths.get(normalized_path)
        duplicate_path_of = None
        hash_required = bool(inspection["hash_required"])
        if hash_required and first_owner is not None:
            hash_required = False
            duplicate_path_of = first_owner
        elif hash_required:
            seen_paths[normalized_path] = source_id

        plan_candidates.append(
            {
                "source_id": source_id,
                "absolute_path": candidate.get("absolute_path"),
                "source_root": candidate.get("source_root"),
                "size_bytes": candidate.get("size_bytes"),
                "mtime": candidate.get("mtime"),
                "observed_size_bytes": inspection["observed_size_bytes"],
                "observed_mtime": inspection["observed_mtime"],
                "duplicate_group": queue_meta.get("duplicate_group"),
                "verification_priority": queue_meta.get("verification_priority"),
                "source_status": inspection["source_status"],
                "metadata_status": inspection["metadata_status"],
                "rejection_reason": inspection["rejection_reason"],
                "hash_required": hash_required,
                "hash_status": HASH_NOT_STARTED,
                "approval_required": True,
                "duplicate_path_of": duplicate_path_of,
            }
        )

    group_targets: dict[str, dict] = {}
    for candidate in plan_candidates:
        group_id = candidate["duplicate_group"]
        if not group_id:
            continue
        summary = group_targets.setdefault(
            str(group_id),
            {
                "duplicate_group": str(group_id),
                "member_count": 0,
                "hash_target_count": 0,
                "not_hashable_count": 0,
            },
        )
        summary["member_count"] += 1
        if candidate["hash_required"]:
            summary["hash_target_count"] += 1
        else:
            summary["not_hashable_count"] += 1

    hash_target_count = sum(1 for c in plan_candidates if c["hash_required"])
    source_status_counts: dict[str, int] = {}
    for candidate in plan_candidates:
        status = candidate["source_status"]
        source_status_counts[status] = source_status_counts.get(status, 0) + 1

    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE_STAGE_A,
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "stage_b_approved": STAGE_B_APPROVED_NO,
        "counts": {
            "UNIFIED_CANDIDATE_COUNT": len(plan_candidates),
            "HASH_TARGET_COUNT": hash_target_count,
            "SOURCE_MISSING_COUNT": source_status_counts.get(SOURCE_MISSING, 0),
            "SOURCE_CHANGED_COUNT": source_status_counts.get(
                SOURCE_CHANGED_SINCE_INVENTORY, 0
            ),
            "SOURCE_REJECTED_COUNT": source_status_counts.get(SOURCE_REJECTED, 0),
            "DUPLICATE_PATH_SKIPPED_COUNT": sum(
                1 for c in plan_candidates if c["duplicate_path_of"]
            ),
            "ALL_HASH_STATUS_NOT_STARTED": all(
                c["hash_status"] == HASH_NOT_STARTED for c in plan_candidates
            ),
            "ALL_APPROVAL_REQUIRED_TRUE": all(
                c["approval_required"] is True for c in plan_candidates
            ),
            "ALL_APPROVED_FALSE": True,
        },
        "source_status_counts": dict(sorted(source_status_counts.items())),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "hash_chunk_size_bytes": HASH_CHUNK_SIZE,
        "hash_algorithm": "SHA-256",
        "group_targets": sorted(group_targets.values(), key=lambda g: g["duplicate_group"]),
        "candidates": plan_candidates,
    }


def build_scope_review(plan: dict, *, generated_at: str) -> dict:
    group_targets = plan["group_targets"]
    hash_target_group_count = sum(
        1 for group in group_targets if group["hash_target_count"] > 0
    )
    return {
        "schema_version": SCOPE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE_STAGE_A,
        "content_read": False,
        "hash_computed": False,
        "real_import_executed": False,
        "counts": {
            "UNIFIED_CANDIDATE_COUNT": plan["counts"]["UNIFIED_CANDIDATE_COUNT"],
            "HASH_TARGET_COUNT": plan["counts"]["HASH_TARGET_COUNT"],
            "HASH_TARGET_GROUP_COUNT": hash_target_group_count,
            "DUPLICATE_VERIFICATION_GROUP_COUNT": len(group_targets),
            "SOURCE_MISSING_COUNT": plan["counts"]["SOURCE_MISSING_COUNT"],
            "SOURCE_CHANGED_COUNT": plan["counts"]["SOURCE_CHANGED_COUNT"],
            "SOURCE_REJECTED_COUNT": plan["counts"]["SOURCE_REJECTED_COUNT"],
            "DUPLICATE_PATH_SKIPPED_COUNT": plan["counts"]["DUPLICATE_PATH_SKIPPED_COUNT"],
            "ALL_HASH_STATUS_NOT_STARTED": plan["counts"]["ALL_HASH_STATUS_NOT_STARTED"],
            "ALL_APPROVAL_REQUIRED_TRUE": plan["counts"]["ALL_APPROVAL_REQUIRED_TRUE"],
        },
        "source_status_counts": plan["source_status_counts"],
        "rejection_reason_counts": plan["rejection_reason_counts"],
        "group_targets": group_targets,
        "safety": {
            "approved_roots_only": True,
            "symlink_rejected": True,
            "path_traversal_rejected": True,
            "secret_filename_rejected": True,
            "canonical_main_excluded": True,
            "body_not_read_in_stage_a": True,
            "delete_move_modify_sources": False,
        },
    }


def build_stage_a(
    fixtures: dict,
    *,
    expected: dict | None = None,
    generated_at: str | None = None,
    extra_approved_roots: tuple[str | Path, ...] = (),
) -> dict:
    reconciliation = validate_inputs(fixtures, expected=expected or EXPECTED_BASELINE)
    if not reconciliation["inputs_valid"]:
        raise InputError(
            BLOCKED_INVALID_INPUT,
            "inputs",
            "input reconciliation failed: "
            + ",".join(item["key"] for item in reconciliation["mismatches"]),
        )
    timestamp = generated_at or _now_iso()
    plan = build_hash_plan(
        fixtures,
        generated_at=timestamp,
        extra_approved_roots=extra_approved_roots,
    )
    scope = build_scope_review(plan, generated_at=timestamp)
    return {
        "plan": plan,
        "scope": scope,
        "reconciliation": reconciliation,
        "counts": {
            "UNIFIED_CANDIDATE_COUNT": plan["counts"]["UNIFIED_CANDIDATE_COUNT"],
            "HASH_TARGET_COUNT": plan["counts"]["HASH_TARGET_COUNT"],
            "HASH_TARGET_GROUP_COUNT": scope["counts"]["HASH_TARGET_GROUP_COUNT"],
            "SOURCE_MISSING_COUNT": plan["counts"]["SOURCE_MISSING_COUNT"],
            "SOURCE_CHANGED_COUNT": plan["counts"]["SOURCE_CHANGED_COUNT"],
            "SOURCE_REJECTED_COUNT": plan["counts"]["SOURCE_REJECTED_COUNT"],
        },
        "generated_at": timestamp,
    }


def hash_file(
    path: str | Path,
    *,
    expected_size: int,
    expected_mtime: str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    chunk_size: int = HASH_CHUNK_SIZE,
) -> dict:
    """Stream a file through SHA-256 without retaining or logging its body."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        return {"status": READ_FAILED, "error_reason": type(exc).__name__}

    hasher = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if not stat_module.S_ISREG(before.st_mode):
            return {"status": READ_FAILED, "error_reason": "NOT_REGULAR_FILE"}
        if expected_device is not None and (
            before.st_dev != expected_device or before.st_ino != expected_inode
        ):
            return {
                "status": SOURCE_CHANGED_DURING_HASH,
                "error_reason": "DEVICE_OR_INODE_CHANGED",
            }
        if before.st_size != expected_size or not _mtime_matches(
            expected_mtime, before.st_mtime
        ):
            return {
                "status": SOURCE_CHANGED_DURING_HASH,
                "error_reason": "METADATA_CHANGED",
            }

        bytes_read = 0
        while True:
            chunk = os.read(descriptor, chunk_size)
            if not chunk:
                break
            bytes_read += len(chunk)
            hasher.update(chunk)

        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or not _mtime_matches(expected_mtime, after.st_mtime)
        ):
            return {
                "status": SOURCE_CHANGED_DURING_HASH,
                "error_reason": "CHANGED_DURING_READ",
            }
        if bytes_read != before.st_size:
            return {
                "status": SOURCE_CHANGED_DURING_HASH,
                "error_reason": "SIZE_CHANGED_DURING_READ",
            }
        return {
            "status": HASHED,
            "sha256": hasher.hexdigest(),
            "bytes_read": bytes_read,
            "body_stored": False,
        }
    except OSError as exc:
        return {"status": READ_FAILED, "error_reason": type(exc).__name__}
    finally:
        os.close(descriptor)


def execute_hash_plan(
    plan: dict,
    *,
    generated_at: str,
    chunk_size: int = HASH_CHUNK_SIZE,
) -> dict:
    entries: list[dict] = []
    hash_groups: dict[str, list[str]] = {}

    for candidate in plan["candidates"]:
        source_id = str(candidate["source_id"])
        entry = {
            "source_id": source_id,
            "absolute_path": candidate["absolute_path"],
            "source_root": candidate["source_root"],
            "size_bytes": candidate["size_bytes"],
            "mtime": candidate["mtime"],
            "duplicate_group": candidate["duplicate_group"],
            "verification_priority": candidate["verification_priority"],
            "provenance_status": PROVENANCE_UNKNOWN,
            "hash_required": candidate["hash_required"],
            "sha256": None,
            "bytes_read": None,
            "verification_status": NOT_VERIFIED,
            "error_reason": None,
            "body_stored": False,
        }
        if not candidate["hash_required"]:
            entry["error_reason"] = candidate.get("rejection_reason") or (
                "SOURCE_NOT_HASH_ELIGIBLE"
            )
            entries.append(entry)
            continue

        path = Path(candidate["absolute_path"])
        try:
            pre = os.lstat(path)
        except FileNotFoundError:
            entry["verification_status"] = READ_FAILED
            entry["error_reason"] = "FILE_NOT_FOUND"
            entries.append(entry)
            continue
        except OSError:
            entry["verification_status"] = READ_FAILED
            entry["error_reason"] = "STAT_FAILED"
            entries.append(entry)
            continue

        if stat_module.S_ISLNK(pre.st_mode):
            entry["verification_status"] = READ_FAILED
            entry["error_reason"] = REJECT_SYMLINK
            entries.append(entry)
            continue
        if not stat_module.S_ISREG(pre.st_mode):
            entry["verification_status"] = READ_FAILED
            entry["error_reason"] = REJECT_NOT_REGULAR_FILE
            entries.append(entry)
            continue
        if pre.st_size != candidate.get("size_bytes") or not _mtime_matches(
            str(candidate.get("mtime")), pre.st_mtime
        ):
            entry["verification_status"] = SOURCE_CHANGED_DURING_HASH
            entry["error_reason"] = "METADATA_CHANGED_BEFORE_HASH"
            entries.append(entry)
            continue

        result = hash_file(
            path,
            expected_size=int(candidate["size_bytes"]),
            expected_mtime=str(candidate["mtime"]),
            expected_device=pre.st_dev,
            expected_inode=pre.st_ino,
            chunk_size=chunk_size,
        )
        if result["status"] == HASHED:
            entry["sha256"] = result["sha256"]
            entry["bytes_read"] = result["bytes_read"]
            entry["verification_status"] = HASHED
            hash_groups.setdefault(result["sha256"], []).append(source_id)
        else:
            entry["verification_status"] = result["status"]
            entry["error_reason"] = result.get("error_reason")
        entries.append(entry)

    for entry in entries:
        if entry["verification_status"] != HASHED:
            continue
        members = hash_groups.get(str(entry["sha256"]), [])
        entry["verification_status"] = (
            CONTENT_IDENTICAL if len(members) > 1 else CONTENT_DIFFERENT
        )

    status_counts: dict[str, int] = {}
    for entry in entries:
        status = entry["verification_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE_STAGE_B,
        "content_read": True,
        "body_stored": False,
        "hash_computed": True,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "counts": {
            "HASH_EXECUTED_COUNT": sum(
                1 for entry in entries if entry["sha256"] is not None
            ),
            "CONTENT_IDENTICAL_COUNT": status_counts.get(CONTENT_IDENTICAL, 0),
            "CONTENT_DIFFERENT_COUNT": status_counts.get(CONTENT_DIFFERENT, 0),
            "READ_FAILED_COUNT": status_counts.get(READ_FAILED, 0),
            "SOURCE_CHANGED_DURING_HASH_COUNT": status_counts.get(
                SOURCE_CHANGED_DURING_HASH, 0
            ),
            "NOT_VERIFIED_COUNT": status_counts.get(NOT_VERIFIED, 0),
            "CONTENT_IDENTICAL_GROUP_COUNT": sum(
                1 for members in hash_groups.values() if len(members) > 1
            ),
        },
        "verification_status_counts": dict(sorted(status_counts.items())),
        "entries": entries,
    }


def build_confirmed_duplicates(results: dict) -> dict:
    by_hash: dict[str, list[dict]] = {}
    for entry in results["entries"]:
        if entry["sha256"] and entry["verification_status"] in {
            CONTENT_IDENTICAL,
            CONTENT_DIFFERENT,
        }:
            by_hash.setdefault(entry["sha256"], []).append(entry)

    groups: list[dict] = []
    for content_hash, members in sorted(by_hash.items()):
        if len(members) < 2:
            continue
        member_source_ids = sorted(str(member["source_id"]) for member in members)
        path_by_id = {
            str(member["source_id"]): member["absolute_path"] for member in members
        }
        groups.append(
            {
                "content_hash": content_hash,
                "member_count": len(members),
                "representative_source_id": member_source_ids[0],
                "representative_is_import_approval": False,
                "member_source_ids": member_source_ids,
                "source_paths": [path_by_id[source_id] for source_id in member_source_ids],
                "verification_status": "CONTENT_IDENTICAL_CONFIRMED",
                "approved": False,
                "import_ready": False,
            }
        )
    groups.sort(key=lambda group: group["content_hash"])
    return {
        "schema_version": CONFIRMED_SCHEMA_VERSION,
        "generated_at": results["generated_at"],
        "mode": MODE_STAGE_B,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "content_hash_algorithm": "SHA-256",
        "sources_preserved": True,
        "counts": {
            "CONFIRMED_DUPLICATE_GROUP_COUNT": len(groups),
            "CONFIRMED_DUPLICATE_MEMBER_COUNT": sum(
                group["member_count"] for group in groups
            ),
            "ALL_APPROVED_FALSE": all(group["approved"] is False for group in groups),
        },
        "groups": groups,
    }


def build_unique_content_candidates(results: dict) -> dict:
    entries = [
        {
            "source_id": entry["source_id"],
            "absolute_path": entry["absolute_path"],
            "sha256": entry["sha256"],
            "verification_status": entry["verification_status"],
            "approved": False,
            "import_ready": False,
        }
        for entry in results["entries"]
        if entry["verification_status"] == CONTENT_DIFFERENT
    ]
    entries.sort(key=lambda entry: str(entry["source_id"]))
    return {
        "schema_version": UNIQUE_SCHEMA_VERSION,
        "generated_at": results["generated_at"],
        "mode": MODE_STAGE_B,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "counts": {
            "UNIQUE_CONTENT_CANDIDATE_COUNT": len(entries),
            "ALL_APPROVED_FALSE": all(entry["approved"] is False for entry in entries),
        },
        "entries": entries,
    }


def build_stage_b(
    fixtures: dict,
    *,
    approval: str,
    expected: dict | None = None,
    generated_at: str | None = None,
    chunk_size: int = HASH_CHUNK_SIZE,
    extra_approved_roots: tuple[str | Path, ...] = (),
) -> dict:
    if approval != STAGE_B_APPROVAL_TOKEN:
        raise PermissionError(
            "STAGE_B_NOT_APPROVED: explicit STAGE_B_APPROVED token is required"
        )
    stage_a = build_stage_a(
        fixtures,
        expected=expected,
        generated_at=generated_at,
        extra_approved_roots=extra_approved_roots,
    )
    timestamp = stage_a["generated_at"]
    results = execute_hash_plan(
        stage_a["plan"], generated_at=timestamp, chunk_size=chunk_size
    )
    confirmed = build_confirmed_duplicates(results)
    unique = build_unique_content_candidates(results)
    return {
        "plan": stage_a["plan"],
        "scope": stage_a["scope"],
        "results": results,
        "confirmed_duplicates": confirmed,
        "unique_content_candidates": unique,
        "generated_at": timestamp,
        "counts": {
            "UNIFIED_CANDIDATE_COUNT": stage_a["counts"]["UNIFIED_CANDIDATE_COUNT"],
            "HASH_TARGET_COUNT": stage_a["counts"]["HASH_TARGET_COUNT"],
            "HASH_EXECUTED_COUNT": results["counts"]["HASH_EXECUTED_COUNT"],
            "CONFIRMED_DUPLICATE_GROUP_COUNT": confirmed["counts"][
                "CONFIRMED_DUPLICATE_GROUP_COUNT"
            ],
            "CONFIRMED_DUPLICATE_MEMBER_COUNT": confirmed["counts"][
                "CONFIRMED_DUPLICATE_MEMBER_COUNT"
            ],
            "UNIQUE_CONTENT_CANDIDATE_COUNT": unique["counts"][
                "UNIQUE_CONTENT_CANDIDATE_COUNT"
            ],
            "READ_FAILED_COUNT": results["counts"]["READ_FAILED_COUNT"],
            "SOURCE_CHANGED_DURING_HASH_COUNT": results["counts"][
                "SOURCE_CHANGED_DURING_HASH_COUNT"
            ],
            "NOT_VERIFIED_COUNT": results["counts"]["NOT_VERIFIED_COUNT"],
        },
    }


def render_approval_request(scope: dict, *, generated_at: str) -> str:
    counts = scope["counts"]
    lines = [
        "# BC-11E-5 STAGE_B Hash Execution Approval Request",
        "",
        f"- generated_at: `{generated_at}`",
        "- STAGE_B_APPROVED: `NO`",
        "- mode: `OFFLINE_CONTENT_HASH_VERIFICATION`",
        "",
        "## Scope",
        "",
        f"- UNIFIED_CANDIDATE_COUNT: {counts['UNIFIED_CANDIDATE_COUNT']}",
        f"- HASH_TARGET_COUNT: {counts['HASH_TARGET_COUNT']}",
        f"- HASH_TARGET_GROUP_COUNT: {counts['HASH_TARGET_GROUP_COUNT']}",
        f"- SOURCE_MISSING_COUNT: {counts['SOURCE_MISSING_COUNT']}",
        f"- SOURCE_CHANGED_COUNT: {counts['SOURCE_CHANGED_COUNT']}",
        f"- SOURCE_REJECTED_COUNT: {counts['SOURCE_REJECTED_COUNT']}",
        "",
        "## What STAGE_B will do",
        "",
        "- Open each `hash_required=true` file read-only and compute SHA-256 in 1 MiB chunks.",
        "- Use `O_NOFOLLOW` plus an `fstat` regular-file check.",
        "- Record only hash values and metadata, never report bodies.",
        "- Group identical hashes and keep every storage location.",
        "- Never delete, move, or modify a source file.",
        "",
        "## What STAGE_B will not do",
        "",
        "- No real import, no production database access, no approved manifest.",
        "- No provenance confirmation from a hash match.",
        "- No automatic execution: STAGE_A never starts STAGE_B.",
        "",
        "## Gate",
        "",
        "STAGE_B must only run after the operator explicitly approves and the",
        "command is invoked as:",
        "",
        "```",
        "python3 scripts/bc11e_content_deduplication.py --stage-b "
        "--stage-b-approval STAGE_B_APPROVED",
        "```",
        "",
        "Pasting this task instruction alone does not approve STAGE_B.",
        "",
    ]
    return "\n".join(lines)


def render_stage_a_final(stage_a: dict, *, head: str, test_summary: str) -> str:
    counts = stage_a["counts"]
    lines = [
        "# BC-11E-5 STAGE_A Final Report",
        "",
        "TASK_ID=TRADINGAI-WORK-BC-11E5-CONTENT-DEDUPLICATION-1",
        f"VERDICT={VERDICT_STAGE_A_READY}",
        "WORKTREE=/home/joe4410joe/tradingai_prod_v1.worktrees/knowledge-import-readiness",
        "BRANCH=feature/knowledge-import-readiness",
        f"HEAD_BEFORE={head}",
        f"HEAD_AFTER={head}",
        "",
        f"UNIFIED_CANDIDATE_COUNT={counts['UNIFIED_CANDIDATE_COUNT']}",
        f"HASH_TARGET_COUNT={counts['HASH_TARGET_COUNT']}",
        f"HASH_TARGET_GROUP_COUNT={counts['HASH_TARGET_GROUP_COUNT']}",
        f"SOURCE_MISSING_COUNT={counts['SOURCE_MISSING_COUNT']}",
        f"SOURCE_CHANGED_COUNT={counts['SOURCE_CHANGED_COUNT']}",
        f"SOURCE_REJECTED_COUNT={counts['SOURCE_REJECTED_COUNT']}",
        "",
        "HASH_PLAN_CREATED=YES",
        "HASH_SCOPE_REVIEW_CREATED=YES",
        "HASH_APPROVAL_REQUEST_CREATED=YES",
        "NO_SOURCE_BODY_READ=YES",
        "NO_REAL_HASH_EXECUTED=YES",
        "ALL_HASH_STATUS_NOT_STARTED=YES",
        "ALL_APPROVAL_REQUIRED_TRUE=YES",
        "REAL_IMPORT_EXECUTED=NO",
        "PRODUCTION_DB_UNCHANGED=YES",
        "CANONICAL_UNCHANGED=YES",
        "WORK_AA_UNCHANGED=YES",
        "BB_CC_UNCHANGED=YES",
        "",
        f"TEST_RESULTS={test_summary}",
        "COMMIT=PENDING",
        "GIT_PUSH=NO",
        "PRODUCTION_RESTART=NO",
        "NEXT_REQUIRED_APPROVAL=STAGE_B_APPROVED",
        "",
    ]
    return "\n".join(lines)


def render_stage_b_final(stage_b: dict) -> str:
    counts = stage_b["counts"]
    lines = [
        "# BC-11E-5 Content Verification Final Report",
        "",
        "TASK_ID=TRADINGAI-WORK-BC-11E5-CONTENT-DEDUPLICATION-1",
        "VERDICT=BC11E5_CONTENT_VERIFICATION_COMPLETE",
        f"generated_at={stage_b['generated_at']}",
        "",
        f"UNIFIED_CANDIDATE_COUNT={counts['UNIFIED_CANDIDATE_COUNT']}",
        f"HASH_TARGET_COUNT={counts['HASH_TARGET_COUNT']}",
        f"HASH_EXECUTED_COUNT={counts['HASH_EXECUTED_COUNT']}",
        f"CONFIRMED_DUPLICATE_GROUP_COUNT={counts['CONFIRMED_DUPLICATE_GROUP_COUNT']}",
        f"CONFIRMED_DUPLICATE_MEMBER_COUNT={counts['CONFIRMED_DUPLICATE_MEMBER_COUNT']}",
        f"UNIQUE_CONTENT_CANDIDATE_COUNT={counts['UNIQUE_CONTENT_CANDIDATE_COUNT']}",
        f"READ_FAILED_COUNT={counts['READ_FAILED_COUNT']}",
        f"SOURCE_CHANGED_DURING_HASH_COUNT={counts['SOURCE_CHANGED_DURING_HASH_COUNT']}",
        f"NOT_VERIFIED_COUNT={counts['NOT_VERIFIED_COUNT']}",
        "",
        "REAL_IMPORT_EXECUTED=NO",
        "ALL_APPROVED_FALSE=YES",
        "ALL_IMPORT_READY_FALSE=YES",
        "SOURCES_PRESERVED=YES",
        "PROVENANCE_NOT_INFERRED_FROM_HASH=YES",
        "",
    ]
    return "\n".join(lines)


def write_stage_a_outputs(
    stage_a: dict,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    head: str = "UNKNOWN",
    test_summary: str = "PENDING",
) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = {
        "hash_execution_plan": target / PLAN_JSON_NAME,
        "hash_scope_review": target / SCOPE_JSON_NAME,
        "hash_approval_request": target / APPROVAL_MD_NAME,
        "stage_a_final": target / STAGE_A_FINAL_MD_NAME,
    }
    paths["hash_execution_plan"].write_text(
        json.dumps(stage_a["plan"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["hash_scope_review"].write_text(
        json.dumps(stage_a["scope"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["hash_approval_request"].write_text(
        render_approval_request(stage_a["scope"], generated_at=stage_a["generated_at"])
        + "\n",
        encoding="utf-8",
    )
    paths["stage_a_final"].write_text(
        render_stage_a_final(stage_a, head=head, test_summary=test_summary) + "\n",
        encoding="utf-8",
    )
    return {key: str(path) for key, path in paths.items()}


def write_stage_b_outputs(
    stage_b: dict, *, output_dir: str | Path = DEFAULT_OUTPUT_DIR
) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = {
        "content_hash_results": target / RESULTS_JSON_NAME,
        "confirmed_duplicates": target / CONFIRMED_JSON_NAME,
        "unique_content_candidates": target / UNIQUE_JSON_NAME,
        "content_verification_final": target / STAGE_B_FINAL_MD_NAME,
    }
    paths["content_hash_results"].write_text(
        json.dumps(stage_b["results"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["confirmed_duplicates"].write_text(
        json.dumps(stage_b["confirmed_duplicates"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["unique_content_candidates"].write_text(
        json.dumps(stage_b["unique_content_candidates"], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    paths["content_verification_final"].write_text(
        render_stage_b_final(stage_b) + "\n", encoding="utf-8"
    )
    return {key: str(path) for key, path in paths.items()}


INPUT_KEYS = (
    "unified",
    "duplicate_review",
    "manifest",
    "verification_plan",
    "provenance_plan",
    "verification_queue",
    "readiness",
)


def load_fixtures(paths: dict[str, str | Path]) -> dict:
    fixtures: dict = {}
    for key in INPUT_KEYS:
        fixtures[key] = load_input(paths[key])
    return fixtures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-a", action="store_true", help="plan hashes only (default)")
    parser.add_argument("--stage-b", action="store_true", help="execute approved hashing")
    parser.add_argument(
        "--stage-b-approval",
        default=STAGE_B_APPROVED_NO,
        help="must equal STAGE_B_APPROVED to run STAGE_B",
    )
    parser.add_argument("--unified", default=str(DEFAULT_UNIFIED_PATH))
    parser.add_argument("--duplicate-review", default=str(DEFAULT_DUPLICATE_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--verification-plan", default=str(DEFAULT_VERIFICATION_PLAN_PATH))
    parser.add_argument("--provenance-plan", default=str(DEFAULT_PROVENANCE_PLAN_PATH))
    parser.add_argument("--verification-queue", default=str(DEFAULT_QUEUE_PATH))
    parser.add_argument("--readiness", default=str(DEFAULT_READINESS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    return parser


def _fixture_paths(args: argparse.Namespace) -> dict[str, str | Path]:
    return {
        "unified": args.unified,
        "duplicate_review": args.duplicate_review,
        "manifest": args.manifest,
        "verification_plan": args.verification_plan,
        "provenance_plan": args.provenance_plan,
        "verification_queue": args.verification_queue,
        "readiness": args.readiness,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stage_b = bool(args.stage_b)
    if stage_b and args.stage_b_approval != STAGE_B_APPROVAL_TOKEN:
        print(
            json.dumps(
                {
                    "status": "STAGE_B_NOT_APPROVED",
                    "verdict": VERDICT_SECURITY_BLOCKED,
                    "detail": (
                        "STAGE_B requires an explicit "
                        f"--stage-b-approval {STAGE_B_APPROVAL_TOKEN} token"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3

    try:
        fixtures = load_fixtures(_fixture_paths(args))
    except InputError as exc:
        print(
            json.dumps(
                {"status": exc.code, "path": exc.path, "detail": exc.detail},
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    try:
        if stage_b:
            stage_b_result = build_stage_b(
                fixtures,
                approval=args.stage_b_approval,
                generated_at=args.generated_at or None,
            )
        else:
            stage_a_result = build_stage_a(
                fixtures, generated_at=args.generated_at or None
            )
    except InputError as exc:
        print(
            json.dumps(
                {
                    "status": exc.code,
                    "verdict": VERDICT_INPUT_BLOCKED,
                    "detail": exc.detail,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    except PermissionError as exc:
        print(
            json.dumps(
                {"status": "STAGE_B_NOT_APPROVED", "verdict": VERDICT_SECURITY_BLOCKED, "detail": str(exc)},
                indent=2,
                sort_keys=True,
            )
        )
        return 3

    if stage_b:
        outputs = write_stage_b_outputs(stage_b_result, output_dir=args.output_dir)
        summary = {
            "status": INPUTS_VALID,
            "verdict": "BC11E5_CONTENT_VERIFICATION_COMPLETE",
            "counts": stage_b_result["counts"],
            "outputs": outputs,
        }
    else:
        outputs = write_stage_a_outputs(stage_a_result, output_dir=args.output_dir)
        summary = {
            "status": INPUTS_VALID,
            "verdict": VERDICT_STAGE_A_READY,
            "counts": stage_a_result["counts"],
            "outputs": outputs,
        }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
