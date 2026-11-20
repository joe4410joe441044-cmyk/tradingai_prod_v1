"""BC-11E-7C operator review and redaction preparation.

This module turns the BC-11E-7B approval-review artifacts into an operator
decision package. It never re-reads a source report, never reads a secret
value, never imports a record, and never opens a database.

It only reads the BC-11E-7B JSON/Markdown artifacts, which are already
sanitized and contain no source body text and no secret values.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

TASK_ID = "TRADINGAI-WORK-BC-11E7C-REVIEW-AND-REDACTION-PREPARATION-1"
MODE = "OPERATOR_REVIEW_AND_REDACTION_PLANNING"

VERDICT_READY = "BC11E7C_REVIEW_AND_REDACTION_PREPARATION_READY"
VERDICT_INPUT_BLOCKED = "BC11E7C_INPUT_BLOCKED"
VERDICT_SECURITY_BLOCKED = "BC11E7C_SECURITY_BLOCKED"
VERDICT_TEST_FAILED = "BC11E7C_TEST_FAILED"

ELIGIBLE_SCHEMA_VERSION = "tradingai-bc11e7b-eligible-import-candidates/v1"
DISPOSITION_SCHEMA_VERSION = "tradingai-bc11e7b-secret-finding-disposition/v1"
REDACTION_SCHEMA_VERSION = "tradingai-bc11e7b-redaction-review-plan/v1"
MANUAL_SCHEMA_VERSION = "tradingai-bc11e7b-manual-review-queue/v1"
MANIFEST_SCHEMA_VERSION = "tradingai-bc11e7b-final-approval-manifest/v1"

MANUAL_PACKAGE_SCHEMA_VERSION = (
    "tradingai-bc11e7c-manual-review-package/v1"
)
REDACTION_APPROVAL_SCHEMA_VERSION = (
    "tradingai-bc11e7c-redaction-approval-plan/v1"
)
FINDING_REVIEW_SCHEMA_VERSION = (
    "tradingai-bc11e7c-finding-disposition-review/v1"
)
CANDIDATE_SUMMARY_SCHEMA_VERSION = (
    "tradingai-bc11e7c-import-candidate-summary/v1"
)

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_ELIGIBLE_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_ELIGIBLE_IMPORT_CANDIDATES.json"
)
DEFAULT_DISPOSITION_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_SECRET_FINDING_DISPOSITION.json"
)
DEFAULT_REDACTION_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_REDACTION_REVIEW_PLAN.json"
)
DEFAULT_MANUAL_PATH = DEFAULT_OUTPUT_DIR / "BC11E7B_MANUAL_REVIEW_QUEUE.json"
DEFAULT_MANIFEST_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_FINAL_APPROVAL_MANIFEST.json"
)
DEFAULT_APPROVAL_REQUEST_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_IMPORT_APPROVAL_REQUEST.md"
)
DEFAULT_FINAL_PATH = DEFAULT_OUTPUT_DIR / "BC11E7B_FINAL.md"

MANUAL_PACKAGE_JSON_NAME = "BC11E7C_MANUAL_REVIEW_PACKAGE.json"
REDACTION_APPROVAL_JSON_NAME = "BC11E7C_REDACTION_APPROVAL_PLAN.json"
FINDING_REVIEW_JSON_NAME = "BC11E7C_FINDING_DISPOSITION_REVIEW.json"
CANDIDATE_SUMMARY_JSON_NAME = "BC11E7C_IMPORT_CANDIDATE_SUMMARY.json"
OPERATOR_REQUEST_MD_NAME = "BC11E7C_OPERATOR_APPROVAL_REQUEST.md"
FINAL_MD_NAME = "BC11E7C_FINAL.md"

INPUTS_VALID = "INPUTS_VALID"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"
BLOCKED_EXISTING_OUTPUT = "BLOCKED_EXISTING_OUTPUT"

ELIGIBLE_CANDIDATE = "ELIGIBLE_CANDIDATE"
REDACTION_REQUIRED = "REDACTION_REQUIRED"
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"

IMPORT_DISPOSITION_IMPORT = "PROPOSED_IMPORT"
IMPORT_DISPOSITION_REDACTED_IMPORT = "PROPOSED_REDACTED_IMPORT"
IMPORT_DISPOSITION_MANUAL_REVIEW = "PROPOSED_MANUAL_REVIEW"

APPROVAL_PENDING = "PENDING_OPERATOR_APPROVAL"
DECISION_PENDING = "PENDING_OPERATOR_DECISION"
REVIEW_PENDING = "PENDING_OPERATOR_REVIEW"
REDACTION_STATUS_NOT_APPLIED = "NOT_APPLIED"

MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE = "POSSIBLE_FALSE_POSITIVE"
MANUAL_CLASS_REDACTION_RECOMMENDED = "REDACTION_RECOMMENDED"
MANUAL_CLASS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW = "IMPORT_EXCLUSION_REVIEW"

DISPOSITION_REDACTION_REQUIRED = "REDACTION_REQUIRED"
DISPOSITION_MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
DISPOSITION_POSSIBLE_FALSE_POSITIVE = "POSSIBLE_FALSE_POSITIVE"
DISPOSITION_UNRESOLVED = "UNRESOLVED"

SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")

SOURCE_TRUTH_CLASS = "AGENT_REPORTED"
AUTHORITY_SCOPE = "NONE"

EXPECTED_BASELINE = {
    "CONTENT_UNIQUE_COUNT": 491,
    "SOURCE_REFERENCE_COUNT": 6646,
    "ELIGIBLE_CANDIDATE_COUNT": 390,
    "REDACTION_REQUIRED_COUNT": 17,
    "MANUAL_REVIEW_REQUIRED_COUNT": 84,
    "SECRET_FINDING_COUNT": 154,
    "PROVENANCE_CONFIRMED_COUNT": 3,
    "PROVENANCE_UNKNOWN_COUNT": 488,
    "FINAL_APPROVAL_MANIFEST_COUNT": 491,
    "REDACTION_DISPOSITION_COUNT": 29,
    "MANUAL_DISPOSITION_COUNT": 125,
    "MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT": 79,
    "MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT": 5,
}

REQUIRED_ELIGIBLE_FIELDS = (
    "content_hash",
    "representative_source_id",
    "member_source_ids",
    "source_paths",
    "scan_status",
    "provenance_status",
    "import_disposition",
    "approved",
    "import_ready",
    "real_import_allowed",
)
REQUIRED_DISPOSITION_FIELDS = (
    "finding_id",
    "content_hash",
    "secret_type",
    "severity",
    "confidence",
    "review_disposition",
    "review_reason_code",
)
REQUIRED_REDACTION_FIELDS = (
    "content_hash",
    "representative_source_id",
    "finding_ids",
    "secret_types",
    "redaction_required",
    "redaction_status",
    "import_disposition",
)
REQUIRED_MANUAL_FIELDS = (
    "content_hash",
    "representative_source_id",
    "finding_ids",
    "review_classification",
    "review_reason",
    "recommended_action",
    "review_status",
)
REQUIRED_MANIFEST_FIELDS = (
    "content_hash",
    "representative_source_id",
    "member_source_ids",
    "source_paths",
    "provenance_status",
    "scan_status",
    "finding_count",
    "import_disposition",
    "approval_status",
    "approved",
    "import_ready",
    "real_import_allowed",
)

DECISION_OPTIONS = {
    MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE: [
        "CONFIRM_NOT_A_SECRET",
        "APPROVE_REDACTION",
        "EXCLUDE_FROM_IMPORT",
        "REQUEST_MORE_EVIDENCE",
    ],
    MANUAL_CLASS_REDACTION_RECOMMENDED: [
        "APPROVE_REDACTION",
        "CONFIRM_NOT_A_SECRET",
        "EXCLUDE_FROM_IMPORT",
        "REQUEST_MORE_EVIDENCE",
    ],
    MANUAL_CLASS_INSUFFICIENT_EVIDENCE: [
        "REQUEST_MORE_EVIDENCE",
        "APPROVE_REDACTION",
        "EXCLUDE_FROM_IMPORT",
    ],
    MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW: [
        "EXCLUDE_FROM_IMPORT",
        "APPROVE_REDACTION",
        "REQUEST_MORE_EVIDENCE",
    ],
}


class InputError(Exception):
    def __init__(self, code: str, path: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.detail = detail


class SecurityBoundaryError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _require(condition: bool, origin: str, detail: str) -> None:
    if not condition:
        raise InputError(BLOCKED_INVALID_INPUT, origin, detail)


def _require_fields(entries: list, fields: tuple[str, ...], origin: str) -> None:
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InputError(
                BLOCKED_INVALID_INPUT, origin, f"entry {index} is not an object"
            )
        for field in fields:
            if field not in entry:
                raise InputError(
                    BLOCKED_INVALID_INPUT,
                    origin,
                    f"entry {index} is missing {field}",
                )


def load_input(path: str | Path, origin: str) -> dict:
    target = Path(path)
    if not target.exists():
        raise InputError(BLOCKED_MISSING_INPUT, origin, str(target))
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(
            BLOCKED_INVALID_INPUT, origin, f"{target}: {type(exc).__name__}"
        ) from None
    if not isinstance(payload, dict):
        raise InputError(BLOCKED_INVALID_INPUT, origin, "root is not an object")
    return payload


def load_text_reference(path: str | Path, origin: str) -> dict:
    target = Path(path)
    if not target.exists():
        raise InputError(BLOCKED_MISSING_INPUT, origin, str(target))
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(
            BLOCKED_INVALID_INPUT, origin, f"{target}: {type(exc).__name__}"
        ) from None
    return {"path": str(target), "text": text}


def validate_shapes(inputs: dict) -> None:
    for key, schema, list_key in (
        ("eligible", ELIGIBLE_SCHEMA_VERSION, "candidates"),
        ("disposition", DISPOSITION_SCHEMA_VERSION, "findings"),
        ("redaction", REDACTION_SCHEMA_VERSION, "plan"),
        ("manual", MANUAL_SCHEMA_VERSION, "queue"),
        ("manifest", MANIFEST_SCHEMA_VERSION, "records"),
    ):
        payload = inputs[key]
        _require(
            payload.get("schema_version") == schema,
            key,
            "unexpected schema_version",
        )
        _require(isinstance(payload.get(list_key), list), key, "missing list")
        _require(
            int(payload.get("count", -1)) == len(payload[list_key]),
            key,
            "count does not match list length",
        )

    _require_fields(
        inputs["eligible"]["candidates"],
        REQUIRED_ELIGIBLE_FIELDS,
        "eligible",
    )
    _require_fields(
        inputs["disposition"]["findings"],
        REQUIRED_DISPOSITION_FIELDS,
        "disposition",
    )
    _require_fields(
        inputs["redaction"]["plan"],
        REQUIRED_REDACTION_FIELDS,
        "redaction",
    )
    _require_fields(
        inputs["manual"]["queue"],
        REQUIRED_MANUAL_FIELDS,
        "manual",
    )
    _require_fields(
        inputs["manifest"]["records"],
        REQUIRED_MANIFEST_FIELDS,
        "manifest",
    )

    _require(
        "VERDICT=BC11E7B_FINAL_IMPORT_APPROVAL_REVIEW_READY"
        in str(inputs["approval_request_text"].get("text", "")),
        "approval_request_text",
        "BC11E7B verdict missing",
    )
    _require(
        "VERDICT=BC11E7B_FINAL_IMPORT_APPROVAL_REVIEW_READY"
        in str(inputs["final_text"].get("text", "")),
        "final_text",
        "BC11E7B verdict missing",
    )


def _count_by(entries: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _mismatch(key: str, expected: Any, actual: Any, detail: str = "") -> dict:
    return {
        "key": key,
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def reconcile(inputs: dict, *, expected: dict | None = None) -> dict:
    baseline = dict(EXPECTED_BASELINE)
    if expected:
        baseline.update(expected)

    candidates = inputs["eligible"]["candidates"]
    findings = inputs["disposition"]["findings"]
    redaction_plan = inputs["redaction"]["plan"]
    manual_queue = inputs["manual"]["queue"]
    manifest = inputs["manifest"]["records"]

    mismatches: list[dict] = []

    def _check(key: str, expected_value: Any, actual_value: Any, detail: str = ""):
        if expected_value != actual_value:
            mismatches.append(_mismatch(key, expected_value, actual_value, detail))

    eligible_hashes = {str(entry["content_hash"]) for entry in candidates}
    redaction_hashes = {str(entry["content_hash"]) for entry in redaction_plan}
    manual_hashes = {str(entry["content_hash"]) for entry in manual_queue}
    manifest_hashes = {str(entry["content_hash"]) for entry in manifest}

    _check(
        "ELIGIBLE_CANDIDATE_COUNT",
        baseline["ELIGIBLE_CANDIDATE_COUNT"],
        len(candidates),
    )
    _check(
        "REDACTION_REQUIRED_COUNT",
        baseline["REDACTION_REQUIRED_COUNT"],
        len(redaction_plan),
    )
    _check(
        "MANUAL_REVIEW_REQUIRED_COUNT",
        baseline["MANUAL_REVIEW_REQUIRED_COUNT"],
        len(manual_queue),
    )
    _check(
        "SECRET_FINDING_COUNT",
        baseline["SECRET_FINDING_COUNT"],
        len(findings),
    )
    _check(
        "FINAL_APPROVAL_MANIFEST_COUNT",
        baseline["FINAL_APPROVAL_MANIFEST_COUNT"],
        len(manifest),
    )
    _check(
        "CATEGORY_RECONCILIATION",
        baseline["CONTENT_UNIQUE_COUNT"],
        len(candidates) + len(redaction_plan) + len(manual_queue),
    )
    _check(
        "MANIFEST_RECONCILIATION",
        baseline["CONTENT_UNIQUE_COUNT"],
        len(manifest),
    )
    _check(
        "CATEGORY_HASH_DISJOINT",
        True,
        not (
            (eligible_hashes & redaction_hashes)
            or (eligible_hashes & manual_hashes)
            or (redaction_hashes & manual_hashes)
        ),
    )
    _check(
        "CATEGORY_HASH_UNION",
        True,
        (eligible_hashes | redaction_hashes | manual_hashes) == manifest_hashes,
    )
    _check(
        "MANIFEST_HASH_UNIQUE",
        True,
        len(manifest_hashes) == len(manifest),
    )

    member_total = sum(len(entry["member_source_ids"]) for entry in manifest)
    path_total = sum(len(entry["source_paths"]) for entry in manifest)
    _check(
        "SOURCE_REFERENCE_COUNT",
        baseline["SOURCE_REFERENCE_COUNT"],
        member_total,
    )
    _check(
        "SOURCE_PATH_COUNT",
        baseline["SOURCE_REFERENCE_COUNT"],
        path_total,
    )

    provenance_counts = _count_by(manifest, "provenance_status")
    _check(
        "PROVENANCE_CONFIRMED_COUNT",
        baseline["PROVENANCE_CONFIRMED_COUNT"],
        provenance_counts.get("CONFIRMED", 0),
    )
    _check(
        "PROVENANCE_UNKNOWN_COUNT",
        baseline["PROVENANCE_UNKNOWN_COUNT"],
        provenance_counts.get("UNKNOWN", 0),
    )

    disposition_counts = _count_by(findings, "review_disposition")
    _check(
        "REDACTION_DISPOSITION_COUNT",
        baseline["REDACTION_DISPOSITION_COUNT"],
        disposition_counts.get(DISPOSITION_REDACTION_REQUIRED, 0),
    )
    _check(
        "MANUAL_DISPOSITION_COUNT",
        baseline["MANUAL_DISPOSITION_COUNT"],
        disposition_counts.get(DISPOSITION_MANUAL_REVIEW_REQUIRED, 0),
    )

    manual_class_counts = _count_by(manual_queue, "review_classification")
    _check(
        "MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT",
        baseline["MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT"],
        manual_class_counts.get(MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE, 0),
    )
    _check(
        "MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT",
        baseline["MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT"],
        manual_class_counts.get(MANUAL_CLASS_REDACTION_RECOMMENDED, 0),
    )

    finding_ids = [str(entry["finding_id"]) for entry in findings]
    _check("FINDING_ID_UNIQUE", True, len(finding_ids) == len(set(finding_ids)))

    disposition_redaction_ids = {
        str(entry["finding_id"])
        for entry in findings
        if entry["review_disposition"] == DISPOSITION_REDACTION_REQUIRED
    }
    plan_finding_ids = {
        str(finding_id)
        for entry in redaction_plan
        for finding_id in entry["finding_ids"]
    }
    _check(
        "REDACTION_PLAN_FINDING_SUBSET",
        True,
        plan_finding_ids <= disposition_redaction_ids,
    )

    for record in manifest:
        _check(
            f"MANIFEST_APPROVED_FALSE:{record['content_hash']}",
            False,
            record["approved"],
        )
        _check(
            f"MANIFEST_IMPORT_READY_FALSE:{record['content_hash']}",
            False,
            record["import_ready"],
        )
        _check(
            f"MANIFEST_REAL_IMPORT_FALSE:{record['content_hash']}",
            False,
            record["real_import_allowed"],
        )
        _check(
            f"MANIFEST_APPROVAL_PENDING:{record['content_hash']}",
            APPROVAL_PENDING,
            record["approval_status"],
        )

    return {
        "status": INPUTS_VALID if not mismatches else BLOCKED_INVALID_INPUT,
        "valid": not mismatches,
        "mismatches": mismatches,
        "counts": {
            "CONTENT_UNIQUE_COUNT": len(manifest),
            "SOURCE_REFERENCE_COUNT": member_total,
            "ELIGIBLE_CANDIDATE_COUNT": len(candidates),
            "REDACTION_REQUIRED_COUNT": len(redaction_plan),
            "MANUAL_REVIEW_REQUIRED_COUNT": len(manual_queue),
            "SECRET_FINDING_COUNT": len(findings),
            "PROVENANCE_CONFIRMED_COUNT": provenance_counts.get("CONFIRMED", 0),
            "PROVENANCE_UNKNOWN_COUNT": provenance_counts.get("UNKNOWN", 0),
            "REDACTION_DISPOSITION_COUNT": disposition_counts.get(
                DISPOSITION_REDACTION_REQUIRED, 0
            ),
            "MANUAL_DISPOSITION_COUNT": disposition_counts.get(
                DISPOSITION_MANUAL_REVIEW_REQUIRED, 0
            ),
            "MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT": (
                manual_class_counts.get(MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE, 0)
            ),
            "MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT": (
                manual_class_counts.get(MANUAL_CLASS_REDACTION_RECOMMENDED, 0)
            ),
        },
    }


def _decision_options_for(classification: str) -> list[str]:
    return list(
        DECISION_OPTIONS.get(
            classification,
            [
                "REQUEST_MORE_EVIDENCE",
                "APPROVE_REDACTION",
                "EXCLUDE_FROM_IMPORT",
            ],
        )
    )


def build_manual_package(inputs: dict) -> list[dict]:
    package: list[dict] = []
    for entry in sorted(
        inputs["manual"]["queue"], key=lambda item: str(item["content_hash"])
    ):
        classification = str(entry["review_classification"])
        package.append(
            {
                "content_hash": str(entry["content_hash"]),
                "representative_source_id": str(
                    entry["representative_source_id"]
                ),
                "member_source_ids": [
                    str(member) for member in entry.get("member_source_ids", [])
                ],
                "source_paths": [
                    str(path) for path in entry.get("source_paths", [])
                ],
                "finding_ids": [str(fid) for fid in entry["finding_ids"]],
                "severity_summary": dict(entry.get("severity_summary", {})),
                "review_classification": classification,
                "review_reason": str(entry["review_reason"]),
                "recommended_action": str(entry["recommended_action"]),
                "decision_options": _decision_options_for(classification),
                "required_operator_decision": "UNASSIGNED",
                "decision_status": DECISION_PENDING,
                "operator_note": "",
                "review_status": REVIEW_PENDING,
                "import_disposition": IMPORT_DISPOSITION_MANUAL_REVIEW,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "auto_excluded": False,
            }
        )
    return package


def build_redaction_approval_plan(inputs: dict) -> list[dict]:
    plan: list[dict] = []
    for entry in sorted(
        inputs["redaction"]["plan"], key=lambda item: str(item["content_hash"])
    ):
        plan.append(
            {
                "content_hash": str(entry["content_hash"]),
                "representative_source_id": str(
                    entry["representative_source_id"]
                ),
                "member_source_ids": [
                    str(member) for member in entry.get("member_source_ids", [])
                ],
                "source_paths": [
                    str(path) for path in entry.get("source_paths", [])
                ],
                "finding_ids": [str(fid) for fid in entry["finding_ids"]],
                "secret_types": [str(item) for item in entry["secret_types"]],
                "severity_summary": dict(entry.get("severity_summary", {})),
                "redaction_method": "OPERATOR_APPROVED_PLACEHOLDER_REPLACEMENT",
                "target_scope": "MATCHED_SECRET_SPANS_ONLY",
                "requires_rescan_before_execution": True,
                "execution_task_required": True,
                "redaction_required": True,
                "redaction_status": REDACTION_STATUS_NOT_APPLIED,
                "redaction_applied": False,
                "original_file_modified": False,
                "import_copy_generated": False,
                "approval_status": APPROVAL_PENDING,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "import_disposition": IMPORT_DISPOSITION_REDACTED_IMPORT,
            }
        )
    return plan


def build_finding_review(inputs: dict) -> list[dict]:
    review: list[dict] = []
    for entry in sorted(
        inputs["disposition"]["findings"],
        key=lambda item: (str(item["content_hash"]), str(item["finding_id"])),
    ):
        review.append(
            {
                "finding_id": str(entry["finding_id"]),
                "content_hash": str(entry["content_hash"]),
                "secret_type": str(entry["secret_type"]),
                "severity": str(entry["severity"]),
                "confidence": str(entry["confidence"]),
                "review_disposition": str(entry["review_disposition"]),
                "review_reason_code": str(entry["review_reason_code"]),
                "operator_decision_status": DECISION_PENDING,
                "operator_disposition": "UNASSIGNED",
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "value_stored": False,
                "context_stored": False,
            }
        )
    return review


def _import_disposition_counts(records: list[dict]) -> dict[str, int]:
    return _count_by(records, "import_disposition")


def build_candidate_summary(inputs: dict) -> dict:
    manifest = inputs["manifest"]["records"]
    records = [
        {
            "content_hash": str(entry["content_hash"]),
            "representative_source_id": str(entry["representative_source_id"]),
            "scan_status": str(entry["scan_status"]),
            "finding_count": int(entry["finding_count"]),
            "provenance_status": str(entry["provenance_status"]),
            "import_disposition": str(entry["import_disposition"]),
            "approval_status": str(entry["approval_status"]),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
        }
        for entry in sorted(manifest, key=lambda item: str(item["content_hash"]))
    ]
    return {
        "count": len(records),
        "by_import_disposition": _import_disposition_counts(records),
        "by_scan_status": _count_by(records, "scan_status"),
        "by_provenance_status": _count_by(records, "provenance_status"),
        "records": records,
    }


def build_result(
    inputs: dict,
    *,
    generated_at: str | None = None,
    expected: dict | None = None,
) -> dict:
    timestamp = generated_at or _now_iso()
    validate_shapes(inputs)
    reconciliation = reconcile(inputs, expected=expected)
    if not reconciliation["valid"]:
        raise InputError(
            BLOCKED_INVALID_INPUT,
            "reconciliation",
            "; ".join(item["key"] for item in reconciliation["mismatches"][:10]),
        )

    baseline = dict(EXPECTED_BASELINE)
    if expected:
        baseline.update(expected)

    manual_package = build_manual_package(inputs)
    redaction_approval = build_redaction_approval_plan(inputs)
    finding_review = build_finding_review(inputs)
    candidate_summary = build_candidate_summary(inputs)

    _require(
        len(manual_package) == baseline["MANUAL_REVIEW_REQUIRED_COUNT"],
        "manual_package",
        "manual package count mismatch",
    )
    _require(
        len(redaction_approval) == baseline["REDACTION_REQUIRED_COUNT"],
        "redaction_approval",
        "redaction approval count mismatch",
    )
    _require(
        len(finding_review) == baseline["SECRET_FINDING_COUNT"],
        "finding_review",
        "finding review count mismatch",
    )
    _require(
        candidate_summary["count"] == baseline["CONTENT_UNIQUE_COUNT"],
        "candidate_summary",
        "candidate summary count mismatch",
    )

    for collection in (manual_package, redaction_approval, finding_review):
        if any(entry["approved"] for entry in collection):
            raise SecurityBoundaryError("approved must remain false")
        if any(entry["import_ready"] for entry in collection):
            raise SecurityBoundaryError("import_ready must remain false")
        if any(entry["real_import_allowed"] for entry in collection):
            raise SecurityBoundaryError("real_import_allowed must remain false")
    if any(record["approved"] for record in candidate_summary["records"]):
        raise SecurityBoundaryError("candidate approved must remain false")

    counts = dict(reconciliation["counts"])
    counts.update(
        {
            "MANUAL_PACKAGE_COUNT": len(manual_package),
            "REDACTION_APPROVAL_COUNT": len(redaction_approval),
            "FINDING_REVIEW_COUNT": len(finding_review),
            "IMPORT_CANDIDATE_SUMMARY_COUNT": candidate_summary["count"],
        }
    )

    acceptance = {
        "INPUTS_VALID": True,
        "CONTENT_UNIQUE_COUNT": counts["CONTENT_UNIQUE_COUNT"],
        "SOURCE_REFERENCE_COUNT": counts["SOURCE_REFERENCE_COUNT"],
        "ELIGIBLE_CANDIDATE_COUNT": counts["ELIGIBLE_CANDIDATE_COUNT"],
        "REDACTION_REQUIRED_COUNT": counts["REDACTION_REQUIRED_COUNT"],
        "MANUAL_REVIEW_REQUIRED_COUNT": counts["MANUAL_REVIEW_REQUIRED_COUNT"],
        "SECRET_FINDING_COUNT": counts["SECRET_FINDING_COUNT"],
        "PROVENANCE_CONFIRMED_COUNT": counts["PROVENANCE_CONFIRMED_COUNT"],
        "PROVENANCE_UNKNOWN_COUNT": counts["PROVENANCE_UNKNOWN_COUNT"],
        "MANUAL_PACKAGE_COUNT": counts["MANUAL_PACKAGE_COUNT"],
        "REDACTION_APPROVAL_COUNT": counts["REDACTION_APPROVAL_COUNT"],
        "FINDING_REVIEW_COUNT": counts["FINDING_REVIEW_COUNT"],
        "IMPORT_CANDIDATE_SUMMARY_COUNT": counts["IMPORT_CANDIDATE_SUMMARY_COUNT"],
        "ALL_APPROVED_FALSE": True,
        "ALL_IMPORT_READY_FALSE": True,
        "ALL_REAL_IMPORT_ALLOWED_FALSE": True,
        "OPERATOR_APPROVAL_REQUEST_CREATED": True,
        "NO_SECRET_VALUES_EXPORTED": True,
        "NO_REAL_IMPORT": True,
        "NO_PRODUCTION_WRITE": True,
        "SOURCE_REPORT_REREAD": False,
    }

    return {
        "task_id": TASK_ID,
        "verdict": VERDICT_READY,
        "mode": MODE,
        "generated_at": timestamp,
        "reconciliation": reconciliation,
        "counts": counts,
        "acceptance": acceptance,
        "manual_review_package": manual_package,
        "redaction_approval_plan": redaction_approval,
        "finding_disposition_review": finding_review,
        "import_candidate_summary": candidate_summary,
        "safety": {
            "source_files_read": False,
            "source_body_stored": False,
            "secret_values_stored": False,
            "secret_value_hash_stored": False,
            "real_import_executed": False,
            "production_database_opened": False,
            "production_database_written": False,
            "database_created": False,
            "database_migrated": False,
            "canonical_written": False,
            "git_push": False,
            "production_restart": False,
        },
    }


def _payload_header(schema_version: str, result: dict, **extra: Any) -> dict:
    payload = {
        "task_id": result["task_id"],
        "schema_version": schema_version,
        "mode": result["mode"],
        "generated_at": result["generated_at"],
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "real_import_executed": False,
        "secret_values_stored": False,
        "source_body_stored": False,
        "counts": dict(result["counts"]),
    }
    payload.update(extra)
    return payload


def build_outputs(result: dict) -> dict[str, dict]:
    return {
        "manual_review_package": _payload_header(
            MANUAL_PACKAGE_SCHEMA_VERSION,
            result,
            count=len(result["manual_review_package"]),
            package=result["manual_review_package"],
        ),
        "redaction_approval_plan": _payload_header(
            REDACTION_APPROVAL_SCHEMA_VERSION,
            result,
            count=len(result["redaction_approval_plan"]),
            plan=result["redaction_approval_plan"],
        ),
        "finding_disposition_review": _payload_header(
            FINDING_REVIEW_SCHEMA_VERSION,
            result,
            count=len(result["finding_disposition_review"]),
            findings=result["finding_disposition_review"],
        ),
        "import_candidate_summary": _payload_header(
            CANDIDATE_SUMMARY_SCHEMA_VERSION,
            result,
            count=result["import_candidate_summary"]["count"],
            summary=result["import_candidate_summary"],
        ),
    }


def render_operator_request(result: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    counts = result["counts"]
    lines = [
        "# BC-11E-7C Operator Approval Request",
        "",
        f"TASK_ID={result['task_id']}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "REAL_IMPORT_APPROVED=NO",
        "PRODUCTION_WRITE_APPROVED=NO",
        "GIT_PUSH_APPROVED=NO",
        "",
        "## 1. Inputs",
        "",
        "This package reuses the BC-11E-7B artifacts only. No source report was",
        "re-read and no secret value was read or written.",
        "",
        f"- CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"- SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"- ELIGIBLE_CANDIDATE_COUNT={counts['ELIGIBLE_CANDIDATE_COUNT']}",
        f"- REDACTION_REQUIRED_COUNT={counts['REDACTION_REQUIRED_COUNT']}",
        f"- MANUAL_REVIEW_REQUIRED_COUNT={counts['MANUAL_REVIEW_REQUIRED_COUNT']}",
        f"- SECRET_FINDING_COUNT={counts['SECRET_FINDING_COUNT']}",
        "",
        "## 2. Manual review package",
        "",
        f"- MANUAL_PACKAGE_COUNT={counts['MANUAL_PACKAGE_COUNT']}",
        f"- POSSIBLE_FALSE_POSITIVE candidates: "
        f"{counts['MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT']}",
        f"- REDACTION_RECOMMENDED candidates: "
        f"{counts['MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT']}",
        "",
        "Every item remains PENDING_OPERATOR_DECISION. No item is approved,",
        "excluded, or declared a false positive automatically.",
        "",
        "## 3. Redaction approval plan",
        "",
        f"- REDACTION_APPROVAL_COUNT={counts['REDACTION_APPROVAL_COUNT']}",
        "",
        "The plan is metadata only. It does not modify any source file, does not",
        "generate an import copy, and requires a separate approved execution task.",
        "",
        "## 4. Finding disposition review",
        "",
        f"- FINDING_REVIEW_COUNT={counts['FINDING_REVIEW_COUNT']}",
        f"- REDACTION_REQUIRED findings: "
        f"{counts['REDACTION_DISPOSITION_COUNT']}",
        f"- MANUAL_REVIEW_REQUIRED findings: "
        f"{counts['MANUAL_DISPOSITION_COUNT']}",
        "",
        "## 5. Import candidate summary",
        "",
        f"- IMPORT_CANDIDATE_SUMMARY_COUNT="
        f"{counts['IMPORT_CANDIDATE_SUMMARY_COUNT']}",
        f"- PROVENANCE_CONFIRMED_COUNT={counts['PROVENANCE_CONFIRMED_COUNT']}",
        f"- PROVENANCE_UNKNOWN_COUNT={counts['PROVENANCE_UNKNOWN_COUNT']}",
        "",
        "All candidates remain approved=false, import_ready=false, and",
        "real_import_allowed=false.",
        "",
        "## 6. Operator decisions required",
        "",
        "1. Resolve every manual review item without auto-exclusion.",
        "2. Approve or reject the redaction approval plan.",
        "3. Confirm the final 491-record manifest remains pending.",
        "4. Authorize a separate redacted-copy generation task if approved.",
        "5. Authorize a separate import execution task if approved.",
        "",
        "## 7. Safety boundaries",
        "",
        "- REAL_IMPORT_EXECUTED=NO",
        "- PRODUCTION_DB_WRITE=NO",
        "- DATABASE_CREATED=NO",
        "- DATABASE_MIGRATED=NO",
        "- SOURCE_FILE_MODIFIED=NO",
        "- SECRET_VALUE_EXPORTED=NO",
        "- GIT_PUSH=NO",
        "",
        "ALL_APPROVED_FALSE=TRUE",
        "ALL_IMPORT_READY_FALSE=TRUE",
        "ALL_REAL_IMPORT_ALLOWED_FALSE=TRUE",
        "",
    ]
    return "\n".join(lines)


def render_final(result: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    counts = result["counts"]
    lines = [
        "# BC-11E-7C Review and Redaction Preparation",
        "",
        f"TASK_ID={result['task_id']}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "",
        f"CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"ELIGIBLE_CANDIDATE_COUNT={counts['ELIGIBLE_CANDIDATE_COUNT']}",
        f"REDACTION_REQUIRED_COUNT={counts['REDACTION_REQUIRED_COUNT']}",
        f"MANUAL_REVIEW_REQUIRED_COUNT={counts['MANUAL_REVIEW_REQUIRED_COUNT']}",
        f"SECRET_FINDING_COUNT={counts['SECRET_FINDING_COUNT']}",
        f"PROVENANCE_CONFIRMED_COUNT={counts['PROVENANCE_CONFIRMED_COUNT']}",
        f"PROVENANCE_UNKNOWN_COUNT={counts['PROVENANCE_UNKNOWN_COUNT']}",
        f"MANUAL_PACKAGE_COUNT={counts['MANUAL_PACKAGE_COUNT']}",
        f"REDACTION_APPROVAL_COUNT={counts['REDACTION_APPROVAL_COUNT']}",
        f"FINDING_REVIEW_COUNT={counts['FINDING_REVIEW_COUNT']}",
        f"IMPORT_CANDIDATE_SUMMARY_COUNT="
        f"{counts['IMPORT_CANDIDATE_SUMMARY_COUNT']}",
        "OPERATOR_APPROVAL_REQUEST_CREATED=YES",
        "",
        "ALL_APPROVED_FALSE=TRUE",
        "ALL_IMPORT_READY_FALSE=TRUE",
        "ALL_REAL_IMPORT_ALLOWED_FALSE=TRUE",
        "",
        "TEST_RESULTS=" + meta.get("test_results", "PENDING"),
        "CHANGED_FILES=" + meta.get("changed_files", "UNKNOWN"),
        "COMMIT=" + meta.get("commit", "NONE"),
        "BC11E7B_COMMIT=" + meta.get("bc11e7b_commit", "UNKNOWN"),
        "PRODUCTION_DB_UNCHANGED=YES",
        "CANONICAL_UNCHANGED=YES",
        "REAL_IMPORT_EXECUTED=NO",
        "SOURCE_REPORT_REREAD=NO",
        "GIT_PUSH=NO",
        "PRODUCTION_RESTART=NO",
        "",
        "NEXT_RECOMMENDED_TASK="
        + meta.get(
            "next_recommended_task",
            "BC-11E-7D_OPERATOR_DECISION_APPLICATION",
        ),
        "",
    ]
    return "\n".join(lines)


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


def write_outputs(
    result: dict,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    meta: dict | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    meta = meta or {}
    paths = {
        "manual_review_package": target / MANUAL_PACKAGE_JSON_NAME,
        "redaction_approval_plan": target / REDACTION_APPROVAL_JSON_NAME,
        "finding_disposition_review": target / FINDING_REVIEW_JSON_NAME,
        "import_candidate_summary": target / CANDIDATE_SUMMARY_JSON_NAME,
        "operator_approval_request": target / OPERATOR_REQUEST_MD_NAME,
        "final": target / FINAL_MD_NAME,
    }
    if not overwrite:
        existing = [str(path) for path in paths.values() if path.exists()]
        if existing:
            raise InputError(
                BLOCKED_EXISTING_OUTPUT,
                "outputs",
                "refusing to overwrite: " + ", ".join(existing),
            )

    payloads = build_outputs(result)
    payloads["operator_approval_request"] = render_operator_request(result, meta)
    payloads["final"] = render_final(result, meta)

    for key, path in paths.items():
        payload = payloads[key]
        text = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        _write_private_text(path, text)
    return {key: str(path) for key, path in paths.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eligible", default=str(DEFAULT_ELIGIBLE_PATH))
    parser.add_argument("--disposition", default=str(DEFAULT_DISPOSITION_PATH))
    parser.add_argument("--redaction", default=str(DEFAULT_REDACTION_PATH))
    parser.add_argument("--manual", default=str(DEFAULT_MANUAL_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument(
        "--approval-request",
        default=str(DEFAULT_APPROVAL_REQUEST_PATH),
    )
    parser.add_argument("--bc11e7b-final", default=str(DEFAULT_FINAL_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--worktree", default="UNKNOWN")
    parser.add_argument("--branch", default="UNKNOWN")
    parser.add_argument("--head-before", default="UNKNOWN")
    parser.add_argument("--head-after", default="UNKNOWN")
    parser.add_argument("--test-results", default="PENDING")
    parser.add_argument("--changed-files", default="UNKNOWN")
    parser.add_argument("--commit", default="NONE")
    parser.add_argument("--bc11e7b-commit", default="UNKNOWN")
    parser.add_argument(
        "--next-recommended-task",
        default="BC-11E-7D_OPERATOR_DECISION_APPLICATION",
    )
    return parser


def _meta_from_args(args: argparse.Namespace) -> dict:
    return {
        "worktree": args.worktree,
        "branch": args.branch,
        "head_before": args.head_before,
        "head_after": args.head_after,
        "test_results": args.test_results,
        "changed_files": args.changed_files,
        "commit": args.commit,
        "bc11e7b_commit": args.bc11e7b_commit,
        "next_recommended_task": args.next_recommended_task,
    }


def load_inputs(paths: dict[str, str | Path]) -> dict:
    return {
        "eligible": load_input(paths["eligible"], "eligible"),
        "disposition": load_input(paths["disposition"], "disposition"),
        "redaction": load_input(paths["redaction"], "redaction"),
        "manual": load_input(paths["manual"], "manual"),
        "manifest": load_input(paths["manifest"], "manifest"),
        "approval_request_text": load_text_reference(
            paths["approval_request"], "approval_request_text"
        ),
        "final_text": load_text_reference(
            paths["bc11e7b_final"], "final_text"
        ),
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = {
        "eligible": args.eligible,
        "disposition": args.disposition,
        "redaction": args.redaction,
        "manual": args.manual,
        "manifest": args.manifest,
        "approval_request": args.approval_request,
        "bc11e7b_final": args.bc11e7b_final,
    }
    try:
        inputs = load_inputs(paths)
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
        result = build_result(
            inputs, generated_at=args.generated_at or None
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

    try:
        outputs = write_outputs(
            result,
            output_dir=args.output_dir,
            meta=_meta_from_args(args),
            overwrite=args.overwrite,
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

    _emit(
        {
            "status": INPUTS_VALID,
            "verdict": result["verdict"],
            "counts": result["counts"],
            "acceptance": result["acceptance"],
            "outputs": outputs,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
