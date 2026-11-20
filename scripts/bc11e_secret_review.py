#!/usr/bin/env python3
"""BC-11E-7A historical agent report secret review readiness.

This module implements the secret-detection engine, the approved-root path
safety gate, provenance review planning, and the pre-import redaction policy
needed before any real historical report may be reviewed for secrets.

Safety boundaries enforced here:

* STAGE_A (default, ``--stage-a``) consumes only the already-produced
  BC-11E-5/BC-11E-6 metadata artefacts. It never opens a real report body and
  never runs the detector against a real source file.
* The detector is exercised only with synthetic in-memory fixtures in the test
  suite. A real source scan requires a separate explicit operator approval and
  is blocked by :func:`build_approval_gate`.
* Findings never store a secret value, a secret fragment, surrounding report
  text, or a hash of the secret value.
* Nothing outside the requested output directory is written. No import,
  production database access, or runtime mutation occurs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat as stat_module
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_hub.config import DEFAULT_REPORT_ROOTS  # noqa: E402
from backend.knowledge_hub.security import secret_filename  # noqa: E402

MODE_STAGE_A = "OFFLINE_SECRET_REVIEW_PLAN_ONLY"

TASK_ID = "TRADINGAI-WORK-BC-11E7A-SECRET-REVIEW-READINESS-1"
VERDICT_READY = "BC11E7A_STAGE_A_SECRET_REVIEW_READY"
VERDICT_INPUT_BLOCKED = "BC11E7A_INPUT_BLOCKED"
VERDICT_SECURITY_BLOCKED = "BC11E7A_SECURITY_BLOCKED"
VERDICT_TEST_FAILED = "BC11E7A_TEST_FAILED"

SCAN_PLAN_SCHEMA_VERSION = "tradingai-bc11e7a-secret-scan-plan/v1"
DETECTION_POLICY_SCHEMA_VERSION = "tradingai-bc11e7a-secret-detection-policy/v1"
PROVENANCE_PLAN_SCHEMA_VERSION = "tradingai-bc11e7a-provenance-review-plan/v1"
REDACTION_POLICY_SCHEMA_VERSION = "tradingai-bc11e7a-redaction-policy/v1"

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_CONTENT_REVIEW_PATH = DEFAULT_OUTPUT_DIR / "BC11E6_CONTENT_UNIQUE_REVIEW.json"
DEFAULT_PROVENANCE_QUEUE_PATH = DEFAULT_OUTPUT_DIR / "BC11E6_PROVENANCE_REVIEW_QUEUE.json"
DEFAULT_MANIFEST_REVIEW_PATH = DEFAULT_OUTPUT_DIR / "BC11E6_IMPORT_MANIFEST_REVIEW.json"
DEFAULT_IMPORT_TARGET_FINAL_PATH = DEFAULT_OUTPUT_DIR / "BC11E6_IMPORT_TARGET_FINAL.md"
DEFAULT_HASH_RESULTS_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_CONTENT_HASH_RESULTS.json"
DEFAULT_CONFIRMED_DUPLICATES_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_CONFIRMED_DUPLICATES.json"
DEFAULT_UNIQUE_CONTENT_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_UNIQUE_CONTENT_CANDIDATES.json"

SCAN_PLAN_JSON_NAME = "BC11E7A_SECRET_SCAN_PLAN.json"
DETECTION_POLICY_JSON_NAME = "BC11E7A_SECRET_DETECTION_POLICY.json"
PROVENANCE_PLAN_JSON_NAME = "BC11E7A_PROVENANCE_REVIEW_PLAN.json"
REDACTION_POLICY_JSON_NAME = "BC11E7A_REDACTION_POLICY.json"
APPROVAL_REQUEST_MD_NAME = "BC11E7A_REAL_SCAN_APPROVAL_REQUEST.md"
FINAL_MD_NAME = "BC11E7A_STAGE_A_FINAL.md"

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

MAX_SCAN_BYTES = 16 * 1024 * 1024
SCAN_CHUNK_SIZE = 1024 * 1024
MTIME_TOLERANCE_SECONDS = 1e-5

INPUTS_VALID = "INPUTS_VALID"
INPUT_COUNT_MISMATCH = "INPUT_COUNT_MISMATCH"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"

SOURCE_TRUTH_CLASS = "AGENT_REPORTED"
AUTHORITY_SCOPE = "NONE"
PROVENANCE_UNKNOWN = "UNKNOWN"

SECRET_REVIEW_NOT_PERFORMED = "NOT_PERFORMED"
SECRET_REVIEW_REQUIRED = True
SECRET_SCAN_APPROVED = False

SCAN_NOT_STARTED = "NOT_STARTED"

REVIEW_NOT_STARTED = "NOT_STARTED"
REVIEW_NOT_REVIEWED = "NOT_REVIEWED"
APPROVAL_NOT_APPROVED = "NOT_APPROVED"

SECRET_TYPES: tuple[str, ...] = (
    "API_KEY",
    "API_SECRET",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "AUTHORIZATION_HEADER",
    "BEARER_TOKEN",
    "SESSION_COOKIE",
    "PASSWORD",
    "PRIVATE_KEY",
    "DATABASE_CREDENTIAL",
    "WEBHOOK_SECRET",
    "CLOUD_CREDENTIAL",
    "EXCHANGE_API_CREDENTIAL",
    "CREDENTIAL_LIKE_TEXT",
)

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_UNKNOWN = "UNKNOWN"
SEVERITY_ORDER = (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_UNKNOWN,
)

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_ORDER = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)

METHOD_PATTERN = "PATTERN"
METHOD_KEY_VALUE = "KEY_VALUE_ASSIGNMENT"
METHOD_CONTEXT = "CREDENTIAL_LIKE_CONTEXT"
METHOD_ENTROPY = "ENTROPY_HEURISTIC"
DETECTION_METHODS: tuple[str, ...] = (
    METHOD_PATTERN,
    METHOD_KEY_VALUE,
    METHOD_CONTEXT,
    METHOD_ENTROPY,
)

SEVERITY_BY_TYPE: dict[str, str] = {
    "PRIVATE_KEY": SEVERITY_CRITICAL,
    "EXCHANGE_API_CREDENTIAL": SEVERITY_CRITICAL,
    "DATABASE_CREDENTIAL": SEVERITY_CRITICAL,
    "CLOUD_CREDENTIAL": SEVERITY_CRITICAL,
    "API_SECRET": SEVERITY_HIGH,
    "ACCESS_TOKEN": SEVERITY_HIGH,
    "REFRESH_TOKEN": SEVERITY_HIGH,
    "AUTHORIZATION_HEADER": SEVERITY_HIGH,
    "BEARER_TOKEN": SEVERITY_HIGH,
    "SESSION_COOKIE": SEVERITY_HIGH,
    "PASSWORD": SEVERITY_HIGH,
    "WEBHOOK_SECRET": SEVERITY_HIGH,
    "API_KEY": SEVERITY_HIGH,
    "CREDENTIAL_LIKE_TEXT": SEVERITY_MEDIUM,
    "UNKNOWN": SEVERITY_UNKNOWN,
}

ACTION_REDACT = "REDACT_BEFORE_IMPORT"
ACTION_REVIEW = "REVIEW_REQUIRED"
ACTION_EXCLUDE = "EXCLUDE_FROM_IMPORT"
REDACTION_ACTIONS: tuple[str, ...] = (ACTION_REDACT, ACTION_REVIEW, ACTION_EXCLUDE)

ACTION_BY_SEVERITY: dict[str, str] = {
    SEVERITY_CRITICAL: ACTION_EXCLUDE,
    SEVERITY_HIGH: ACTION_REDACT,
    SEVERITY_MEDIUM: ACTION_REVIEW,
    SEVERITY_LOW: ACTION_REDACT,
    SEVERITY_UNKNOWN: ACTION_REVIEW,
}

REAL_SCAN_APPROVAL_TOKEN = "REAL_SOURCE_SCAN_APPROVED"

EXPECTED_BASELINE = {
    "CONTENT_UNIQUE_COUNT": 491,
    "SOURCE_REFERENCE_COUNT": 6646,
    "DISTINCT_CONTENT_HASHES": 491,
    "SOURCE_ENTRY_COUNT": 6646,
    "SINGLETON_CONTENT_COUNT": 461,
    "CONFIRMED_DUPLICATE_GROUPS": 30,
    "ADDITIONAL_COPY_COUNT": 6155,
    "PROVENANCE_REVIEW_COUNT": 491,
    "IMPORT_MANIFEST_COUNT": 491,
    "ALL_SECRET_REVIEW_NOT_PERFORMED": True,
    "ALL_PROVENANCE_UNKNOWN": True,
    "ALL_APPROVED_FALSE": True,
    "ALL_IMPORT_READY_FALSE": True,
    "ALL_REAL_IMPORT_ALLOWED_FALSE": True,
}

# ---------------------------------------------------------------------------
# Stage B constants (approved, read-only real source content scan)
# ---------------------------------------------------------------------------

MODE_STAGE_B = "APPROVED_READ_ONLY_SOURCE_CONTENT_SCAN"

TASK_ID_STAGE_B = "TRADINGAI-WORK-BC-11E7A-STAGE-B-REAL-SECRET-SCAN-1"
VERDICT_STAGE_B_COMPLETE = "BC11E7A_STAGE_B_REAL_SCAN_COMPLETE"
VERDICT_STAGE_B_PARTIAL = "BC11E7A_STAGE_B_PARTIAL_REVIEW_REQUIRED"

SCAN_RESULTS_SCHEMA_VERSION = "tradingai-bc11e7a-real-scan-results/v1"
FINDINGS_SUMMARY_SCHEMA_VERSION = "tradingai-bc11e7a-secret-findings-summary/v1"
PROVENANCE_EVIDENCE_SCHEMA_VERSION = (
    "tradingai-bc11e7a-provenance-evidence-review/v1"
)
IMPORT_ELIGIBILITY_SCHEMA_VERSION = (
    "tradingai-bc11e7a-import-eligibility-review/v1"
)

DEFAULT_SECRET_SCAN_PLAN_PATH = DEFAULT_OUTPUT_DIR / SCAN_PLAN_JSON_NAME
DEFAULT_DETECTION_POLICY_PATH = DEFAULT_OUTPUT_DIR / DETECTION_POLICY_JSON_NAME
DEFAULT_PROVENANCE_PLAN_PATH = DEFAULT_OUTPUT_DIR / PROVENANCE_PLAN_JSON_NAME
DEFAULT_REDACTION_POLICY_PATH = DEFAULT_OUTPUT_DIR / REDACTION_POLICY_JSON_NAME
DEFAULT_STAGE_A_FINAL_PATH = DEFAULT_OUTPUT_DIR / FINAL_MD_NAME

REAL_SCAN_RESULTS_JSON_NAME = "BC11E7A_REAL_SCAN_RESULTS.json"
SECRET_FINDINGS_SUMMARY_JSON_NAME = "BC11E7A_SECRET_FINDINGS_SUMMARY.json"
PROVENANCE_EVIDENCE_JSON_NAME = "BC11E7A_PROVENANCE_EVIDENCE_REVIEW.json"
IMPORT_ELIGIBILITY_JSON_NAME = "BC11E7A_IMPORT_ELIGIBILITY_REVIEW.json"
STAGE_B_FINAL_MD_NAME = "BC11E7A_STAGE_B_FINAL.md"

EXPECTED_TARGET_COUNT = 491
EXPECTED_SOURCE_REFERENCE_COUNT = 6646

SCAN_COMPLETED_NO_FINDINGS = "SCAN_COMPLETED_NO_FINDINGS"
SCAN_COMPLETED_FINDINGS = "SCAN_COMPLETED_FINDINGS"
SCAN_FAILED = "SCAN_FAILED"
SOURCE_CHANGED = "SOURCE_CHANGED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
SOURCE_REJECTED = "SOURCE_REJECTED"

SCAN_COMPLETED_STATUSES: tuple[str, ...] = (
    SCAN_COMPLETED_NO_FINDINGS,
    SCAN_COMPLETED_FINDINGS,
)
SCAN_RESULT_STATUSES: tuple[str, ...] = (
    *SCAN_COMPLETED_STATUSES,
    SCAN_FAILED,
    SOURCE_CHANGED,
    SOURCE_UNAVAILABLE,
    SOURCE_REJECTED,
)

ELIGIBLE_CANDIDATE = "ELIGIBLE_CANDIDATE"
REDACTION_REQUIRED = "REDACTION_REQUIRED"
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"

PROVENANCE_CURSOR_CANDIDATE = "CURSOR_CANDIDATE"
PROVENANCE_OPENCODE_CANDIDATE = "OPENCODE_CANDIDATE"
PROVENANCE_OTHER_AGENT_CANDIDATE = "OTHER_AGENT_CANDIDATE"
PROVENANCE_CHATGPT_CANDIDATE = "CHATGPT_CANDIDATE"
PROVENANCE_UNKNOWN_CLASS = "UNKNOWN"
PROVENANCE_CONFIRMED = "CONFIRMED"
PROVENANCE_CLASS_ORDER: tuple[str, ...] = (
    PROVENANCE_CURSOR_CANDIDATE,
    PROVENANCE_OPENCODE_CANDIDATE,
    PROVENANCE_CHATGPT_CANDIDATE,
    PROVENANCE_OTHER_AGENT_CANDIDATE,
)

REQUIRED_STAGE_B_CANDIDATE_FIELDS = (
    "content_hash",
    "representative_source_id",
    "absolute_path",
    "source_root",
    "size_bytes",
    "mtime",
)

REQUIRED_CONTENT_RECORD_FIELDS = (
    "content_hash",
    "representative_source_id",
    "member_source_ids",
    "source_paths",
    "member_count",
    "review_priority",
    "secret_review_status",
    "provenance_status",
    "approved",
    "import_ready",
    "real_import_allowed",
    "source_truth_class",
    "authority_scope",
)

REQUIRED_HASH_ENTRY_FIELDS = (
    "source_id",
    "absolute_path",
    "source_root",
    "sha256",
    "size_bytes",
    "mtime",
)

REQUIRED_PROVENANCE_ENTRY_FIELDS = (
    "content_hash",
    "representative_source_id",
    "member_source_ids",
    "provenance_status",
    "classifications",
)

REQUIRED_MANIFEST_ENTRY_FIELDS = (
    "content_hash",
    "representative_source_id",
    "approved",
    "import_ready",
    "real_import_allowed",
    "secret_review_status",
)

class InputError(Exception):
    """A required input is missing or structurally invalid."""

    def __init__(self, code: str, path: str, detail: str) -> None:
        super().__init__(f"{code}: {path}: {detail}")
        self.code = code
        self.path = path
        self.detail = detail


class SecurityBoundaryError(Exception):
    """An authority or approval invariant was violated."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ScanRejected(Exception):
    """A real-file scan was refused by the path or streaming safety gate."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
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
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), type(exc).__name__
        ) from None
    if not isinstance(payload, dict):
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), "top-level JSON is not an object"
        )
    return payload


def load_text_reference(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        raise InputError(BLOCKED_MISSING_INPUT, str(target), "file does not exist")
    if not target.is_file():
        raise InputError(BLOCKED_INVALID_INPUT, str(target), "not a regular file")
    try:
        return {
            "path": str(target),
            "exists": True,
            "size_bytes": target.stat().st_size,
        }
    except OSError as exc:
        raise InputError(
            BLOCKED_INVALID_INPUT, str(target), type(exc).__name__
        ) from None


def load_optional_input(path: str | Path) -> dict | None:
    target = Path(path)
    if not target.exists():
        return None
    return load_input(target)


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
    content = fixtures["content_review"]
    provenance = fixtures["provenance_review"]
    manifest = fixtures["import_manifest"]
    hash_results = fixtures["hash_results"]

    _require(
        isinstance(content.get("records"), list),
        "content_review",
        "records is not a list",
    )
    _require_fields(content["records"], REQUIRED_CONTENT_RECORD_FIELDS, "content_review")

    _require(
        isinstance(provenance.get("entries"), list),
        "provenance_review",
        "entries is not a list",
    )
    _require_fields(
        provenance["entries"], REQUIRED_PROVENANCE_ENTRY_FIELDS, "provenance_review"
    )

    _require(
        isinstance(manifest.get("entries"), list),
        "import_manifest",
        "entries is not a list",
    )
    _require_fields(
        manifest["entries"], REQUIRED_MANIFEST_ENTRY_FIELDS, "import_manifest"
    )

    _require(
        isinstance(hash_results.get("entries"), list),
        "hash_results",
        "entries is not a list",
    )
    _require_fields(hash_results["entries"], REQUIRED_HASH_ENTRY_FIELDS, "hash_results")


def _mismatch(key: str, expected: object, actual: object, detail: str = "") -> dict:
    return {
        "key": key,
        "expected": expected,
        "actual": actual,
        "match": expected == actual,
        "detail": detail,
    }


def _derived_counts(fixtures: dict) -> dict:
    records = fixtures["content_review"]["records"]
    hash_entries = fixtures["hash_results"]["entries"]
    hashes = [str(record["content_hash"]) for record in records]
    member_ids = [
        str(member)
        for record in records
        for member in record["member_source_ids"]
    ]
    member_counts = [int(record["member_count"]) for record in records]
    return {
        "CONTENT_UNIQUE_COUNT": len(records),
        "SOURCE_REFERENCE_COUNT": sum(member_counts),
        "DISTINCT_CONTENT_HASHES": len(set(hashes)),
        "SOURCE_ENTRY_COUNT": len(hash_entries),
        "TOTAL_SOURCE_ENTRIES": len(hash_entries),
        "SINGLETON_CONTENT_COUNT": sum(1 for value in member_counts if value == 1),
        "CONFIRMED_DUPLICATE_GROUPS": sum(1 for value in member_counts if value > 1),
        "ADDITIONAL_COPY_COUNT": sum(max(0, value - 1) for value in member_counts),
        "PROVENANCE_REVIEW_COUNT": len(fixtures["provenance_review"]["entries"]),
        "IMPORT_MANIFEST_COUNT": len(fixtures["import_manifest"]["entries"]),
        "MEMBER_SOURCE_REFERENCE_COUNT": len(member_ids),
        "UNIQUE_MEMBER_SOURCE_IDS": len(set(member_ids)),
        "_member_ids": member_ids,
        "_hashes": hashes,
    }


def validate_inputs(fixtures: dict, *, expected: dict | None = None) -> dict:
    validate_shapes(fixtures)
    expected = expected or {}
    records = fixtures["content_review"]["records"]
    hash_entries = fixtures["hash_results"]["entries"]
    hash_by_id = {str(entry["source_id"]): entry for entry in hash_entries}
    derived = _derived_counts(fixtures)

    comparisons: list[dict] = []

    def _cmp(key: str, actual: object, detail: str = "") -> None:
        if key in expected:
            comparisons.append(_mismatch(key, expected[key], actual, detail))

    for key in (
        "CONTENT_UNIQUE_COUNT",
        "SOURCE_REFERENCE_COUNT",
        "DISTINCT_CONTENT_HASHES",
        "SOURCE_ENTRY_COUNT",
        "SINGLETON_CONTENT_COUNT",
        "CONFIRMED_DUPLICATE_GROUPS",
        "ADDITIONAL_COPY_COUNT",
        "PROVENANCE_REVIEW_COUNT",
        "IMPORT_MANIFEST_COUNT",
        "MEMBER_SOURCE_REFERENCE_COUNT",
        "UNIQUE_MEMBER_SOURCE_IDS",
    ):
        _cmp(key, derived[key])

    declared = fixtures["content_review"].get("counts", {})
    if isinstance(declared, dict):
        for key in (
            "CONTENT_UNIQUE_COUNT",
            "SOURCE_REFERENCE_COUNT",
            "DISTINCT_CONTENT_HASHES",
            "TOTAL_SOURCE_ENTRIES",
        ):
            if key in declared:
                comparisons.append(
                    _mismatch(f"DECLARED_{key}", declared[key], derived[key])
                )

    all_secret_not_performed = all(
        record.get("secret_review_status") == SECRET_REVIEW_NOT_PERFORMED
        for record in records
    )
    all_provenance_unknown = all(
        record.get("provenance_status") == PROVENANCE_UNKNOWN for record in records
    )
    all_approved_false = all(
        record.get("approved") is False for record in records
    ) and all(entry.get("approved") is False for entry in fixtures["import_manifest"]["entries"])
    all_import_ready_false = all(
        record.get("import_ready") is False for record in records
    ) and all(
        entry.get("import_ready") is False
        for entry in fixtures["import_manifest"]["entries"]
    )
    all_real_import_allowed_false = all(
        record.get("real_import_allowed") is False for record in records
    ) and all(
        entry.get("real_import_allowed") is False
        for entry in fixtures["import_manifest"]["entries"]
    )
    all_members_resolve = all(member in hash_by_id for member in derived["_member_ids"])
    representative_in_members = all(
        record.get("representative_source_id") in record.get("member_source_ids", [])
        for record in records
    )
    hashes_unique = len(derived["_hashes"]) == len(set(derived["_hashes"]))
    members_unique = len(derived["_member_ids"]) == len(set(derived["_member_ids"]))

    for key, actual in (
        ("ALL_SECRET_REVIEW_NOT_PERFORMED", all_secret_not_performed),
        ("ALL_PROVENANCE_UNKNOWN", all_provenance_unknown),
        ("ALL_APPROVED_FALSE", all_approved_false),
        ("ALL_IMPORT_READY_FALSE", all_import_ready_false),
        ("ALL_REAL_IMPORT_ALLOWED_FALSE", all_real_import_allowed_false),
        ("ALL_MEMBER_SOURCE_IDS_RESOLVE", all_members_resolve),
        ("REPRESENTATIVE_IN_MEMBERS", representative_in_members),
        ("CONTENT_HASHES_UNIQUE", hashes_unique),
        ("MEMBER_SOURCE_IDS_UNIQUE", members_unique),
    ):
        _cmp(key, actual)

    mismatches = [item for item in comparisons if not item["match"]]
    return {
        "status": INPUTS_VALID if not mismatches else INPUT_COUNT_MISMATCH,
        "inputs_valid": not mismatches,
        "all_secret_review_not_performed": all_secret_not_performed,
        "all_provenance_unknown": all_provenance_unknown,
        "all_approved_false": all_approved_false,
        "all_import_ready_false": all_import_ready_false,
        "all_real_import_allowed_false": all_real_import_allowed_false,
        "comparisons": comparisons,
        "mismatches": mismatches,
    }


# ---------------------------------------------------------------------------
# A. Secret scan plan
# ---------------------------------------------------------------------------


def _priority_counts(candidates: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        priority = str(candidate["scan_priority"])
        counts[priority] = counts.get(priority, 0) + 1
    return dict(sorted(counts.items()))


def _representative_metadata(
    record: dict, hash_by_id: dict[str, dict]
) -> dict:
    representative = str(record["representative_source_id"])
    metadata = hash_by_id.get(representative, {})
    source_paths = list(record.get("source_paths") or [])
    source_roots = list(record.get("source_roots") or [])
    absolute_path = metadata.get("absolute_path") or (
        source_paths[0] if source_paths else None
    )
    source_root = metadata.get("source_root") or (
        source_roots[0] if source_roots else None
    )
    return {
        "absolute_path": absolute_path,
        "source_root": source_root,
        "size_bytes": metadata.get("size_bytes"),
        "mtime": metadata.get("mtime"),
        "metadata_available": bool(metadata),
        "metadata_hash_matches": (
            metadata.get("sha256") == record.get("content_hash")
            if metadata
            else False
        ),
    }


def build_scan_plan(
    fixtures: dict,
    *,
    generated_at: str,
    approved_roots: tuple[str | Path, ...] = (),
) -> dict:
    records = sorted(
        fixtures["content_review"]["records"],
        key=lambda record: str(record["content_hash"]),
    )
    hash_entries = fixtures["hash_results"]["entries"]
    hash_by_id = {str(entry["source_id"]): entry for entry in hash_entries}

    candidates: list[dict] = []
    representative_by_hash: dict[str, str] = {}
    for record in records:
        content_hash = str(record["content_hash"])
        representative = str(record["representative_source_id"])
        representative_by_hash[content_hash] = representative
        metadata = _representative_metadata(record, hash_by_id)
        candidates.append(
            {
                "content_hash": content_hash,
                "representative_source_id": representative,
                "absolute_path": metadata["absolute_path"],
                "source_root": metadata["source_root"],
                "size_bytes": metadata["size_bytes"],
                "mtime": metadata["mtime"],
                "source_metadata_available": metadata["metadata_available"],
                "source_metadata_hash_matches": metadata["metadata_hash_matches"],
                "scan_priority": str(record.get("review_priority", "P3")),
                "scan_status": SCAN_NOT_STARTED,
                "approval_required": True,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "secret_review_status": SECRET_REVIEW_NOT_PERFORMED,
                "secret_finding_count": None,
                "secret_review_required": SECRET_REVIEW_REQUIRED,
                "secret_scan_approved": SECRET_SCAN_APPROVED,
                "member_count": int(record["member_count"]),
                "member_source_ids": list(record["member_source_ids"]),
                "source_reference_count": len(record["member_source_ids"]),
                "provenance_status": PROVENANCE_UNKNOWN,
                "source_truth_class": SOURCE_TRUTH_CLASS,
                "authority_scope": AUTHORITY_SCOPE,
                "historical_record": True,
                "historical_runtime_authority": False,
            }
        )

    references: list[dict] = []
    for entry in hash_entries:
        source_id = str(entry["source_id"])
        content_hash = str(entry["sha256"])
        references.append(
            {
                "source_id": source_id,
                "content_hash": content_hash,
                "absolute_path": entry.get("absolute_path"),
                "source_root": entry.get("source_root"),
                "size_bytes": entry.get("size_bytes"),
                "mtime": entry.get("mtime"),
                "inspection_target": representative_by_hash.get(content_hash)
                == source_id,
                "in_content_unique_set": content_hash in representative_by_hash,
            }
        )
    references.sort(key=lambda item: (item["content_hash"], item["source_id"]))

    inspection_targets = [item for item in references if item["inspection_target"]]
    counts = {
        "CONTENT_UNIQUE_COUNT": len(candidates),
        "SOURCE_REFERENCE_COUNT": len(references),
        "SCAN_TARGET_COUNT": len(candidates),
        "SOURCE_REFERENCE_INSPECTION_TARGET_COUNT": len(inspection_targets),
        "ADDITIONAL_COPY_COUNT": len(references) - len(inspection_targets),
        "SECRET_REVIEW_NOT_PERFORMED_COUNT": len(candidates),
        "SECRET_REVIEW_REQUIRED_COUNT": sum(
            1 for candidate in candidates if candidate["secret_review_required"]
        ),
        "SECRET_SCAN_APPROVED_COUNT": sum(
            1 for candidate in candidates if candidate["secret_scan_approved"]
        ),
        "SCAN_NOT_STARTED_COUNT": sum(
            1 for candidate in candidates if candidate["scan_status"] == SCAN_NOT_STARTED
        ),
        "ALL_APPROVED_FALSE": all(
            candidate["approved"] is False for candidate in candidates
        ),
        "ALL_IMPORT_READY_FALSE": all(
            candidate["import_ready"] is False for candidate in candidates
        ),
        "ALL_REAL_IMPORT_ALLOWED_FALSE": all(
            candidate["real_import_allowed"] is False for candidate in candidates
        ),
        "ALL_SECRET_REVIEW_NOT_PERFORMED": all(
            candidate["secret_review_status"] == SECRET_REVIEW_NOT_PERFORMED
            for candidate in candidates
        ),
        "PRIORITY_COUNTS": _priority_counts(candidates),
    }
    return {
        "task_id": TASK_ID,
        "schema_version": SCAN_PLAN_SCHEMA_VERSION,
        "mode": MODE_STAGE_A,
        "generated_at": generated_at,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "content_read": False,
        "source_body_stored": False,
        "real_source_scan_executed": False,
        "real_import_executed": False,
        "scan_status": SCAN_NOT_STARTED,
        "approval_required": True,
        "approved_roots": sorted(
            {
                str(Path(root))
                for root in (*ADDITIONAL_APPROVED_ROOTS, *approved_roots)
            }
        ),
        "path_safety_controls": [
            "ABSOLUTE_PATH_REQUIRED",
            "PATH_TRAVERSAL_REJECTED",
            "SYMLINK_REJECTED",
            "SECRET_FILENAME_REJECTED",
            "APPROVED_ROOT_REQUIRED",
            "CANONICAL_ROOT_EXCLUDED",
            "REGULAR_FILE_REQUIRED",
            "SOURCE_METADATA_MATCH_REQUIRED",
            "O_NOFOLLOW_OPEN",
            "POST_OPEN_FSTAT_REQUIRED",
            "POST_READ_FSTAT_REQUIRED",
            "SIZE_LIMIT_ENFORCED",
            "STREAMING_READ_ONLY",
            "CHANGE_DURING_READ_REJECTED",
        ],
        "counts": counts,
        "candidates": candidates,
        "source_references": references,
    }


# ---------------------------------------------------------------------------
# B. Synthetic secret scanner
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(
    r"(?ix)^(?:"
    r"<[^>]*>|"
    r"\$\{[^}]*\}|"
    r"\{\{[^}]*\}\}|"
    r"%\([^)]*\)s|"
    r"your[_-]?[a-z0-9_-]*|"
    r"example[_-]?[a-z0-9_-]*|"
    r"sample[_-]?[a-z0-9_-]*|"
    r"placeholder[a-z0-9_-]*|"
    r"changeme|change[_-]?me|"
    r"redacted|dummy|fake[_-]?[a-z0-9_-]*|"
    r"xxx+|"
    r"\*+|"
    r"\.{3,}|"
    r"todo|tbd|none|null|undefined|"
    r"os\.environ.*|getenv.*|"
    r"[a-z_]+_here"
    r")$"
)

_EXCHANGE_RE = re.compile(
    r"(?i)\b(?:binance|bybit|okx|kucoin|coinbase|kraken|bitget|gate\.io|htx|huobi|mexc)"
)

_KEY_VALUE_RE = re.compile(
    r"""(?ix)
    (?P<key>
        api[_-]?key|apikey|
        api[_-]?secret(?:[_-]?key)?|
        secret[_-]?key|
        access[_-]?token|
        refresh[_-]?token|
        auth[_-]?token|
        bearer[_-]?token|
        client[_-]?secret|
        private[_-]?key|
        webhook[_-]?secret|
        database[_-]?url|
        db[_-]?password|
        db[_-]?pass|
        aws[_-]?secret[_-]?access[_-]?key|
        account[_-]?key|
        password|passwd|pwd|
        secret|token
    )
    \s*[:=]\s*
    (?P<quote>["']?)
    (?P<value>[^\s"'`,;]+)
    """
)

_CONTEXT_RE = re.compile(
    r"(?i)\b(?:credentials?|api[\s_-]?key|secret[\s_-]?key|access[\s_-]?token|password)\b"
    r"[^\n]{0,40}\b(?:is|was|were|are|stored|provided|rotated|used|configured)\b"
)

_PATTERN_RULES: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----"
        ),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "AUTHORIZATION_HEADER",
        re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?:bearer|basic|token)\s+\S+"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "BEARER_TOKEN",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
        CONFIDENCE_MEDIUM,
        METHOD_PATTERN,
    ),
    (
        "SESSION_COOKIE",
        re.compile(r"(?i)\b(?:set-)?cookie\b\s*[:=]\s*[^\n]+"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "SESSION_COOKIE",
        re.compile(r"(?i)\bsession(?:id|_id)?\s*[:=]\s*[A-Za-z0-9._-]{8,}"),
        CONFIDENCE_MEDIUM,
        METHOD_PATTERN,
    ),
    (
        "CLOUD_CREDENTIAL",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "CLOUD_CREDENTIAL",
        re.compile(r"(?i)\bAccountKey\s*=\s*[A-Za-z0-9+/=]{20,}"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "ACCESS_TOKEN",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "ACCESS_TOKEN",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "API_KEY",
        re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "API_KEY",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "API_KEY",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "ACCESS_TOKEN",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
        CONFIDENCE_MEDIUM,
        METHOD_PATTERN,
    ),
    (
        "DATABASE_CREDENTIAL",
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|mssql)"
            r"://[^\s:/@]+:[^\s/@]+@"
        ),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
    (
        "WEBHOOK_SECRET",
        re.compile(
            r"https://(?:hooks\.slack\.com/services|discord(?:app)?\.com/api/webhooks"
            r"|outlook\.office\.com/webhook)/\S+"
        ),
        CONFIDENCE_HIGH,
        METHOD_PATTERN,
    ),
)

_MIN_SECRET_LENGTH = {
    "password": 6,
    "passwd": 6,
    "pwd": 6,
    "token": 10,
    "secret": 10,
}

_KEY_TYPE_OVERRIDES = {
    "private_key": "PRIVATE_KEY",
    "api_secret": "API_SECRET",
    "api_secret_key": "API_SECRET",
    "secret_key": "API_SECRET",
    "client_secret": "API_SECRET",
    "secret": "API_SECRET",
    "access_token": "ACCESS_TOKEN",
    "auth_token": "ACCESS_TOKEN",
    "bearer_token": "BEARER_TOKEN",
    "token": "ACCESS_TOKEN",
    "refresh_token": "REFRESH_TOKEN",
    "password": "PASSWORD",
    "passwd": "PASSWORD",
    "pwd": "PASSWORD",
    "webhook_secret": "WEBHOOK_SECRET",
    "database_url": "DATABASE_CREDENTIAL",
    "db_password": "DATABASE_CREDENTIAL",
    "db_pass": "DATABASE_CREDENTIAL",
    "aws_secret_access_key": "CLOUD_CREDENTIAL",
    "account_key": "CLOUD_CREDENTIAL",
    "api_key": "API_KEY",
    "apikey": "API_KEY",
}


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _is_placeholder(value: str) -> bool:
    stripped = value.strip().strip("\"'")
    if not stripped:
        return True
    if _PLACEHOLDER_RE.match(stripped):
        return True
    lowered = stripped.lower()
    if lowered in {"none", "null", "true", "false", "undefined"}:
        return True
    if lowered.startswith(("os.environ", "getenv", "process.env", "${")):
        return True
    return False


def _classify_key(key: str) -> str | None:
    normalized = key.lower().strip().replace("-", "_")
    if normalized in _KEY_TYPE_OVERRIDES:
        return _KEY_TYPE_OVERRIDES[normalized]
    if "refresh" in normalized and "token" in normalized:
        return "REFRESH_TOKEN"
    if "api" in normalized and "secret" in normalized:
        return "API_SECRET"
    if "api" in normalized and "key" in normalized:
        return "API_KEY"
    if "token" in normalized:
        return "ACCESS_TOKEN"
    if "password" in normalized or "passwd" in normalized or "pwd" in normalized:
        return "PASSWORD"
    return None


def severity_for(secret_type: str) -> str:
    return SEVERITY_BY_TYPE.get(secret_type, SEVERITY_UNKNOWN)


def action_for(secret_type: str, severity: str | None = None) -> str:
    resolved = severity or severity_for(secret_type)
    return ACTION_BY_SEVERITY.get(resolved, ACTION_REVIEW)


def _severity_rank(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return len(SEVERITY_ORDER)


def _internal_finding(
    *,
    secret_type: str,
    confidence: str,
    detection_method: str,
    line_number: int,
    start: int,
    end: int,
    severity: str | None = None,
) -> dict:
    return {
        "secret_type": secret_type,
        "severity": severity or severity_for(secret_type),
        "confidence": confidence,
        "detection_method": detection_method,
        "line_number": line_number,
        "start": start,
        "end": end,
    }


def _overlaps(left: dict, right: dict) -> bool:
    return left["start"] < right["end"] and right["start"] < left["end"]


def _dedupe_findings(findings: list[dict]) -> list[dict]:
    ranked = sorted(
        findings,
        key=lambda finding: (
            finding["start"],
            -(finding["end"] - finding["start"]),
            _severity_rank(finding["severity"]),
        ),
    )
    selected: list[dict] = []
    for finding in ranked:
        if any(_overlaps(finding, kept) for kept in selected):
            continue
        selected.append(finding)
    return selected


def _scan_line(line: str, line_number: int, base_offset: int) -> list[dict]:
    findings: list[dict] = []

    for secret_type, pattern, confidence, method in _PATTERN_RULES:
        for match in pattern.finditer(line):
            findings.append(
                _internal_finding(
                    secret_type=secret_type,
                    confidence=confidence,
                    detection_method=method,
                    line_number=line_number,
                    start=base_offset + match.start(),
                    end=base_offset + match.end(),
                )
            )

    exchange_context = _EXCHANGE_RE.search(line) is not None
    for match in _KEY_VALUE_RE.finditer(line):
        key = match.group("key")
        value = match.group("value")
        secret_type = _classify_key(key)
        if secret_type is None:
            continue
        if _is_placeholder(value):
            continue
        lowered_key = key.lower().replace("-", "_")
        minimum = _MIN_SECRET_LENGTH.get(lowered_key)
        if minimum is not None and len(value) < minimum:
            continue
        if len(value) < 4:
            continue
        entropy = shannon_entropy(value)
        confidence = CONFIDENCE_HIGH if entropy >= 3.5 else CONFIDENCE_MEDIUM
        method = METHOD_KEY_VALUE
        if entropy >= 4.5:
            method = METHOD_ENTROPY
        if exchange_context and secret_type in {
            "API_KEY",
            "API_SECRET",
            "ACCESS_TOKEN",
        }:
            secret_type = "EXCHANGE_API_CREDENTIAL"
            confidence = CONFIDENCE_HIGH
        findings.append(
            _internal_finding(
                secret_type=secret_type,
                confidence=confidence,
                detection_method=method,
                line_number=line_number,
                start=base_offset + match.start("value"),
                end=base_offset + match.end("value"),
            )
        )

    if not findings and _CONTEXT_RE.search(line):
        match = _CONTEXT_RE.search(line)
        findings.append(
            _internal_finding(
                secret_type="CREDENTIAL_LIKE_TEXT",
                confidence=CONFIDENCE_LOW,
                detection_method=METHOD_CONTEXT,
                line_number=line_number,
                start=base_offset + match.start(),
                end=base_offset + match.end(),
            )
        )

    return _dedupe_findings(findings)


def scan_text(text: str) -> list[dict]:
    """Scan synthetic text and return internal findings with offsets.

    The returned dictionaries carry only classification metadata and character
    offsets. They never carry the matched value itself. Callers must serialize
    through :func:`serialize_findings` before persisting or logging.
    """

    findings: list[dict] = []
    offset = 0
    for line_number, raw_line in enumerate(text.splitlines(keepends=True), start=1):
        line = raw_line.rstrip("\r\n")
        findings.extend(_scan_line(line, line_number, offset))
        offset += len(raw_line)
    return findings


def _finding_id(content_hash: str | None, secret_type: str, line_number: int, index: int) -> str:
    seed = f"{content_hash or 'NO_CONTENT_HASH'}|{secret_type}|{line_number}|{index}"
    return "secfind_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def serialize_findings(
    findings: list[dict], *, content_hash: str | None = None
) -> list[dict]:
    """Convert internal findings into value-free, safe review records."""

    counters: dict[str, int] = {}
    serialized: list[dict] = []
    for finding in findings:
        secret_type = str(finding["secret_type"])
        counters[secret_type] = counters.get(secret_type, 0) + 1
        severity = str(finding["severity"])
        serialized.append(
            {
                "finding_id": _finding_id(
                    content_hash, secret_type, int(finding["line_number"]),
                    counters[secret_type],
                ),
                "content_hash": content_hash,
                "secret_type": secret_type,
                "severity": severity,
                "confidence": str(finding["confidence"]),
                "line_number": int(finding["line_number"]),
                "detection_method": str(finding["detection_method"]),
                "review_status": REVIEW_NOT_REVIEWED,
                "default_action": action_for(secret_type, severity),
                "value_stored": False,
            }
        )
    return serialized


def scan_to_safe_findings(text: str, *, content_hash: str | None = None) -> list[dict]:
    return serialize_findings(scan_text(text), content_hash=content_hash)


def summarize_findings(findings: list[dict]) -> dict:
    """Return aggregate counts only. No value, fragment, or context text."""

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    highest = SEVERITY_UNKNOWN
    for finding in findings:
        secret_type = str(finding.get("secret_type"))
        severity = str(finding.get("severity"))
        confidence = str(finding.get("confidence"))
        by_type[secret_type] = by_type.get(secret_type, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1
        if _severity_rank(severity) < _severity_rank(highest):
            highest = severity
    return {
        "finding_count": len(findings),
        "by_secret_type": dict(sorted(by_type.items())),
        "by_severity": dict(sorted(by_severity.items())),
        "by_confidence": dict(sorted(by_confidence.items())),
        "highest_severity": highest if findings else None,
        "values_stored": False,
        "context_stored": False,
    }


def redact_text(
    text: str, findings: list[dict], *, placeholder: str = "[REDACTED:{secret_type}]"
) -> str:
    """Replace only the matched secret spans in synthetic text.

    Surrounding prose, line order, and unrelated content are preserved. This is
    exercised only against synthetic fixtures; it is never applied to a real
    report.
    """

    spans = [
        (int(finding["start"]), int(finding["end"]), str(finding["secret_type"]))
        for finding in findings
        if "start" in finding and "end" in finding
    ]
    spans.sort(key=lambda item: item[0], reverse=True)
    result = text
    last_start = len(text) + 1
    for start, end, secret_type in spans:
        if end > last_start:
            continue
        result = result[:start] + placeholder.format(secret_type=secret_type) + result[end:]
        last_start = start
    return result


# ---------------------------------------------------------------------------
# C. Real-file path and streaming safety gate (implemented, never executed)
# ---------------------------------------------------------------------------

SCAN_PATH_APPROVED = "SCAN_PATH_APPROVED"
SCAN_PATH_REJECTED = "SCAN_PATH_REJECTED"
SCAN_SOURCE_CHANGED = "SCAN_SOURCE_CHANGED"

REJECT_ABSOLUTE_PATH_REQUIRED = "ABSOLUTE_PATH_REQUIRED"
REJECT_PATH_TRAVERSAL = "PATH_TRAVERSAL"
REJECT_SECRET_FILENAME = "SECRET_FILENAME"
REJECT_SOURCE_ROOT_NOT_ABSOLUTE = "SOURCE_ROOT_NOT_ABSOLUTE"
REJECT_SOURCE_ROOT_NOT_APPROVED = "SOURCE_ROOT_NOT_APPROVED"
REJECT_SYMLINK = "SYMLINK_REJECTED"
REJECT_NOT_REGULAR_FILE = "NOT_REGULAR_FILE"
REJECT_PATH_ESCAPE = "PATH_ESCAPE"
REJECT_CANONICAL_EXCLUDED = "CANONICAL_EXCLUDED"
REJECT_PATH_RESOLUTION_FAILED = "PATH_RESOLUTION_FAILED"
REJECT_FILE_NOT_FOUND = "FILE_NOT_FOUND"
REJECT_STAT_FAILED = "STAT_FAILED"
REJECT_SIZE_LIMIT_EXCEEDED = "SIZE_LIMIT_EXCEEDED"
REJECT_METADATA_CHANGED = "SOURCE_METADATA_CHANGED"
REJECT_DEVICE_OR_INODE_CHANGED = "DEVICE_OR_INODE_CHANGED"
REJECT_CHANGED_DURING_READ = "CHANGED_DURING_READ"
REJECT_OPEN_FAILED = "OPEN_FAILED"


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _is_under(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def is_approved_root(
    root: str | Path, *, approved_roots: tuple[str | Path, ...] = ()
) -> bool:
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
    for extra in approved_roots:
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


def _rejected(reason: str, **extra: object) -> dict:
    payload = {
        "status": SCAN_PATH_REJECTED,
        "rejection_reason": reason,
        "observed_size_bytes": None,
        "observed_mtime": None,
        "device": None,
        "inode": None,
    }
    payload.update(extra)
    return payload


def validate_scan_path(
    absolute_path: str | Path,
    source_root: str | Path,
    *,
    approved_roots: tuple[str | Path, ...] = (),
    max_bytes: int = MAX_SCAN_BYTES,
    expected_size: int | None = None,
    expected_mtime: str | None = None,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> dict:
    """Metadata-only gate for a future approved real source scan."""

    path = Path(absolute_path)
    if not path.is_absolute():
        return _rejected(REJECT_ABSOLUTE_PATH_REQUIRED)
    if any(part in {".", ".."} for part in path.parts):
        return _rejected(REJECT_PATH_TRAVERSAL)
    if secret_filename(path.name):
        return _rejected(REJECT_SECRET_FILENAME)

    root = Path(source_root)
    if not root.is_absolute():
        return _rejected(REJECT_SOURCE_ROOT_NOT_ABSOLUTE)
    if not is_approved_root(root, approved_roots=approved_roots):
        return _rejected(REJECT_SOURCE_ROOT_NOT_APPROVED)

    resolved_path = _resolved(path)
    resolved_root = _resolved(root)
    if resolved_path is None or resolved_root is None:
        return _rejected(REJECT_PATH_RESOLUTION_FAILED)
    if not _is_under(resolved_path, resolved_root):
        return _rejected(REJECT_PATH_ESCAPE)
    canonical = _resolved(CANONICAL_ROOT)
    if canonical is not None and _is_under(resolved_path, canonical):
        return _rejected(REJECT_CANONICAL_EXCLUDED)

    try:
        stat_result = os.lstat(path)
    except FileNotFoundError:
        return _rejected(REJECT_FILE_NOT_FOUND)
    except OSError:
        return _rejected(REJECT_STAT_FAILED)

    if stat_module.S_ISLNK(stat_result.st_mode):
        return _rejected(REJECT_SYMLINK)
    if not stat_module.S_ISREG(stat_result.st_mode):
        return _rejected(REJECT_NOT_REGULAR_FILE)
    if stat_result.st_size > max_bytes:
        return _rejected(REJECT_SIZE_LIMIT_EXCEEDED)
    if expected_size is not None and stat_result.st_size != expected_size:
        return _rejected(
            REJECT_METADATA_CHANGED,
            observed_size_bytes=stat_result.st_size,
            observed_mtime=_iso_from_epoch(stat_result.st_mtime),
        )
    if expected_mtime is not None and not _mtime_matches(
        expected_mtime, stat_result.st_mtime
    ):
        return _rejected(
            REJECT_METADATA_CHANGED,
            observed_size_bytes=stat_result.st_size,
            observed_mtime=_iso_from_epoch(stat_result.st_mtime),
        )
    if expected_device is not None and (
        stat_result.st_dev != expected_device or stat_result.st_ino != expected_inode
    ):
        return _rejected(REJECT_DEVICE_OR_INODE_CHANGED)

    return {
        "status": SCAN_PATH_APPROVED,
        "rejection_reason": None,
        "observed_size_bytes": stat_result.st_size,
        "observed_mtime": _iso_from_epoch(stat_result.st_mtime),
        "device": stat_result.st_dev,
        "inode": stat_result.st_ino,
    }


def iter_verified_chunks(
    absolute_path: str | Path,
    source_root: str | Path,
    *,
    approved_roots: tuple[str | Path, ...] = (),
    max_bytes: int = MAX_SCAN_BYTES,
    expected_size: int | None = None,
    expected_mtime: str | None = None,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    chunk_size: int = SCAN_CHUNK_SIZE,
):
    """Yield verified chunks without ever retaining or logging the body.

    ``O_NOFOLLOW`` plus a post-open ``fstat`` blocks symlink swaps. A post-read
    ``fstat`` detects a file that changed while it was being read.
    """

    validation = validate_scan_path(
        absolute_path,
        source_root,
        approved_roots=approved_roots,
        max_bytes=max_bytes,
        expected_size=expected_size,
        expected_mtime=expected_mtime,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )
    if validation["status"] != SCAN_PATH_APPROVED:
        raise ScanRejected(str(validation["rejection_reason"]))

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(absolute_path), flags)
    except OSError as exc:
        raise ScanRejected(REJECT_OPEN_FAILED, type(exc).__name__) from None

    try:
        before = os.fstat(descriptor)
        if not stat_module.S_ISREG(before.st_mode):
            raise ScanRejected(REJECT_NOT_REGULAR_FILE)
        if before.st_size > max_bytes:
            raise ScanRejected(REJECT_SIZE_LIMIT_EXCEEDED)
        if expected_device is not None and (
            before.st_dev != expected_device or before.st_ino != expected_inode
        ):
            raise ScanRejected(REJECT_DEVICE_OR_INODE_CHANGED)
        if expected_size is not None and before.st_size != expected_size:
            raise ScanRejected(REJECT_METADATA_CHANGED)
        if expected_mtime is not None and not _mtime_matches(
            expected_mtime, before.st_mtime
        ):
            raise ScanRejected(REJECT_METADATA_CHANGED)

        total = 0
        while True:
            chunk = os.read(descriptor, chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ScanRejected(REJECT_SIZE_LIMIT_EXCEEDED)
            yield chunk

        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or not _mtime_matches(
                _iso_from_epoch(before.st_mtime), after.st_mtime
            )
        ):
            raise ScanRejected(REJECT_CHANGED_DURING_READ)
        if total != before.st_size:
            raise ScanRejected(REJECT_CHANGED_DURING_READ)
    finally:
        os.close(descriptor)


# ---------------------------------------------------------------------------
# D. Policies, provenance plan, approval gate
# ---------------------------------------------------------------------------


def build_detection_policy(*, generated_at: str) -> dict:
    return {
        "task_id": TASK_ID,
        "schema_version": DETECTION_POLICY_SCHEMA_VERSION,
        "mode": MODE_STAGE_A,
        "generated_at": generated_at,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "real_source_scan_executed": False,
        "secret_types": list(SECRET_TYPES),
        "severity_by_type": dict(SEVERITY_BY_TYPE),
        "detection_methods": list(DETECTION_METHODS),
        "confidence_levels": list(CONFIDENCE_ORDER),
        "entropy_policy": {
            "used_as_sole_evidence": False,
            "requires_key_value_context": True,
            "high_confidence_threshold_bits": 3.5,
            "entropy_method_threshold_bits": 4.5,
            "note": "Entropy alone never confirms a secret; it only adjusts confidence.",
        },
        "placeholder_handling": {
            "placeholder_values_are_not_findings": True,
            "examples": [
                "<your-api-key>",
                "${API_KEY}",
                "changeme",
                "redacted",
                "os.environ['TOKEN']",
            ],
        },
        "false_positive_policy": {
            "detection_is_not_confirmation": True,
            "operators_must_review_every_finding": True,
            "undetectable_secrets_may_exist": True,
        },
        "serialization_protections": {
            "secret_value_stored": False,
            "secret_fragment_stored": False,
            "surrounding_text_stored": False,
            "secret_value_hash_stored": False,
            "safe_fields": [
                "finding_id",
                "content_hash",
                "secret_type",
                "severity",
                "confidence",
                "line_number",
                "detection_method",
                "review_status",
                "default_action",
            ],
        },
        "logging_policy": {
            "logs_finding_counts_only": True,
            "logs_classification_only": True,
            "logs_processing_state_only": True,
        },
        "limitations": [
            "Pattern detection cannot prove a secret is live.",
            "Entropy heuristics have false positives and false negatives.",
            "Some secrets are unstructured and may not be detected.",
            "No real source body has been read in Stage A.",
        ],
        "approved_roots": sorted(str(Path(root)) for root in ADDITIONAL_APPROVED_ROOTS),
    }


def build_provenance_review_plan(
    fixtures: dict, *, generated_at: str
) -> dict:
    queue_by_hash = {
        str(entry["content_hash"]): entry
        for entry in fixtures["provenance_review"]["entries"]
    }
    records = sorted(
        fixtures["content_review"]["records"],
        key=lambda record: str(record["content_hash"]),
    )
    entries: list[dict] = []
    for record in records:
        content_hash = str(record["content_hash"])
        source = queue_by_hash.get(content_hash, record)
        entries.append(
            {
                "content_hash": content_hash,
                "representative_source_id": str(source["representative_source_id"]),
                "member_source_ids": list(source["member_source_ids"]),
                "member_count": int(record["member_count"]),
                "classifications": sorted(source.get("classifications") or []),
                "classification_counts": dict(
                    source.get("classification_counts") or {}
                ),
                "source_classifications": dict(
                    source.get("source_classifications") or {}
                ),
                "member_provenance": list(record.get("member_provenance") or []),
                "provenance_status": PROVENANCE_UNKNOWN,
                "confirmed_cursor": False,
                "confirmed_other_agent": False,
                "confirmed_chatgpt": False,
                "review_priority": str(
                    source.get("review_priority", record.get("review_priority", "P3"))
                ),
                "review_status": REVIEW_NOT_STARTED,
                "review_required": True,
                "source_truth_class": SOURCE_TRUTH_CLASS,
                "authority_scope": AUTHORITY_SCOPE,
                "historical_record": True,
                "historical_runtime_authority": False,
                "evidence_policy": {
                    "filename_alone_is_sufficient": False,
                    "hash_match_alone_is_sufficient": False,
                    "body_read_in_stage_a": False,
                    "requires_explicit_operator_evidence": True,
                },
            }
        )

    counts = {
        "PROVENANCE_REVIEW_COUNT": len(entries),
        "PROVENANCE_UNKNOWN_COUNT": sum(
            1 for entry in entries if entry["provenance_status"] == PROVENANCE_UNKNOWN
        ),
        "CONFIRMED_CURSOR_COUNT": sum(
            1 for entry in entries if entry["confirmed_cursor"]
        ),
        "CONFIRMED_OTHER_AGENT_COUNT": sum(
            1 for entry in entries if entry["confirmed_other_agent"]
        ),
        "CONFIRMED_CHATGPT_COUNT": sum(
            1 for entry in entries if entry["confirmed_chatgpt"]
        ),
        "ALL_REVIEW_NOT_STARTED": all(
            entry["review_status"] == REVIEW_NOT_STARTED for entry in entries
        ),
        "ALL_CONFIRMATIONS_FALSE": all(
            not entry["confirmed_cursor"]
            and not entry["confirmed_other_agent"]
            and not entry["confirmed_chatgpt"]
            for entry in entries
        ),
    }
    return {
        "task_id": TASK_ID,
        "schema_version": PROVENANCE_PLAN_SCHEMA_VERSION,
        "mode": MODE_STAGE_A,
        "generated_at": generated_at,
        "content_read": False,
        "source_body_stored": False,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "policy": {
            "filename_is_not_proof": True,
            "hash_match_is_not_proof": True,
            "requires_clear_operator_evidence": True,
            "preserve_existing_classification": True,
            "provenance_remains_unknown_until_confirmed": True,
        },
        "counts": counts,
        "entries": entries,
    }


def build_redaction_policy(*, generated_at: str) -> dict:
    rules = []
    for secret_type in SECRET_TYPES:
        severity = severity_for(secret_type)
        rules.append(
            {
                "secret_type": secret_type,
                "severity": severity,
                "default_action": action_for(secret_type, severity),
                "requires_operator_review": severity
                in {SEVERITY_CRITICAL, SEVERITY_HIGH},
                "preserve_surrounding_text": True,
            }
        )
    return {
        "task_id": TASK_ID,
        "schema_version": REDACTION_POLICY_SCHEMA_VERSION,
        "mode": MODE_STAGE_A,
        "generated_at": generated_at,
        "applies_to": "SYNTHETIC_FIXTURE_ONLY",
        "real_file_modified": False,
        "import_body_generated": False,
        "real_import_executed": False,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "placeholder_format": "[REDACTED:<SECRET_TYPE>]",
        "actions": {
            ACTION_REDACT: "Replace only the secret token before a future import.",
            ACTION_REVIEW: "Hold the candidate for explicit operator review.",
            ACTION_EXCLUDE: "Exclude the candidate from import unless separately approved.",
        },
        "meaning_preservation": {
            "replace_secret_span_only": True,
            "preserve_line_structure": True,
            "preserve_surrounding_prose": True,
            "drop_unrelated_history": False,
        },
        "guarantees": [
            "No real report body is changed in Stage A.",
            "No redacted import body is generated in Stage A.",
            "Redaction is validated only against synthetic fixtures.",
            "A redacted record still requires explicit operator approval.",
        ],
        "rules": rules,
    }


def build_approval_gate(
    scan_plan: dict, *, approval_token: str | None = None
) -> dict:
    granted = approval_token == REAL_SCAN_APPROVAL_TOKEN
    return {
        "approval_required": True,
        "approval_token_required": REAL_SCAN_APPROVAL_TOKEN,
        "real_source_scan_approved": granted,
        "real_source_scan_approved_label": "YES" if granted else "NO",
        "real_source_scan_executed": False,
        "real_import_executed": False,
        "candidate_count": scan_plan["counts"]["SCAN_TARGET_COUNT"],
        "source_reference_count": scan_plan["counts"]["SOURCE_REFERENCE_COUNT"],
        "blocked": not granted,
        "block_reason": None if granted else "OPERATOR_APPROVAL_REQUIRED",
        "note": (
            "Approval token accepted for a future scan; no scan is executed by "
            "Stage A."
            if granted
            else "A separate explicit operator approval is required before any "
            "real source body may be scanned."
        ),
    }


# ---------------------------------------------------------------------------
# E. Stage A assembly and reporting
# ---------------------------------------------------------------------------


def build_stage_a(
    fixtures: dict,
    *,
    expected: dict | None = None,
    generated_at: str | None = None,
    approved_roots: tuple[str | Path, ...] = (),
    approval_token: str | None = None,
) -> dict:
    timestamp = generated_at or _now_iso()
    validation = validate_inputs(fixtures, expected=expected or EXPECTED_BASELINE)
    if not validation["inputs_valid"]:
        raise InputError(
            INPUT_COUNT_MISMATCH,
            "inputs",
            "; ".join(item["key"] for item in validation["mismatches"]),
        )

    scan_plan = build_scan_plan(
        fixtures, generated_at=timestamp, approved_roots=approved_roots
    )
    detection_policy = build_detection_policy(generated_at=timestamp)
    provenance_plan = build_provenance_review_plan(
        fixtures, generated_at=timestamp
    )
    redaction_policy = build_redaction_policy(generated_at=timestamp)
    approval_gate = build_approval_gate(
        scan_plan, approval_token=approval_token
    )

    counts = scan_plan["counts"]
    if not (
        counts["ALL_APPROVED_FALSE"]
        and counts["ALL_IMPORT_READY_FALSE"]
        and counts["ALL_REAL_IMPORT_ALLOWED_FALSE"]
        and counts["ALL_SECRET_REVIEW_NOT_PERFORMED"]
        and provenance_plan["counts"]["ALL_CONFIRMATIONS_FALSE"]
    ):
        raise SecurityBoundaryError(
            "authority invariants violated: approved/import flags must stay false "
            "and provenance must stay unconfirmed"
        )
    if approval_gate["real_source_scan_executed"] or approval_gate["real_import_executed"]:
        raise SecurityBoundaryError("Stage A must not execute a scan or an import")

    return {
        "task_id": TASK_ID,
        "verdict": VERDICT_READY,
        "generated_at": timestamp,
        "mode": MODE_STAGE_A,
        "validation": validation,
        "scan_plan": scan_plan,
        "detection_policy": detection_policy,
        "provenance_review_plan": provenance_plan,
        "redaction_policy": redaction_policy,
        "approval_gate": approval_gate,
        "counts": counts,
        "acceptance": {
            "INPUTS_VALID": validation["inputs_valid"],
            "CONTENT_UNIQUE_COUNT": counts["CONTENT_UNIQUE_COUNT"],
            "SOURCE_REFERENCE_COUNT": counts["SOURCE_REFERENCE_COUNT"],
            "SECRET_SCAN_PLAN_CREATED": True,
            "SECRET_DETECTION_POLICY_CREATED": True,
            "PROVENANCE_REVIEW_PLAN_CREATED": True,
            "REDACTION_POLICY_CREATED": True,
            "REAL_SCAN_APPROVAL_REQUEST_CREATED": True,
            "ALL_SECRET_REVIEW_NOT_PERFORMED": counts[
                "ALL_SECRET_REVIEW_NOT_PERFORMED"
            ],
            "ALL_APPROVED_FALSE": counts["ALL_APPROVED_FALSE"],
            "ALL_IMPORT_READY_FALSE": counts["ALL_IMPORT_READY_FALSE"],
            "ALL_REAL_IMPORT_ALLOWED_FALSE": counts[
                "ALL_REAL_IMPORT_ALLOWED_FALSE"
            ],
            "NO_REAL_SOURCE_BODY_READ": True,
            "NO_REAL_SECRET_SCAN": True,
            "NO_REAL_IMPORT": True,
        },
    }


def render_approval_request(result: dict, *, generated_at: str) -> str:
    scan_plan = result["scan_plan"]
    counts = scan_plan["counts"]
    lines = [
        "# BC-11E-7A Real Source Secret Scan Approval Request",
        "",
        f"TASK_ID={TASK_ID}",
        f"generated_at={generated_at}",
        "REAL_SOURCE_CONTENT_SCAN_APPROVED=NO",
        "REAL_IMPORT_APPROVED=NO",
        "",
        "## Request",
        "",
        "Approve a future, separately executed scan of the representative source",
        "files for the content-unique historical report candidates listed in",
        "BC11E7A_SECRET_SCAN_PLAN.json.",
        "",
        f"CONTENT_UNIQUE_CANDIDATE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"SCAN_TARGET_COUNT={counts['SCAN_TARGET_COUNT']}",
        f"ADDITIONAL_COPY_COUNT={counts['ADDITIONAL_COPY_COUNT']}",
        "",
        "Duplicate copies are preserved as references but are not re-scanned.",
        "",
        "## Required Path Safety Controls",
        "",
        "- Only approved roots may be scanned.",
        "- Absolute regular files only; symlinks are rejected.",
        "- Path traversal and secret-like filenames are rejected.",
        "- `O_NOFOLLOW` open with a post-open `fstat` regular-file check.",
        "- Streaming reads only, with a size limit.",
        "- Pre- and post-read `fstat` metadata consistency checks.",
        "",
        "## What This Stage Did Not Do",
        "",
        "REAL_SOURCE_SCAN_EXECUTED=NO",
        "REAL_SOURCE_BODY_READ=NO",
        "REAL_IMPORT_EXECUTED=NO",
        "",
        "## Next Required Approval",
        "",
        "A future task must pass the explicit token below. This Stage A output",
        "does not contain it and cannot enable a real scan.",
        "",
        f"REQUIRED_APPROVAL_TOKEN={REAL_SCAN_APPROVAL_TOKEN}",
        "",
        "Until that approval, every candidate remains:",
        "",
        "secret_review_status=NOT_PERFORMED",
        "secret_review_required=true",
        "secret_scan_approved=false",
        "approved=false",
        "import_ready=false",
        "real_import_allowed=false",
        "",
    ]
    return "\n".join(lines)


def render_final(result: dict, meta: dict) -> str:
    counts = result["counts"]
    acceptance = result["acceptance"]
    lines = [
        "# BC-11E-7A Stage A Final Report",
        "",
        f"TASK_ID={TASK_ID}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "",
        f"CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"SECRET_SCAN_PLAN_COUNT={counts['SCAN_TARGET_COUNT']}",
        f"SECRET_DETECTION_POLICY_CREATED={str(acceptance['SECRET_DETECTION_POLICY_CREATED']).upper()}",
        f"PROVENANCE_REVIEW_PLAN_CREATED={str(acceptance['PROVENANCE_REVIEW_PLAN_CREATED']).upper()}",
        f"REDACTION_POLICY_CREATED={str(acceptance['REDACTION_POLICY_CREATED']).upper()}",
        f"REAL_SCAN_APPROVAL_REQUEST_CREATED={str(acceptance['REAL_SCAN_APPROVAL_REQUEST_CREATED']).upper()}",
        f"ALL_SECRET_REVIEW_NOT_PERFORMED={str(acceptance['ALL_SECRET_REVIEW_NOT_PERFORMED']).upper()}",
        f"ALL_APPROVED_FALSE={str(acceptance['ALL_APPROVED_FALSE']).upper()}",
        f"ALL_IMPORT_READY_FALSE={str(acceptance['ALL_IMPORT_READY_FALSE']).upper()}",
        f"ALL_REAL_IMPORT_ALLOWED_FALSE={str(acceptance['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
        "",
        "TEST_RESULTS=" + meta.get("test_results", "PENDING"),
        "CHANGED_FILES=" + meta.get("changed_files", "UNKNOWN"),
        "COMMIT=" + meta.get("commit", "NONE"),
        "PRODUCTION_DB_UNCHANGED=YES",
        "CANONICAL_UNCHANGED=YES",
        "WORK_AA_UNCHANGED=YES",
        "BB_CC_UNCHANGED=YES",
        "REAL_SOURCE_SCAN_EXECUTED=NO",
        "REAL_IMPORT_EXECUTED=NO",
        "GIT_PUSH=NO",
        "PRODUCTION_RESTART=NO",
        "",
        "NEXT_REQUIRED_APPROVAL="
        + meta.get("next_required_approval", REAL_SCAN_APPROVAL_TOKEN),
        "",
    ]
    return "\n".join(lines)


def write_stage_a_outputs(
    result: dict,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    meta: dict | None = None,
) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    meta = meta or {}
    paths = {
        "secret_scan_plan": target / SCAN_PLAN_JSON_NAME,
        "secret_detection_policy": target / DETECTION_POLICY_JSON_NAME,
        "provenance_review_plan": target / PROVENANCE_PLAN_JSON_NAME,
        "redaction_policy": target / REDACTION_POLICY_JSON_NAME,
        "real_scan_approval_request": target / APPROVAL_REQUEST_MD_NAME,
        "stage_a_final": target / FINAL_MD_NAME,
    }
    for key in (
        "secret_scan_plan",
        "secret_detection_policy",
        "provenance_review_plan",
        "redaction_policy",
    ):
        payload = {
            "secret_scan_plan": result["scan_plan"],
            "secret_detection_policy": result["detection_policy"],
            "provenance_review_plan": result["provenance_review_plan"],
            "redaction_policy": result["redaction_policy"],
        }[key]
        paths[key].write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    paths["real_scan_approval_request"].write_text(
        render_approval_request(result, generated_at=result["generated_at"]) + "\n",
        encoding="utf-8",
    )
    paths["stage_a_final"].write_text(
        render_final(result, meta) + "\n", encoding="utf-8"
    )
    return {key: str(path) for key, path in paths.items()}


# ---------------------------------------------------------------------------
# F. Stage B approved, read-only real source content scan
# ---------------------------------------------------------------------------


def _empty_severity_counts() -> dict[str, int]:
    return {severity: 0 for severity in SEVERITY_ORDER}


def _stage_b_rejection_status(code: str) -> str:
    if code in {
        REJECT_METADATA_CHANGED,
        REJECT_DEVICE_OR_INODE_CHANGED,
        REJECT_CHANGED_DURING_READ,
    }:
        return SOURCE_CHANGED
    if code == REJECT_FILE_NOT_FOUND:
        return SOURCE_UNAVAILABLE
    if code in {REJECT_OPEN_FAILED, REJECT_STAT_FAILED}:
        return SCAN_FAILED
    return SOURCE_REJECTED


# Only explicit self-identification lines confirm a producing tool. A bare
# mention of a tool name, the filename, or the save location never confirms.
_PROVENANCE_STRONG_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    PROVENANCE_CURSOR_CANDIDATE: (
        re.compile(
            r"(?im)^\s*(?:generated|produced|created|authored|written|prepared)"
            r"\s+by\s*[:=\-]?\s*cursor\b"
        ),
        re.compile(
            r"(?im)^\s*(?:agent|tool|assistant|author|model|provider)"
            r"\s*[:=]\s*cursor\b"
        ),
    ),
    PROVENANCE_OPENCODE_CANDIDATE: (
        re.compile(
            r"(?im)^\s*(?:generated|produced|created|authored|written|prepared)"
            r"\s+by\s*[:=\-]?\s*opencode\b"
        ),
        re.compile(
            r"(?im)^\s*(?:agent|tool|assistant|author|model|provider)"
            r"\s*[:=]\s*opencode\b"
        ),
    ),
    PROVENANCE_CHATGPT_CANDIDATE: (
        re.compile(
            r"(?im)^\s*(?:generated|produced|created|authored|written|prepared)"
            r"\s+by\s*[:=\-]?\s*(?:chatgpt|openai)\b"
        ),
        re.compile(
            r"(?im)^\s*(?:agent|tool|assistant|author|model|provider)"
            r"\s*[:=]\s*(?:chatgpt|openai)\b"
        ),
    ),
    PROVENANCE_OTHER_AGENT_CANDIDATE: (
        re.compile(
            r"(?im)^\s*(?:generated|produced|created|authored|written|prepared)"
            r"\s+by\s*[:=\-]?\s*(?:claude|anthropic|aider|codex|gemini|copilot|"
            r"devin|windsurf|cline|continue)\b"
        ),
        re.compile(
            r"(?im)^\s*(?:agent|tool|assistant|author|model|provider)"
            r"\s*[:=]\s*(?:claude|anthropic|aider|codex|gemini|copilot|"
            r"devin|windsurf|cline|continue)\b"
        ),
    ),
}

_PROVENANCE_WEAK_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    PROVENANCE_CURSOR_CANDIDATE: (
        re.compile(r"(?im)^.*\bcursor\b.*\b(?:agent|tool|session|model|author)\b.*$"),
    ),
    PROVENANCE_OPENCODE_CANDIDATE: (
        re.compile(r"(?im)^.*\bopencode\b.*\b(?:agent|tool|session|model|author)\b.*$"),
    ),
    PROVENANCE_CHATGPT_CANDIDATE: (
        re.compile(r"(?im)^.*\bchatgpt\b.*\b(?:agent|tool|session|model|author)\b.*$"),
    ),
    PROVENANCE_OTHER_AGENT_CANDIDATE: (
        re.compile(
            r"(?im)^.*\b(?:claude|anthropic|aider|codex|gemini|copilot)\b"
            r".*\b(?:agent|tool|session|model|author)\b.*$"
        ),
    ),
}


def _evidence_counts(
    text: str, patterns: dict[str, tuple[re.Pattern[str], ...]]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for classification in PROVENANCE_CLASS_ORDER:
        total = 0
        for pattern in patterns.get(classification, ()):  # pragma: no branch
            total += sum(1 for _ in pattern.finditer(text))
        counts[classification] = total
    return counts


def _unknown_provenance(
    content_hash: str,
    representative_source_id: str,
    *,
    body_read: bool,
) -> dict:
    return {
        "content_hash": content_hash,
        "representative_source_id": representative_source_id,
        "classification": PROVENANCE_UNKNOWN_CLASS,
        "classifications": [PROVENANCE_UNKNOWN_CLASS],
        "provenance_status": PROVENANCE_UNKNOWN_CLASS,
        "confirmed": False,
        "confirmed_cursor": False,
        "confirmed_opencode": False,
        "confirmed_chatgpt": False,
        "confirmed_other_agent": False,
        "strong_signal_counts": {
            classification: 0 for classification in PROVENANCE_CLASS_ORDER
        },
        "weak_signal_counts": {
            classification: 0 for classification in PROVENANCE_CLASS_ORDER
        },
        "body_read": body_read,
        "review_required": True,
        "review_status": REVIEW_NOT_STARTED,
        "evidence_policy": {
            "filename_alone_is_sufficient": False,
            "save_location_alone_is_sufficient": False,
            "bare_tool_mention_is_sufficient": False,
            "requires_explicit_self_identification": True,
            "requires_operator_confirmation": True,
        },
        "historical_record": True,
        "historical_runtime_authority": False,
        "source_truth_class": SOURCE_TRUTH_CLASS,
        "authority_scope": AUTHORITY_SCOPE,
    }


def classify_provenance_evidence(
    text: str, *, content_hash: str, representative_source_id: str
) -> dict:
    """Return safe provenance evidence. Never stores body text or secrets."""

    evidence = _unknown_provenance(
        content_hash, representative_source_id, body_read=True
    )
    strong = _evidence_counts(text, _PROVENANCE_STRONG_PATTERNS)
    weak = _evidence_counts(text, _PROVENANCE_WEAK_PATTERNS)
    evidence["strong_signal_counts"] = strong
    evidence["weak_signal_counts"] = weak

    strong_classes = [
        classification
        for classification in PROVENANCE_CLASS_ORDER
        if strong.get(classification, 0) > 0
    ]
    weak_classes = [
        classification
        for classification in PROVENANCE_CLASS_ORDER
        if weak.get(classification, 0) > 0
    ]

    if len(strong_classes) == 1:
        classification = strong_classes[0]
        evidence["classification"] = classification
        evidence["classifications"] = [classification]
        evidence["provenance_status"] = PROVENANCE_CONFIRMED
        evidence["confirmed"] = True
        evidence["confirmed_cursor"] = (
            classification == PROVENANCE_CURSOR_CANDIDATE
        )
        evidence["confirmed_opencode"] = (
            classification == PROVENANCE_OPENCODE_CANDIDATE
        )
        evidence["confirmed_chatgpt"] = (
            classification == PROVENANCE_CHATGPT_CANDIDATE
        )
        evidence["confirmed_other_agent"] = (
            classification == PROVENANCE_OTHER_AGENT_CANDIDATE
        )
    elif len(weak_classes) == 1:
        evidence["classification"] = weak_classes[0]
        evidence["classifications"] = [weak_classes[0]]
    return evidence


def scan_target(
    candidate: dict,
    *,
    approved_roots: tuple[str | Path, ...] = (),
    max_bytes: int = MAX_SCAN_BYTES,
) -> dict:
    """Read one representative source file read-only and detect secrets."""

    content_hash = str(candidate["content_hash"])
    representative = str(candidate["representative_source_id"])
    result: dict = {
        "content_hash": content_hash,
        "representative_source_id": representative,
        "absolute_path": str(candidate["absolute_path"]),
        "source_root": str(candidate["source_root"]),
        "size_bytes": candidate.get("size_bytes"),
        "mtime": candidate.get("mtime"),
        "scan_status": None,
        "finding_count": 0,
        "severity_counts": _empty_severity_counts(),
        "confidence_counts": {},
        "highest_severity": None,
        "findings": [],
        "review_required": True,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "source_metadata_match": False,
        "content_hash_verified": False,
        "rejection_reason": None,
        "failure_reason": None,
        "provenance_evidence": _unknown_provenance(
            content_hash, representative, body_read=False
        ),
        "import_eligibility": None,
        "eligibility_reasons": [],
    }

    expected_size = (
        int(candidate["size_bytes"])
        if candidate.get("size_bytes") is not None
        else None
    )
    expected_mtime = str(candidate["mtime"]) if candidate.get("mtime") else None

    hasher = hashlib.sha256()
    buffer = bytearray()
    try:
        for chunk in iter_verified_chunks(
            candidate["absolute_path"],
            candidate["source_root"],
            approved_roots=approved_roots,
            max_bytes=max_bytes,
            expected_size=expected_size,
            expected_mtime=expected_mtime,
        ):
            hasher.update(chunk)
            buffer.extend(chunk)
    except ScanRejected as exc:
        result["scan_status"] = _stage_b_rejection_status(exc.code)
        result["rejection_reason"] = exc.code
        return result
    except OSError as exc:
        result["scan_status"] = SCAN_FAILED
        result["failure_reason"] = type(exc).__name__
        return result

    result["source_metadata_match"] = True
    if hasher.hexdigest() != content_hash:
        result["scan_status"] = SOURCE_CHANGED
        result["rejection_reason"] = "CONTENT_HASH_MISMATCH"
        return result

    result["content_hash_verified"] = True
    text = bytes(buffer).decode("utf-8", errors="replace")
    del buffer
    try:
        internal = scan_text(text)
        findings = serialize_findings(internal, content_hash=content_hash)
        del internal
        summary = summarize_findings(findings)
        provenance = classify_provenance_evidence(
            text,
            content_hash=content_hash,
            representative_source_id=representative,
        )
    finally:
        del text

    severity_counts = _empty_severity_counts()
    severity_counts.update(
        {
            str(key): int(value)
            for key, value in summary["by_severity"].items()
            if key in severity_counts
        }
    )
    result["findings"] = findings
    result["finding_count"] = int(summary["finding_count"])
    result["severity_counts"] = severity_counts
    result["confidence_counts"] = dict(summary["by_confidence"])
    result["highest_severity"] = summary["highest_severity"]
    result["provenance_evidence"] = provenance
    result["scan_status"] = (
        SCAN_COMPLETED_FINDINGS if findings else SCAN_COMPLETED_NO_FINDINGS
    )
    return result


def classify_import_eligibility(target: dict) -> tuple[str, list[str]]:
    status = target["scan_status"]
    if status == SCAN_COMPLETED_NO_FINDINGS:
        return ELIGIBLE_CANDIDATE, [
            "SECRET_SCAN_COMPLETED_NO_FINDINGS",
            "NOT_AN_IMPORT_APPROVAL",
            "OPERATOR_REVIEW_NOT_STARTED",
        ]
    if status == SCAN_COMPLETED_FINDINGS:
        actions = {
            str(finding.get("default_action"))
            for finding in target.get("findings", [])
        }
        if ACTION_EXCLUDE in actions or ACTION_REVIEW in actions:
            return MANUAL_REVIEW_REQUIRED, [
                "SECRET_FINDING_REQUIRES_MANUAL_REVIEW",
                "NOT_AN_IMPORT_APPROVAL",
            ]
        return REDACTION_REQUIRED, [
            "SECRET_FINDING_REDACTION_REQUIRED",
            "NOT_AN_IMPORT_APPROVAL",
        ]
    if status == SCAN_FAILED:
        return MANUAL_REVIEW_REQUIRED, ["SCAN_FAILED", "NOT_AN_IMPORT_APPROVAL"]
    if status == SOURCE_CHANGED:
        return MANUAL_REVIEW_REQUIRED, [
            "SOURCE_CHANGED",
            "NOT_AN_IMPORT_APPROVAL",
        ]
    if status == SOURCE_UNAVAILABLE:
        return SOURCE_UNAVAILABLE, ["SOURCE_UNAVAILABLE", "NOT_AN_IMPORT_APPROVAL"]
    if status == SOURCE_REJECTED:
        return SOURCE_REJECTED, ["SOURCE_REJECTED", "NOT_AN_IMPORT_APPROVAL"]
    return MANUAL_REVIEW_REQUIRED, ["UNRECOGNIZED_SCAN_STATUS", "NOT_AN_IMPORT_APPROVAL"]


def validate_stage_b_plan(
    scan_plan: dict,
    provenance_plan: dict,
    hash_results: dict,
    manifest_review: dict,
    *,
    expected_targets: int = EXPECTED_TARGET_COUNT,
    expected_references: int = EXPECTED_SOURCE_REFERENCE_COUNT,
) -> dict:
    candidates = scan_plan.get("candidates")
    references = scan_plan.get("source_references")
    _require(isinstance(candidates, list), "secret_scan_plan", "candidates is not a list")
    _require(
        isinstance(references, list),
        "secret_scan_plan",
        "source_references is not a list",
    )
    _require_fields(
        candidates, REQUIRED_STAGE_B_CANDIDATE_FIELDS, "secret_scan_plan"
    )

    mismatches: list[dict] = []

    def _check(key: str, expected: object, actual: object) -> None:
        if expected != actual:
            mismatches.append(
                {
                    "key": key,
                    "expected": expected,
                    "actual": actual,
                }
            )

    _check("EXPECTED_TARGET_COUNT", expected_targets, len(candidates))
    _check("SOURCE_REFERENCE_COUNT", expected_references, len(references))

    hashes = [str(candidate["content_hash"]) for candidate in candidates]
    representatives = [
        str(candidate["representative_source_id"]) for candidate in candidates
    ]
    _check("DISTINCT_CONTENT_HASHES", len(candidates), len(set(hashes)))
    _check("DISTINCT_REPRESENTATIVE_IDS", len(candidates), len(set(representatives)))

    reference_ids = {
        str(reference["source_id"]): reference for reference in references
    }
    inspection_targets = [
        reference
        for reference in references
        if reference.get("inspection_target") is True
    ]
    _check(
        "SOURCE_REFERENCE_INSPECTION_TARGET_COUNT",
        expected_targets,
        len(inspection_targets),
    )

    unresolved = 0
    for candidate in candidates:
        reference = reference_ids.get(str(candidate["representative_source_id"]))
        if reference is None:
            unresolved += 1
            continue
        if str(reference.get("content_hash")) != str(candidate["content_hash"]):
            unresolved += 1
    _check("REPRESENTATIVE_REFERENCES_RESOLVE", 0, unresolved)

    metadata_incomplete = [
        str(candidate["representative_source_id"])
        for candidate in candidates
        if not candidate.get("source_metadata_available")
        or not candidate.get("source_metadata_hash_matches")
    ]
    _check("SOURCE_METADATA_AVAILABLE_AND_MATCHING", 0, len(metadata_incomplete))

    provenance_entries = provenance_plan.get("entries")
    _require(
        isinstance(provenance_entries, list),
        "provenance_review_plan",
        "entries is not a list",
    )
    _check("PROVENANCE_REVIEW_COUNT", expected_targets, len(provenance_entries))

    manifest_entries = manifest_review.get("entries")
    _require(
        isinstance(manifest_entries, list),
        "import_manifest_review",
        "entries is not a list",
    )
    _check("IMPORT_MANIFEST_COUNT", expected_targets, len(manifest_entries))

    hash_entries = hash_results.get("entries")
    _require(
        isinstance(hash_entries, list), "hash_results", "entries is not a list"
    )

    return {
        "status": BLOCKED_INVALID_INPUT if mismatches else INPUTS_VALID,
        "valid": not mismatches,
        "mismatches": mismatches,
        "counts": {
            "EXPECTED_TARGET_COUNT": expected_targets,
            "ACTUAL_SCAN_TARGET_COUNT": len(candidates),
            "SOURCE_REFERENCE_COUNT": len(references),
            "SOURCE_REFERENCE_INSPECTION_TARGET_COUNT": len(inspection_targets),
            "PROVENANCE_REVIEW_COUNT": len(provenance_entries),
            "IMPORT_MANIFEST_COUNT": len(manifest_entries),
            "HASH_RESULT_ENTRY_COUNT": len(hash_entries),
        },
    }


def _aggregate_finding_totals(targets: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    by_severity = _empty_severity_counts()
    by_confidence: dict[str, int] = {}
    for target in targets:
        for finding in target.get("findings", []):
            secret_type = str(finding["secret_type"])
            severity = str(finding["severity"])
            confidence = str(finding["confidence"])
            by_type[secret_type] = by_type.get(secret_type, 0) + 1
            if severity in by_severity:
                by_severity[severity] += 1
            by_confidence[confidence] = by_confidence.get(confidence, 0) + 1
    return {
        "by_secret_type": dict(sorted(by_type.items())),
        "by_severity": by_severity,
        "by_confidence": dict(sorted(by_confidence.items())),
    }


def build_stage_b(
    *,
    scan_plan: dict,
    provenance_plan: dict,
    hash_results: dict,
    manifest_review: dict,
    detection_policy: dict,
    redaction_policy: dict,
    generated_at: str | None = None,
    approval_granted: bool = False,
    approved_roots: tuple[str | Path, ...] = (),
    max_bytes: int = MAX_SCAN_BYTES,
    expected_targets: int = EXPECTED_TARGET_COUNT,
    expected_references: int = EXPECTED_SOURCE_REFERENCE_COUNT,
) -> dict:
    if not approval_granted:
        raise SecurityBoundaryError(
            "REAL_SOURCE_SCAN_APPROVED is required before any real source "
            "body may be opened"
        )

    _require(
        isinstance(detection_policy, dict)
        and detection_policy.get("schema_version")
        == DETECTION_POLICY_SCHEMA_VERSION,
        "secret_detection_policy",
        "unexpected schema_version",
    )
    _require(
        isinstance(redaction_policy, dict)
        and redaction_policy.get("schema_version") == REDACTION_POLICY_SCHEMA_VERSION,
        "redaction_policy",
        "unexpected schema_version",
    )

    timestamp = generated_at or _now_iso()
    validation = validate_stage_b_plan(
        scan_plan,
        provenance_plan,
        hash_results,
        manifest_review,
        expected_targets=expected_targets,
        expected_references=expected_references,
    )
    if not validation["valid"]:
        raise InputError(
            BLOCKED_INVALID_INPUT,
            "stage_b_inputs",
            "; ".join(item["key"] for item in validation["mismatches"]),
        )

    roots = tuple(approved_roots) or tuple(scan_plan.get("approved_roots") or ())
    candidates = sorted(
        scan_plan["candidates"], key=lambda candidate: str(candidate["content_hash"])
    )

    targets: list[dict] = []
    for candidate in candidates:
        target = scan_target(candidate, approved_roots=roots, max_bytes=max_bytes)
        eligibility, reasons = classify_import_eligibility(target)
        target["import_eligibility"] = eligibility
        target["eligibility_reasons"] = reasons
        targets.append(target)

    finding_totals = _aggregate_finding_totals(targets)

    def _status_count(*statuses: str) -> int:
        return sum(1 for target in targets if target["scan_status"] in statuses)

    def _eligibility_count(eligibility: str) -> int:
        return sum(
            1 for target in targets if target["import_eligibility"] == eligibility
        )

    confirmed = sum(
        1
        for target in targets
        if target["provenance_evidence"]["provenance_status"]
        == PROVENANCE_CONFIRMED
    )
    unknown = sum(
        1
        for target in targets
        if target["provenance_evidence"]["provenance_status"]
        == PROVENANCE_UNKNOWN_CLASS
    )

    counts = {
        "EXPECTED_TARGET_COUNT": expected_targets,
        "ACTUAL_SCAN_TARGET_COUNT": len(targets),
        "SOURCE_REFERENCE_COUNT": int(
            scan_plan.get("counts", {}).get(
                "SOURCE_REFERENCE_COUNT", len(scan_plan["source_references"])
            )
        ),
        "SCAN_COMPLETED_COUNT": _status_count(*SCAN_COMPLETED_STATUSES),
        "SCAN_COMPLETED_NO_FINDINGS_COUNT": _status_count(
            SCAN_COMPLETED_NO_FINDINGS
        ),
        "SCAN_COMPLETED_FINDINGS_COUNT": _status_count(
            SCAN_COMPLETED_FINDINGS
        ),
        "SCAN_FAILED_COUNT": _status_count(SCAN_FAILED),
        "SOURCE_CHANGED_COUNT": _status_count(SOURCE_CHANGED),
        "SOURCE_UNAVAILABLE_COUNT": _status_count(SOURCE_UNAVAILABLE),
        "SOURCE_REJECTED_COUNT": _status_count(SOURCE_REJECTED),
        "SECRET_FINDING_COUNT": int(
            sum(target["finding_count"] for target in targets)
        ),
        "CRITICAL_FINDING_COUNT": finding_totals["by_severity"][SEVERITY_CRITICAL],
        "HIGH_FINDING_COUNT": finding_totals["by_severity"][SEVERITY_HIGH],
        "MEDIUM_FINDING_COUNT": finding_totals["by_severity"][SEVERITY_MEDIUM],
        "LOW_FINDING_COUNT": finding_totals["by_severity"][SEVERITY_LOW],
        "UNKNOWN_FINDING_COUNT": finding_totals["by_severity"][SEVERITY_UNKNOWN],
        "ELIGIBLE_CANDIDATE_COUNT": _eligibility_count(ELIGIBLE_CANDIDATE),
        "REDACTION_REQUIRED_COUNT": _eligibility_count(REDACTION_REQUIRED),
        "MANUAL_REVIEW_REQUIRED_COUNT": _eligibility_count(
            MANUAL_REVIEW_REQUIRED
        ),
        "PROVENANCE_CONFIRMED_COUNT": confirmed,
        "PROVENANCE_UNKNOWN_COUNT": unknown,
        "ALL_APPROVED_FALSE": all(
            target["approved"] is False for target in targets
        ),
        "ALL_IMPORT_READY_FALSE": all(
            target["import_ready"] is False for target in targets
        ),
        "ALL_REAL_IMPORT_ALLOWED_FALSE": all(
            target["real_import_allowed"] is False for target in targets
        ),
    }

    recorded = [
        target for target in targets if target["scan_status"] in SCAN_RESULT_STATUSES
    ]
    verdict = (
        VERDICT_STAGE_B_COMPLETE
        if len(recorded) == expected_targets
        else VERDICT_STAGE_B_PARTIAL
    )

    if not (
        counts["ALL_APPROVED_FALSE"]
        and counts["ALL_IMPORT_READY_FALSE"]
        and counts["ALL_REAL_IMPORT_ALLOWED_FALSE"]
    ):
        raise SecurityBoundaryError(
            "authority invariants violated: approved/import flags must stay false"
        )

    per_target_summary = [
        {
            "content_hash": target["content_hash"],
            "representative_source_id": target["representative_source_id"],
            "scan_status": target["scan_status"],
            "finding_count": target["finding_count"],
            "severity_counts": target["severity_counts"],
            "review_required": target["review_required"],
        }
        for target in targets
    ]

    secret_findings_summary = {
        "task_id": TASK_ID_STAGE_B,
        "schema_version": FINDINGS_SUMMARY_SCHEMA_VERSION,
        "mode": MODE_STAGE_B,
        "generated_at": timestamp,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "real_import_executed": False,
        "real_source_scan_approved": True,
        "values_stored": False,
        "context_stored": False,
        "secret_value_hash_stored": False,
        "counts": {
            "SECRET_FINDING_COUNT": counts["SECRET_FINDING_COUNT"],
            "CRITICAL_FINDING_COUNT": counts["CRITICAL_FINDING_COUNT"],
            "HIGH_FINDING_COUNT": counts["HIGH_FINDING_COUNT"],
            "MEDIUM_FINDING_COUNT": counts["MEDIUM_FINDING_COUNT"],
            "LOW_FINDING_COUNT": counts["LOW_FINDING_COUNT"],
            "UNKNOWN_FINDING_COUNT": counts["UNKNOWN_FINDING_COUNT"],
        },
        "by_secret_type": finding_totals["by_secret_type"],
        "by_severity": finding_totals["by_severity"],
        "by_confidence": finding_totals["by_confidence"],
        "per_target": per_target_summary,
    }

    provenance_entries = [
        dict(target["provenance_evidence"]) for target in targets
    ]
    provenance_evidence_review = {
        "task_id": TASK_ID_STAGE_B,
        "schema_version": PROVENANCE_EVIDENCE_SCHEMA_VERSION,
        "mode": MODE_STAGE_B,
        "generated_at": timestamp,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "counts": {
            "PROVENANCE_REVIEW_COUNT": len(provenance_entries),
            "PROVENANCE_CONFIRMED_COUNT": confirmed,
            "PROVENANCE_UNKNOWN_COUNT": unknown,
            "CONFIRMED_CURSOR_COUNT": sum(
                1 for entry in provenance_entries if entry["confirmed_cursor"]
            ),
            "CONFIRMED_OPENCODE_COUNT": sum(
                1 for entry in provenance_entries if entry["confirmed_opencode"]
            ),
            "CONFIRMED_CHATGPT_COUNT": sum(
                1 for entry in provenance_entries if entry["confirmed_chatgpt"]
            ),
            "CONFIRMED_OTHER_AGENT_COUNT": sum(
                1 for entry in provenance_entries if entry["confirmed_other_agent"]
            ),
            "ALL_CONFIRMATIONS_REVIEW_REQUIRED": True,
        },
        "policy": {
            "filename_is_not_proof": True,
            "save_location_is_not_proof": True,
            "bare_tool_mention_is_not_proof": True,
            "requires_explicit_self_identification": True,
            "requires_operator_confirmation": True,
        },
        "entries": provenance_entries,
    }

    eligibility_entries = [
        {
            "content_hash": target["content_hash"],
            "representative_source_id": target["representative_source_id"],
            "scan_status": target["scan_status"],
            "secret_finding_count": target["finding_count"],
            "severity_counts": target["severity_counts"],
            "import_eligibility": target["import_eligibility"],
            "eligibility_reasons": list(target["eligibility_reasons"]),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
            "secret_review_status": target["scan_status"],
            "review_required": True,
            "review_status": REVIEW_NOT_STARTED,
            "source_truth_class": SOURCE_TRUTH_CLASS,
            "authority_scope": AUTHORITY_SCOPE,
            "historical_record": True,
            "historical_runtime_authority": False,
        }
        for target in targets
    ]
    import_eligibility_review = {
        "task_id": TASK_ID_STAGE_B,
        "schema_version": IMPORT_ELIGIBILITY_SCHEMA_VERSION,
        "mode": MODE_STAGE_B,
        "generated_at": timestamp,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "real_import_executed": False,
        "counts": {
            "IMPORT_ELIGIBILITY_REVIEW_COUNT": len(eligibility_entries),
            "ELIGIBLE_CANDIDATE_COUNT": counts["ELIGIBLE_CANDIDATE_COUNT"],
            "REDACTION_REQUIRED_COUNT": counts["REDACTION_REQUIRED_COUNT"],
            "MANUAL_REVIEW_REQUIRED_COUNT": counts[
                "MANUAL_REVIEW_REQUIRED_COUNT"
            ],
            "SOURCE_UNAVAILABLE_COUNT": sum(
                1
                for entry in eligibility_entries
                if entry["import_eligibility"] == SOURCE_UNAVAILABLE
            ),
            "SOURCE_REJECTED_COUNT": sum(
                1
                for entry in eligibility_entries
                if entry["import_eligibility"] == SOURCE_REJECTED
            ),
            "ALL_APPROVED_FALSE": True,
            "ALL_IMPORT_READY_FALSE": True,
            "ALL_REAL_IMPORT_ALLOWED_FALSE": True,
        },
        "entries": eligibility_entries,
    }

    acceptance = {
        "REAL_SOURCE_SCAN_APPROVED": True,
        "EXPECTED_TARGET_COUNT": expected_targets,
        "ACTUAL_SCAN_TARGET_COUNT": len(targets),
        "SOURCE_REFERENCE_COUNT": counts["SOURCE_REFERENCE_COUNT"],
        "ALL_TARGETS_EXPLICITLY_RECORDED": len(recorded) == expected_targets,
        "ALL_APPROVED_FALSE": counts["ALL_APPROVED_FALSE"],
        "ALL_IMPORT_READY_FALSE": counts["ALL_IMPORT_READY_FALSE"],
        "ALL_REAL_IMPORT_ALLOWED_FALSE": counts[
            "ALL_REAL_IMPORT_ALLOWED_FALSE"
        ],
        "SOURCE_FILES_MODIFIED": False,
        "REAL_IMPORT_EXECUTED": False,
        "PRODUCTION_UNCHANGED": True,
        "CANONICAL_UNCHANGED": True,
    }

    return {
        "task_id": TASK_ID_STAGE_B,
        "verdict": verdict,
        "generated_at": timestamp,
        "mode": MODE_STAGE_B,
        "approval_granted": True,
        "validation": validation,
        "counts": counts,
        "finding_totals": finding_totals,
        "targets": targets,
        "secret_findings_summary": secret_findings_summary,
        "provenance_evidence_review": provenance_evidence_review,
        "import_eligibility_review": import_eligibility_review,
        "safety": {
            "source_files_modified": False,
            "real_import_executed": False,
            "production_database_written": False,
            "canonical_written": False,
            "secret_values_stored": False,
            "source_body_stored": False,
            "secret_value_hash_stored": False,
        },
        "acceptance": acceptance,
    }


def _write_private_text(path: Path, text: str) -> None:
    descriptor = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def render_stage_b_final(result: dict, meta: dict) -> str:
    counts = result["counts"]
    acceptance = result["acceptance"]
    lines = [
        "# BC-11E-7A Stage B Final Report",
        "",
        f"TASK_ID={result['task_id']}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "",
        "REAL_SOURCE_SCAN_APPROVED="
        + ("YES" if acceptance["REAL_SOURCE_SCAN_APPROVED"] else "NO"),
        f"EXPECTED_TARGET_COUNT={counts['EXPECTED_TARGET_COUNT']}",
        f"ACTUAL_SCAN_TARGET_COUNT={counts['ACTUAL_SCAN_TARGET_COUNT']}",
        f"SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"SCAN_COMPLETED_COUNT={counts['SCAN_COMPLETED_COUNT']}",
        f"SCAN_COMPLETED_NO_FINDINGS_COUNT={counts['SCAN_COMPLETED_NO_FINDINGS_COUNT']}",
        f"SCAN_COMPLETED_FINDINGS_COUNT={counts['SCAN_COMPLETED_FINDINGS_COUNT']}",
        f"SCAN_FAILED_COUNT={counts['SCAN_FAILED_COUNT']}",
        f"SOURCE_CHANGED_COUNT={counts['SOURCE_CHANGED_COUNT']}",
        f"SOURCE_UNAVAILABLE_COUNT={counts['SOURCE_UNAVAILABLE_COUNT']}",
        f"SOURCE_REJECTED_COUNT={counts['SOURCE_REJECTED_COUNT']}",
        f"SECRET_FINDING_COUNT={counts['SECRET_FINDING_COUNT']}",
        f"CRITICAL_FINDING_COUNT={counts['CRITICAL_FINDING_COUNT']}",
        f"HIGH_FINDING_COUNT={counts['HIGH_FINDING_COUNT']}",
        f"MEDIUM_FINDING_COUNT={counts['MEDIUM_FINDING_COUNT']}",
        f"LOW_FINDING_COUNT={counts['LOW_FINDING_COUNT']}",
        f"UNKNOWN_FINDING_COUNT={counts['UNKNOWN_FINDING_COUNT']}",
        f"ELIGIBLE_CANDIDATE_COUNT={counts['ELIGIBLE_CANDIDATE_COUNT']}",
        f"REDACTION_REQUIRED_COUNT={counts['REDACTION_REQUIRED_COUNT']}",
        f"MANUAL_REVIEW_REQUIRED_COUNT={counts['MANUAL_REVIEW_REQUIRED_COUNT']}",
        f"PROVENANCE_CONFIRMED_COUNT={counts['PROVENANCE_CONFIRMED_COUNT']}",
        f"PROVENANCE_UNKNOWN_COUNT={counts['PROVENANCE_UNKNOWN_COUNT']}",
        "",
        f"SOURCE_FILES_MODIFIED={'NO' if not acceptance['SOURCE_FILES_MODIFIED'] else 'YES'}",
        f"ALL_APPROVED_FALSE={str(acceptance['ALL_APPROVED_FALSE']).upper()}",
        f"ALL_IMPORT_READY_FALSE={str(acceptance['ALL_IMPORT_READY_FALSE']).upper()}",
        f"ALL_REAL_IMPORT_ALLOWED_FALSE={str(acceptance['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
        f"ALL_TARGETS_EXPLICITLY_RECORDED={str(acceptance['ALL_TARGETS_EXPLICITLY_RECORDED']).upper()}",
        "",
        "TEST_RESULTS=" + meta.get("test_results", "PENDING"),
        "CHANGED_FILES=" + meta.get("changed_files", "UNKNOWN"),
        "COMMIT=" + meta.get("commit", "NONE"),
        "PRODUCTION_DB_UNCHANGED=YES",
        "CANONICAL_UNCHANGED=YES",
        "REAL_IMPORT_EXECUTED=NO",
        "GIT_PUSH=NO",
        "PRODUCTION_RESTART=NO",
        "",
        "NEXT_RECOMMENDED_TASK="
        + meta.get(
            "next_recommended_task",
            "BC-11E-7B_FINAL_IMPORT_APPROVAL_REVIEW",
        ),
        "",
    ]
    return "\n".join(lines)


def write_stage_b_outputs(
    result: dict,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    meta: dict | None = None,
) -> dict:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    meta = meta or {}
    paths = {
        "real_scan_results": target / REAL_SCAN_RESULTS_JSON_NAME,
        "secret_findings_summary": target / SECRET_FINDINGS_SUMMARY_JSON_NAME,
        "provenance_evidence_review": target / PROVENANCE_EVIDENCE_JSON_NAME,
        "import_eligibility_review": target / IMPORT_ELIGIBILITY_JSON_NAME,
        "stage_b_final": target / STAGE_B_FINAL_MD_NAME,
    }

    scan_results = {
        "task_id": result["task_id"],
        "schema_version": SCAN_RESULTS_SCHEMA_VERSION,
        "mode": result["mode"],
        "generated_at": result["generated_at"],
        "verdict": result["verdict"],
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "real_import_executed": False,
        "real_source_scan_approved": True,
        "source_body_stored": False,
        "secret_values_stored": False,
        "validation": result["validation"],
        "counts": result["counts"],
        "acceptance": result["acceptance"],
        "targets": result["targets"],
    }
    payloads = {
        "real_scan_results": scan_results,
        "secret_findings_summary": result["secret_findings_summary"],
        "provenance_evidence_review": result["provenance_evidence_review"],
        "import_eligibility_review": result["import_eligibility_review"],
    }
    for key, payload in payloads.items():
        _write_private_text(
            paths[key], json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
    _write_private_text(
        paths["stage_b_final"], render_stage_b_final(result, meta) + "\n"
    )
    return {key: str(path) for key, path in paths.items()}


INPUT_KEYS = (
    "content_review",
    "provenance_review",
    "import_manifest",
    "hash_results",
)
OPTIONAL_INPUT_KEYS = ("confirmed_duplicates", "unique_content_candidates")


def load_fixtures(paths: dict[str, str | Path]) -> dict:
    fixtures: dict = {}
    for key in INPUT_KEYS:
        fixtures[key] = load_input(paths[key])
    for key in OPTIONAL_INPUT_KEYS:
        fixtures[key] = load_optional_input(paths[key])
    fixtures["import_target_final"] = load_text_reference(paths["import_target_final"])
    return fixtures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-a", action="store_true", help="Run Stage A only.")
    parser.add_argument(
        "--stage-b",
        action="store_true",
        help="Run the approved read-only real source content scan.",
    )
    parser.add_argument(
        "--real-source-scan-approved",
        action="store_true",
        help="Explicit Stage B approval flag. Required to open any real source.",
    )
    parser.add_argument(
        "--secret-scan-plan", default=str(DEFAULT_SECRET_SCAN_PLAN_PATH)
    )
    parser.add_argument(
        "--secret-detection-policy", default=str(DEFAULT_DETECTION_POLICY_PATH)
    )
    parser.add_argument(
        "--provenance-review-plan", default=str(DEFAULT_PROVENANCE_PLAN_PATH)
    )
    parser.add_argument(
        "--redaction-policy", default=str(DEFAULT_REDACTION_POLICY_PATH)
    )
    parser.add_argument("--stage-a-final", default=str(DEFAULT_STAGE_A_FINAL_PATH))
    parser.add_argument("--max-scan-bytes", type=int, default=MAX_SCAN_BYTES)
    parser.add_argument(
        "--expected-target-count", type=int, default=EXPECTED_TARGET_COUNT
    )
    parser.add_argument(
        "--expected-source-reference-count",
        type=int,
        default=EXPECTED_SOURCE_REFERENCE_COUNT,
    )
    parser.add_argument(
        "--next-recommended-task",
        default="BC-11E-7B_FINAL_IMPORT_APPROVAL_REVIEW",
    )
    parser.add_argument(
        "--content-unique-review", default=str(DEFAULT_CONTENT_REVIEW_PATH)
    )
    parser.add_argument(
        "--provenance-review-queue", default=str(DEFAULT_PROVENANCE_QUEUE_PATH)
    )
    parser.add_argument(
        "--import-manifest-review", default=str(DEFAULT_MANIFEST_REVIEW_PATH)
    )
    parser.add_argument(
        "--import-target-final", default=str(DEFAULT_IMPORT_TARGET_FINAL_PATH)
    )
    parser.add_argument("--hash-results", default=str(DEFAULT_HASH_RESULTS_PATH))
    parser.add_argument(
        "--confirmed-duplicates", default=str(DEFAULT_CONFIRMED_DUPLICATES_PATH)
    )
    parser.add_argument(
        "--unique-content-candidates", default=str(DEFAULT_UNIQUE_CONTENT_PATH)
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--approved-root", action="append", default=[])
    parser.add_argument("--approval-token", default="")
    parser.add_argument("--worktree", default="UNKNOWN")
    parser.add_argument("--branch", default="UNKNOWN")
    parser.add_argument("--head-before", default="UNKNOWN")
    parser.add_argument("--head-after", default="UNKNOWN")
    parser.add_argument("--test-results", default="PENDING")
    parser.add_argument("--changed-files", default="UNKNOWN")
    parser.add_argument("--commit", default="NONE")
    parser.add_argument("--next-required-approval", default="")
    return parser


def _fixture_paths(args: argparse.Namespace) -> dict[str, str | Path]:
    return {
        "content_review": args.content_unique_review,
        "provenance_review": args.provenance_review_queue,
        "import_manifest": args.import_manifest_review,
        "import_target_final": args.import_target_final,
        "hash_results": args.hash_results,
        "confirmed_duplicates": args.confirmed_duplicates,
        "unique_content_candidates": args.unique_content_candidates,
    }


def _meta_from_args(args: argparse.Namespace) -> dict:
    return {
        "worktree": args.worktree,
        "branch": args.branch,
        "head_before": args.head_before,
        "head_after": args.head_after,
        "test_results": args.test_results,
        "changed_files": args.changed_files,
        "commit": args.commit,
        "next_required_approval": args.next_required_approval,
        "next_recommended_task": args.next_recommended_task,
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _run_stage_b(args: argparse.Namespace) -> int:
    approval_granted = bool(args.real_source_scan_approved) or (
        args.approval_token == REAL_SCAN_APPROVAL_TOKEN
    )

    try:
        scan_plan = load_input(args.secret_scan_plan)
        detection_policy = load_input(args.secret_detection_policy)
        provenance_plan = load_input(args.provenance_review_plan)
        redaction_policy = load_input(args.redaction_policy)
        hash_results = load_input(args.hash_results)
        manifest_review = load_input(args.import_manifest_review)
        stage_a_final = load_text_reference(args.stage_a_final)
    except InputError as exc:
        _emit(
            {
                "status": exc.code,
                "verdict": VERDICT_INPUT_BLOCKED,
                "path": exc.path,
                "detail": exc.detail,
            }
        )
        return 2

    try:
        result = build_stage_b(
            scan_plan=scan_plan,
            provenance_plan=provenance_plan,
            hash_results=hash_results,
            manifest_review=manifest_review,
            detection_policy=detection_policy,
            redaction_policy=redaction_policy,
            generated_at=args.generated_at or None,
            approval_granted=approval_granted,
            approved_roots=tuple(args.approved_root),
            max_bytes=args.max_scan_bytes,
            expected_targets=args.expected_target_count,
            expected_references=args.expected_source_reference_count,
        )
    except InputError as exc:
        _emit(
            {
                "status": exc.code,
                "verdict": VERDICT_INPUT_BLOCKED,
                "path": exc.path,
                "detail": exc.detail,
            }
        )
        return 2
    except SecurityBoundaryError as exc:
        _emit(
            {
                "status": "SECURITY_BOUNDARY_VIOLATION",
                "verdict": VERDICT_SECURITY_BLOCKED,
                "detail": exc.detail,
            }
        )
        return 3

    outputs = write_stage_b_outputs(
        result, output_dir=args.output_dir, meta=_meta_from_args(args)
    )
    _emit(
        {
            "status": INPUTS_VALID,
            "verdict": result["verdict"],
            "stage_a_final": stage_a_final,
            "counts": result["counts"],
            "safety": result["safety"],
            "outputs": outputs,
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stage_b:
        return _run_stage_b(args)
    try:
        fixtures = load_fixtures(_fixture_paths(args))
    except InputError as exc:
        print(
            json.dumps(
                {
                    "status": exc.code,
                    "verdict": VERDICT_INPUT_BLOCKED,
                    "path": exc.path,
                    "detail": exc.detail,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    try:
        result = build_stage_a(
            fixtures,
            expected=EXPECTED_BASELINE,
            generated_at=args.generated_at or None,
            approved_roots=tuple(args.approved_root),
            approval_token=args.approval_token or None,
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
    except SecurityBoundaryError as exc:
        print(
            json.dumps(
                {
                    "status": "SECURITY_BOUNDARY_VIOLATION",
                    "verdict": VERDICT_SECURITY_BLOCKED,
                    "detail": exc.detail,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3

    outputs = write_stage_a_outputs(
        result, output_dir=args.output_dir, meta=_meta_from_args(args)
    )
    print(
        json.dumps(
            {
                "status": INPUTS_VALID,
                "verdict": result["verdict"],
                "counts": result["counts"],
                "approval_gate": result["approval_gate"],
                "outputs": outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
