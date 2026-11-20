"""BC-11E-7D priority 390 approval preparation.

This module is a read-only preparation packager. It splits the existing
BC-11E-7B 491-record approval manifest into:

* 390 priority candidates (``ELIGIBLE_CANDIDATE`` / no findings);
* 101 deferred candidates (17 redaction, 84 manual review).

It reuses the BC-11E-7B/7C schemas and validation helpers. It never re-reads a
source report, never reads or writes a secret value, never imports a record, and
never opens a database.

Hard safety boundaries:

* no source report is opened or modified;
* no secret value, partial secret value, surrounding body text, or secret-value
  hash is read or written here;
* no database is opened for writing, no schema is created, no migration runs;
* no record is imported;
* every approval/import flag stays ``false``;
* the production/canonical tree is never written.

The work order names three BC-11E-7C artifacts that are emitted by
``bc11e_review_and_redaction_preparation.py`` under slightly different names:

* ``BC11E7C_IMPORT_DISPOSITION_MANIFEST.json`` ->
  ``BC11E7C_IMPORT_CANDIDATE_SUMMARY.json``
* ``BC11E7C_MANUAL_REVIEW_PRIORITY_QUEUE.json`` ->
  ``BC11E7C_MANUAL_REVIEW_PACKAGE.json``
* ``BC11E7C_SECRET_FINDING_REVIEW.json`` ->
  ``BC11E7C_FINDING_DISPOSITION_REVIEW.json``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_review_and_redaction_preparation as review_prep  # noqa: E402


TASK_ID = "TRADINGAI-WORK-BC-11E7D-390-PRIORITY-APPROVAL-1"
MODE = "PRIORITY_APPROVAL_PREPARATION"

VERDICT_READY = "BC11E7D_PRIORITY_390_APPROVAL_PREPARATION_READY"
VERDICT_INPUT_BLOCKED = "BC11E7D_INPUT_BLOCKED"
VERDICT_SECURITY_BLOCKED = "BC11E7D_SECURITY_BLOCKED"
VERDICT_TEST_FAILED = "BC11E7D_TEST_FAILED"

PRIORITY_MANIFEST_SCHEMA_VERSION = (
    "tradingai-bc11e7d-priority-390-manifest/v1"
)
DEFERRED_MANIFEST_SCHEMA_VERSION = (
    "tradingai-bc11e7d-deferred-101-manifest/v1"
)
RECONCILIATION_SCHEMA_VERSION = "tradingai-bc11e7d-reconciliation/v1"
SAFETY_REVIEW_SCHEMA_VERSION = (
    "tradingai-bc11e7d-pre-import-safety-review/v1"
)

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_MANIFEST_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_FINAL_APPROVAL_MANIFEST.json"
)
DEFAULT_ELIGIBLE_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7B_ELIGIBLE_IMPORT_CANDIDATES.json"
)
DEFAULT_CANDIDATE_SUMMARY_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7C_IMPORT_CANDIDATE_SUMMARY.json"
)
DEFAULT_MANUAL_PACKAGE_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7C_MANUAL_REVIEW_PACKAGE.json"
)
DEFAULT_REDACTION_PLAN_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7C_REDACTION_APPROVAL_PLAN.json"
)
DEFAULT_FINDING_REVIEW_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7C_FINDING_DISPOSITION_REVIEW.json"
)
DEFAULT_OPERATOR_REQUEST_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7C_OPERATOR_APPROVAL_REQUEST.md"
)

PRIORITY_JSON_NAME = "BC11E7D_PRIORITY_390_MANIFEST.json"
DEFERRED_JSON_NAME = "BC11E7D_DEFERRED_101_MANIFEST.json"
RECONCILIATION_JSON_NAME = "BC11E7D_RECONCILIATION.json"
SAFETY_JSON_NAME = "BC11E7D_PRE_IMPORT_SAFETY_REVIEW.json"
APPROVAL_REQUEST_MD_NAME = "BC11E7D_PRIORITY_APPROVAL_REQUEST.md"
FINAL_MD_NAME = "BC11E7D_FINAL.md"

InputError = review_prep.InputError
SecurityBoundaryError = review_prep.SecurityBoundaryError

INPUTS_VALID = review_prep.INPUTS_VALID
BLOCKED_MISSING_INPUT = review_prep.BLOCKED_MISSING_INPUT
BLOCKED_INVALID_INPUT = review_prep.BLOCKED_INVALID_INPUT
BLOCKED_EXISTING_OUTPUT = review_prep.BLOCKED_EXISTING_OUTPUT

MANIFEST_SCHEMA_VERSION = review_prep.MANIFEST_SCHEMA_VERSION
ELIGIBLE_SCHEMA_VERSION = review_prep.ELIGIBLE_SCHEMA_VERSION
CANDIDATE_SUMMARY_SCHEMA_VERSION = (
    review_prep.CANDIDATE_SUMMARY_SCHEMA_VERSION
)
MANUAL_PACKAGE_SCHEMA_VERSION = review_prep.MANUAL_PACKAGE_SCHEMA_VERSION
REDACTION_APPROVAL_SCHEMA_VERSION = (
    review_prep.REDACTION_APPROVAL_SCHEMA_VERSION
)
FINDING_REVIEW_SCHEMA_VERSION = review_prep.FINDING_REVIEW_SCHEMA_VERSION

ELIGIBLE_CANDIDATE = review_prep.ELIGIBLE_CANDIDATE
REDACTION_REQUIRED = review_prep.REDACTION_REQUIRED
MANUAL_REVIEW_REQUIRED = review_prep.MANUAL_REVIEW_REQUIRED
SCAN_COMPLETED_NO_FINDINGS = "SCAN_COMPLETED_NO_FINDINGS"
APPROVAL_PENDING = review_prep.APPROVAL_PENDING
SOURCE_TRUTH_CLASS = review_prep.SOURCE_TRUTH_CLASS
AUTHORITY_SCOPE = review_prep.AUTHORITY_SCOPE

PRIORITY_GROUP = "PRIORITY_390"
DEFERRED_REDACTION_GROUP = "DEFERRED_REDACTION"
DEFERRED_MANUAL_REVIEW_GROUP = "DEFERRED_MANUAL_REVIEW"
PRIORITY_REVIEW_REASON = (
    "SCAN_COMPLETED_NO_FINDINGS_PENDING_OPERATOR_APPROVAL"
)
REDACTION_REVIEW_REASON = "REDACTION_REQUIRED_BEFORE_IMPORT"
SAFETY_NOTE = (
    "SCAN_COMPLETED_NO_FINDINGS does not prove that no secret exists; "
    "additional operator approval is required before any import."
)

EXPECTED_BASELINE = {
    "TOTAL_CONTENT_UNIQUE": 491,
    "TOTAL_SOURCE_REFERENCES": 6646,
    "PRIORITY_CANDIDATES": 390,
    "DEFERRED_CANDIDATES": 101,
    "REDACTION_REQUIRED": 17,
    "MANUAL_REVIEW_REQUIRED": 84,
    "SECRET_FINDINGS": 154,
    "HIGH_FINDINGS": 29,
    "MEDIUM_FINDINGS": 125,
    "PROVENANCE_CONFIRMED": 3,
    "PROVENANCE_UNKNOWN": 488,
}

REQUIRED_PRIORITY_FIELDS = (
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

REQUIRED_DEFERRED_SOURCE_FIELDS = (
    "content_hash",
    "representative_source_id",
    "finding_ids",
)

HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _baseline(expected: dict | None = None) -> dict:
    baseline = dict(EXPECTED_BASELINE)
    if expected:
        baseline.update(expected)
    return baseline


def load_inputs(paths: dict[str, str | Path]) -> dict:
    return {
        "manifest": review_prep.load_input(paths["manifest"], "manifest"),
        "eligible": review_prep.load_input(paths["eligible"], "eligible"),
        "candidate_summary": review_prep.load_input(
            paths["candidate_summary"], "candidate_summary"
        ),
        "manual_package": review_prep.load_input(
            paths["manual_package"], "manual_package"
        ),
        "redaction_plan": review_prep.load_input(
            paths["redaction_plan"], "redaction_plan"
        ),
        "finding_review": review_prep.load_input(
            paths["finding_review"], "finding_review"
        ),
        "operator_request_text": review_prep.load_text_reference(
            paths["operator_request"], "operator_request_text"
        ),
    }


def validate_shapes(inputs: dict, *, expected: dict | None = None) -> None:
    baseline = _baseline(expected)

    for key, schema, list_key in (
        ("manifest", MANIFEST_SCHEMA_VERSION, "records"),
        ("eligible", ELIGIBLE_SCHEMA_VERSION, "candidates"),
        ("manual_package", MANUAL_PACKAGE_SCHEMA_VERSION, "package"),
        ("redaction_plan", REDACTION_APPROVAL_SCHEMA_VERSION, "plan"),
        ("finding_review", FINDING_REVIEW_SCHEMA_VERSION, "findings"),
    ):
        payload = inputs[key]
        review_prep._require(
            isinstance(payload, dict), key, "root is not an object"
        )
        review_prep._require(
            payload.get("schema_version") == schema,
            key,
            "unexpected schema_version",
        )
        review_prep._require(
            isinstance(payload.get(list_key), list), key, "missing list"
        )
        review_prep._require(
            int(payload.get("count", -1)) == len(payload[list_key]),
            key,
            "count does not match list length",
        )

    candidate_summary = inputs["candidate_summary"]
    review_prep._require(
        candidate_summary.get("schema_version")
        == CANDIDATE_SUMMARY_SCHEMA_VERSION,
        "candidate_summary",
        "unexpected schema_version",
    )
    summary = candidate_summary.get("summary")
    review_prep._require(
        isinstance(summary, dict), "candidate_summary", "missing summary"
    )
    review_prep._require(
        isinstance(summary.get("records"), list),
        "candidate_summary",
        "missing summary records",
    )
    review_prep._require(
        int(summary.get("count", -1)) == len(summary["records"]),
        "candidate_summary",
        "summary count does not match records",
    )
    review_prep._require(
        int(candidate_summary.get("count", -1))
        == baseline["TOTAL_CONTENT_UNIQUE"],
        "candidate_summary",
        "candidate summary count mismatch",
    )

    review_prep._require_fields(
        inputs["manifest"]["records"],
        review_prep.REQUIRED_MANIFEST_FIELDS,
        "manifest",
    )
    review_prep._require_fields(
        inputs["eligible"]["candidates"],
        review_prep.REQUIRED_ELIGIBLE_FIELDS,
        "eligible",
    )
    review_prep._require_fields(
        inputs["manual_package"]["package"],
        review_prep.REQUIRED_MANUAL_FIELDS,
        "manual_package",
    )
    review_prep._require_fields(
        inputs["redaction_plan"]["plan"],
        review_prep.REQUIRED_REDACTION_FIELDS,
        "redaction_plan",
    )
    review_prep._require_fields(
        inputs["finding_review"]["findings"],
        review_prep.REQUIRED_DISPOSITION_FIELDS,
        "finding_review",
    )

    review_prep._require(
        "VERDICT=BC11E7C_REVIEW_AND_REDACTION_PREPARATION_READY"
        in str(inputs["operator_request_text"].get("text", "")),
        "operator_request_text",
        "BC11E7C verdict missing",
    )

    records = inputs["manifest"]["records"]
    eligible = inputs["eligible"]["candidates"]
    manual = inputs["manual_package"]["package"]
    redaction = inputs["redaction_plan"]["plan"]
    findings = inputs["finding_review"]["findings"]

    review_prep._require(
        len(records) == baseline["TOTAL_CONTENT_UNIQUE"],
        "manifest",
        "content unique count mismatch",
    )
    review_prep._require(
        sum(len(record["member_source_ids"]) for record in records)
        == baseline["TOTAL_SOURCE_REFERENCES"],
        "manifest",
        "source reference count mismatch",
    )
    review_prep._require(
        len(eligible) == baseline["PRIORITY_CANDIDATES"],
        "eligible",
        "eligible candidate count mismatch",
    )
    review_prep._require(
        len(manual) == baseline["MANUAL_REVIEW_REQUIRED"],
        "manual_package",
        "manual review count mismatch",
    )
    review_prep._require(
        len(redaction) == baseline["REDACTION_REQUIRED"],
        "redaction_plan",
        "redaction count mismatch",
    )
    review_prep._require(
        len(findings) == baseline["SECRET_FINDINGS"],
        "finding_review",
        "secret finding count mismatch",
    )

    severity_counts = review_prep._count_by(findings, "severity")
    review_prep._require(
        severity_counts.get("HIGH", 0) == baseline["HIGH_FINDINGS"],
        "finding_review",
        "high finding count mismatch",
    )
    review_prep._require(
        severity_counts.get("MEDIUM", 0) == baseline["MEDIUM_FINDINGS"],
        "finding_review",
        "medium finding count mismatch",
    )

    provenance_counts = review_prep._count_by(records, "provenance_status")
    review_prep._require(
        provenance_counts.get("CONFIRMED", 0)
        == baseline["PROVENANCE_CONFIRMED"],
        "manifest",
        "confirmed provenance count mismatch",
    )
    review_prep._require(
        provenance_counts.get("UNKNOWN", 0)
        == baseline["PROVENANCE_UNKNOWN"],
        "manifest",
        "unknown provenance count mismatch",
    )

    for key, collection in (
        ("manifest", records),
        ("eligible", eligible),
        ("manual_package", manual),
        ("redaction_plan", redaction),
        ("finding_review", findings),
    ):
        review_prep._require(
            all(
                entry.get("approved") is False
                and entry.get("import_ready") is False
                and entry.get("real_import_allowed") is False
                for entry in collection
            ),
            key,
            "approval flags must remain false",
        )

    review_prep._require(
        all(
            str(record.get("source_truth_class")) == SOURCE_TRUTH_CLASS
            and str(record.get("authority_scope")) == AUTHORITY_SCOPE
            and record.get("historical_record") is True
            and record.get("historical_runtime_authority") is False
            for record in records
        ),
        "manifest",
        "historical authority must remain non-escalated",
    )


def is_priority_record(record: dict) -> bool:
    return (
        record.get("import_eligibility") == ELIGIBLE_CANDIDATE
        and record.get("scan_status") == SCAN_COMPLETED_NO_FINDINGS
        and int(record.get("finding_count", -1)) == 0
        and record.get("approved") is False
        and record.get("import_ready") is False
        and record.get("real_import_allowed") is False
    )


def select_priority_records(records: list[dict]) -> list[dict]:
    return [record for record in records if is_priority_record(record)]


def select_deferred_records(records: list[dict]) -> list[dict]:
    return [record for record in records if not is_priority_record(record)]


def _base_source_fields(record: dict) -> dict:
    return {
        "content_hash": str(record["content_hash"]),
        "representative_source_id": str(record["representative_source_id"]),
        "member_source_ids": [
            str(member) for member in record["member_source_ids"]
        ],
        "source_paths": [str(path) for path in record["source_paths"]],
    }


def _provenance_fields(record: dict) -> dict:
    return {
        "provenance_status": str(
            record.get("provenance_status") or "UNKNOWN"
        ),
        "provenance_classification": str(
            record.get("provenance_classification") or "UNKNOWN"
        ),
        "source_truth_class": str(
            record.get("source_truth_class") or SOURCE_TRUTH_CLASS
        ),
        "authority_scope": str(
            record.get("authority_scope") or AUTHORITY_SCOPE
        ),
        "historical_record": bool(record.get("historical_record", True)),
        "historical_runtime_authority": bool(
            record.get("historical_runtime_authority", False)
        ),
    }


def build_priority_manifest(records: list[dict]) -> list[dict]:
    manifest: list[dict] = []
    for record in sorted(records, key=lambda item: str(item["content_hash"])):
        entry = _base_source_fields(record)
        entry.update(_provenance_fields(record))
        entry.update(
            {
                "scan_status": str(record["scan_status"]),
                "finding_count": int(record["finding_count"]),
                "import_eligibility": str(record["import_eligibility"]),
                "approval_status": APPROVAL_PENDING,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "priority_group": PRIORITY_GROUP,
                "review_reason": PRIORITY_REVIEW_REASON,
            }
        )
        entry["source_truth_class"] = SOURCE_TRUTH_CLASS
        entry["authority_scope"] = AUTHORITY_SCOPE
        entry["historical_record"] = True
        entry["historical_runtime_authority"] = False
        manifest.append(entry)
    return manifest


def build_deferred_manifest(
    records: list[dict], inputs: dict
) -> list[dict]:
    manual_by_hash = {
        str(entry["content_hash"]): entry
        for entry in inputs["manual_package"]["package"]
    }
    redaction_by_hash = {
        str(entry["content_hash"]): entry
        for entry in inputs["redaction_plan"]["plan"]
    }

    manifest: list[dict] = []
    for record in sorted(records, key=lambda item: str(item["content_hash"])):
        content_hash = str(record["content_hash"])
        classification = str(record["import_eligibility"])
        entry = _base_source_fields(record)
        entry.update(_provenance_fields(record))
        entry.update(
            {
                "scan_status": str(record["scan_status"]),
                "finding_count": int(record["finding_count"]),
                "import_eligibility": classification,
                "import_disposition": str(record["import_disposition"]),
                "approval_status": APPROVAL_PENDING,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
            }
        )

        if classification == REDACTION_REQUIRED:
            review_prep._require(
                content_hash in redaction_by_hash,
                "redaction_plan",
                f"{content_hash} missing from redaction approval plan",
            )
            source = redaction_by_hash[content_hash]
            entry.update(
                {
                    "deferred_group": DEFERRED_REDACTION_GROUP,
                    "review_classification": REDACTION_REQUIRED,
                    "review_reason": REDACTION_REVIEW_REASON,
                    "finding_ids": [
                        str(fid) for fid in source["finding_ids"]
                    ],
                    "severity_summary": dict(
                        source.get("severity_summary", {})
                    ),
                    "secret_types": [
                        str(item) for item in source.get("secret_types", [])
                    ],
                }
            )
        elif classification == MANUAL_REVIEW_REQUIRED:
            review_prep._require(
                content_hash in manual_by_hash,
                "manual_package",
                f"{content_hash} missing from manual review package",
            )
            source = manual_by_hash[content_hash]
            entry.update(
                {
                    "deferred_group": DEFERRED_MANUAL_REVIEW_GROUP,
                    "review_classification": str(
                        source["review_classification"]
                    ),
                    "review_reason": str(source["review_reason"]),
                    "recommended_action": str(source["recommended_action"]),
                    "finding_ids": [
                        str(fid) for fid in source["finding_ids"]
                    ],
                    "severity_summary": dict(
                        source.get("severity_summary", {})
                    ),
                }
            )
        else:
            raise InputError(
                BLOCKED_INVALID_INPUT,
                "manifest",
                f"unexpected import_eligibility for {content_hash}",
            )

        manifest.append(entry)
    return manifest


def _hash_set(entries: list[dict]) -> set[str]:
    return {str(entry["content_hash"]) for entry in entries}


def reconcile(
    inputs: dict,
    priority: list[dict],
    deferred: list[dict],
    *,
    expected: dict | None = None,
) -> dict:
    baseline = _baseline(expected)
    original = inputs["manifest"]["records"]
    combined = priority + deferred

    original_hashes = [str(record["content_hash"]) for record in original]
    priority_hashes = [str(record["content_hash"]) for record in priority]
    deferred_hashes = [str(record["content_hash"]) for record in deferred]

    mismatches: list[dict] = []

    def _check(
        key: str,
        expected_value: Any,
        actual_value: Any,
        detail: str = "",
    ) -> None:
        if expected_value != actual_value:
            mismatches.append(
                review_prep._mismatch(
                    key, expected_value, actual_value, detail
                )
            )

    _check(
        "PRIORITY_COUNT",
        baseline["PRIORITY_CANDIDATES"],
        len(priority),
    )
    _check(
        "DEFERRED_COUNT",
        baseline["DEFERRED_CANDIDATES"],
        len(deferred),
    )
    _check(
        "PRIORITY_PLUS_DEFERRED",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(priority) + len(deferred),
    )
    _check(
        "PRIORITY_HASH_DUPLICATES",
        0,
        len(priority_hashes) - len(set(priority_hashes)),
    )
    _check(
        "DEFERRED_HASH_DUPLICATES",
        0,
        len(deferred_hashes) - len(set(deferred_hashes)),
    )
    _check(
        "PRIORITY_DEFERRED_OVERLAP",
        0,
        len(set(priority_hashes) & set(deferred_hashes)),
    )
    _check(
        "UNION_EQUALS_ORIGINAL_MANIFEST",
        True,
        set(priority_hashes) | set(deferred_hashes)
        == set(original_hashes),
    )
    _check(
        "CONTENT_UNIQUE_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(set(original_hashes)),
    )

    original_references = sum(
        len(record["member_source_ids"]) for record in original
    )
    combined_references = sum(
        len(record["member_source_ids"]) for record in combined
    )
    _check(
        "SOURCE_REFERENCE_TOTAL",
        baseline["TOTAL_SOURCE_REFERENCES"],
        combined_references,
    )
    _check(
        "SOURCE_REFERENCE_LOSS",
        0,
        original_references - combined_references,
    )
    original_paths = sum(len(record["source_paths"]) for record in original)
    combined_paths = sum(len(record["source_paths"]) for record in combined)
    _check("SOURCE_PATH_TOTAL", original_paths, combined_paths)
    _check("SOURCE_PATH_LOSS", 0, original_paths - combined_paths)

    original_by_hash = {
        str(record["content_hash"]): record for record in original
    }
    combined_by_hash = {
        str(record["content_hash"]): record for record in combined
    }
    provenance_loss = sum(
        1
        for content_hash, record in original_by_hash.items()
        if content_hash not in combined_by_hash
        or combined_by_hash[content_hash]["provenance_status"]
        != record["provenance_status"]
    )
    _check("PROVENANCE_LOSS", 0, provenance_loss)

    provenance_counts = review_prep._count_by(combined, "provenance_status")
    _check(
        "PROVENANCE_CONFIRMED_COUNT",
        baseline["PROVENANCE_CONFIRMED"],
        provenance_counts.get("CONFIRMED", 0),
    )
    _check(
        "PROVENANCE_UNKNOWN_COUNT",
        baseline["PROVENANCE_UNKNOWN"],
        provenance_counts.get("UNKNOWN", 0),
    )

    historical_escalation = sum(
        1
        for record in combined
        if record["authority_scope"] != AUTHORITY_SCOPE
        or record["source_truth_class"] != SOURCE_TRUTH_CLASS
        or record["historical_record"] is not True
        or record["historical_runtime_authority"] is not False
    )
    _check(
        "HISTORICAL_AUTHORITY_ESCALATION", 0, historical_escalation
    )

    approval_changes = sum(
        1
        for record in combined
        if record["approved"] is not False
        or record["import_ready"] is not False
        or record["real_import_allowed"] is not False
        or record["approval_status"] != APPROVAL_PENDING
    )
    _check("APPROVAL_FLAG_CHANGES", 0, approval_changes)

    redaction_deferred = sum(
        1
        for record in deferred
        if record.get("deferred_group") == DEFERRED_REDACTION_GROUP
    )
    manual_deferred = sum(
        1
        for record in deferred
        if record.get("deferred_group") == DEFERRED_MANUAL_REVIEW_GROUP
    )
    _check(
        "REDACTION_DEFERRED_COUNT",
        baseline["REDACTION_REQUIRED"],
        redaction_deferred,
    )
    _check(
        "MANUAL_REVIEW_DEFERRED_COUNT",
        baseline["MANUAL_REVIEW_REQUIRED"],
        manual_deferred,
    )

    unexpected_eligibility = sum(
        1
        for record in original
        if record["import_eligibility"]
        not in (
            ELIGIBLE_CANDIDATE,
            REDACTION_REQUIRED,
            MANUAL_REVIEW_REQUIRED,
        )
    )
    _check("UNEXPECTED_ELIGIBILITY_COUNT", 0, unexpected_eligibility)

    eligible_hashes = _hash_set(inputs["eligible"]["candidates"])
    _check(
        "PRIORITY_ELIGIBLE_INPUT_MATCH",
        True,
        eligible_hashes == set(priority_hashes),
    )
    manual_hashes = _hash_set(inputs["manual_package"]["package"])
    redaction_hashes = _hash_set(inputs["redaction_plan"]["plan"])
    deferred_manual_hashes = {
        str(record["content_hash"])
        for record in deferred
        if record.get("deferred_group") == DEFERRED_MANUAL_REVIEW_GROUP
    }
    deferred_redaction_hashes = {
        str(record["content_hash"])
        for record in deferred
        if record.get("deferred_group") == DEFERRED_REDACTION_GROUP
    }
    _check(
        "MANUAL_PACKAGE_MATCH", True, manual_hashes == deferred_manual_hashes
    )
    _check(
        "REDACTION_PLAN_MATCH",
        True,
        redaction_hashes == deferred_redaction_hashes,
    )

    _check(
        "PRIORITY_SELECTION_STRICT",
        0,
        sum(1 for record in priority if not is_priority_record(record)),
    )
    _check(
        "DEFERRED_SELECTION_STRICT",
        0,
        sum(1 for record in deferred if is_priority_record(record)),
    )

    checks = {
        "PRIORITY_COUNT": len(priority),
        "DEFERRED_COUNT": len(deferred),
        "PRIORITY_PLUS_DEFERRED": len(priority) + len(deferred),
        "PRIORITY_HASH_DUPLICATES": len(priority_hashes)
        - len(set(priority_hashes)),
        "DEFERRED_HASH_DUPLICATES": len(deferred_hashes)
        - len(set(deferred_hashes)),
        "PRIORITY_DEFERRED_OVERLAP": len(
            set(priority_hashes) & set(deferred_hashes)
        ),
        "UNION_EQUALS_ORIGINAL_MANIFEST": set(priority_hashes)
        | set(deferred_hashes)
        == set(original_hashes),
        "SOURCE_REFERENCE_TOTAL": combined_references,
        "SOURCE_REFERENCE_LOSS": original_references
        - combined_references,
        "SOURCE_PATH_TOTAL": combined_paths,
        "SOURCE_PATH_LOSS": original_paths - combined_paths,
        "PROVENANCE_LOSS": provenance_loss,
        "HISTORICAL_AUTHORITY_ESCALATION": historical_escalation,
        "APPROVAL_FLAG_CHANGES": approval_changes,
        "REDACTION_DEFERRED_COUNT": redaction_deferred,
        "MANUAL_REVIEW_DEFERRED_COUNT": manual_deferred,
    }

    counts = {
        "CONTENT_UNIQUE_COUNT": len(set(original_hashes)),
        "SOURCE_REFERENCE_COUNT": combined_references,
        "PRIORITY_COUNT": len(priority),
        "DEFERRED_COUNT": len(deferred),
        "PRIORITY_PLUS_DEFERRED": len(priority) + len(deferred),
        "REDACTION_DEFERRED_COUNT": redaction_deferred,
        "MANUAL_REVIEW_DEFERRED_COUNT": manual_deferred,
        "PRIORITY_DEFERRED_OVERLAP": checks["PRIORITY_DEFERRED_OVERLAP"],
        "PRIORITY_HASH_DUPLICATES": checks["PRIORITY_HASH_DUPLICATES"],
        "DEFERRED_HASH_DUPLICATES": checks["DEFERRED_HASH_DUPLICATES"],
        "SOURCE_REFERENCE_LOSS": checks["SOURCE_REFERENCE_LOSS"],
        "PROVENANCE_LOSS": provenance_loss,
        "PROVENANCE_CONFIRMED_COUNT": provenance_counts.get(
            "CONFIRMED", 0
        ),
        "PROVENANCE_UNKNOWN_COUNT": provenance_counts.get("UNKNOWN", 0),
        "HISTORICAL_AUTHORITY_ESCALATION": historical_escalation,
        "APPROVAL_FLAG_CHANGES": approval_changes,
    }

    return {
        "status": INPUTS_VALID if not mismatches else BLOCKED_INVALID_INPUT,
        "valid": not mismatches,
        "mismatches": mismatches,
        "checks": checks,
        "counts": counts,
    }


def build_safety_review(inputs: dict, priority: list[dict]) -> dict:
    manifest_hashes = _hash_set(inputs["manifest"]["records"])
    eligible_hashes = _hash_set(inputs["eligible"]["candidates"])

    records: list[dict] = []
    for record in priority:
        content_hash = str(record["content_hash"])
        records.append(
            {
                "content_hash": content_hash,
                "secret_scan_completed": record["scan_status"]
                == SCAN_COMPLETED_NO_FINDINGS,
                "no_findings": int(record["finding_count"]) == 0,
                "source_hash_present": bool(
                    HEX64_PATTERN.match(content_hash)
                ),
                "matches_existing_manifest": content_hash
                in manifest_hashes,
                "matches_eligible_candidates": content_hash
                in eligible_hashes,
            }
        )

    summary = {
        "SCAN_COMPLETED_CONFIRMED": all(
            record["secret_scan_completed"] for record in records
        ),
        "NO_FINDINGS_CONFIRMED": all(
            record["no_findings"] for record in records
        ),
        "SOURCE_HASH_CONFIRMED": all(
            record["source_hash_present"] for record in records
        ),
        "MANIFEST_MATCH_CONFIRMED": all(
            record["matches_existing_manifest"] for record in records
        ),
        "ELIGIBLE_MATCH_CONFIRMED": all(
            record["matches_eligible_candidates"] for record in records
        ),
    }

    return {
        "count": len(records),
        "summary": summary,
        "note": SAFETY_NOTE,
        "records": records,
    }


def build_result(
    inputs: dict,
    *,
    generated_at: str | None = None,
    expected: dict | None = None,
) -> dict:
    timestamp = generated_at or review_prep._now_iso()
    validate_shapes(inputs, expected=expected)

    records = inputs["manifest"]["records"]
    priority_records = select_priority_records(records)
    deferred_records = select_deferred_records(records)

    priority = build_priority_manifest(priority_records)
    deferred = build_deferred_manifest(deferred_records, inputs)

    reconciliation = reconcile(
        inputs, priority, deferred, expected=expected
    )
    if not reconciliation["valid"]:
        raise InputError(
            BLOCKED_INVALID_INPUT,
            "reconciliation",
            "; ".join(
                item["key"]
                for item in reconciliation["mismatches"][:10]
            ),
        )

    safety_review = build_safety_review(inputs, priority)

    for collection in (priority, deferred):
        if any(entry["approved"] for entry in collection):
            raise SecurityBoundaryError("approved must remain false")
        if any(entry["import_ready"] for entry in collection):
            raise SecurityBoundaryError("import_ready must remain false")
        if any(entry["real_import_allowed"] for entry in collection):
            raise SecurityBoundaryError(
                "real_import_allowed must remain false"
            )

    counts = dict(reconciliation["counts"])
    counts.update(
        {
            "SAFETY_REVIEW_COUNT": safety_review["count"],
        }
    )

    acceptance = {
        "INPUTS_VALID": True,
        "PRIORITY_CANDIDATE_COUNT": counts["PRIORITY_COUNT"],
        "DEFERRED_CANDIDATE_COUNT": counts["DEFERRED_COUNT"],
        "REDACTION_DEFERRED_COUNT": counts[
            "REDACTION_DEFERRED_COUNT"
        ],
        "MANUAL_REVIEW_DEFERRED_COUNT": counts[
            "MANUAL_REVIEW_DEFERRED_COUNT"
        ],
        "CONTENT_UNIQUE_COUNT": counts["CONTENT_UNIQUE_COUNT"],
        "SOURCE_REFERENCE_COUNT": counts["SOURCE_REFERENCE_COUNT"],
        "PRIORITY_DEFERRED_OVERLAP": counts[
            "PRIORITY_DEFERRED_OVERLAP"
        ],
        "SOURCE_REFERENCE_LOSS": counts["SOURCE_REFERENCE_LOSS"],
        "PROVENANCE_LOSS": counts["PROVENANCE_LOSS"],
        "ALL_APPROVED_FALSE": True,
        "ALL_IMPORT_READY_FALSE": True,
        "ALL_REAL_IMPORT_ALLOWED_FALSE": True,
        "HISTORICAL_RUNTIME_AUTHORITY_FALSE": True,
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
        "priority_manifest": priority,
        "deferred_manifest": deferred,
        "safety_review": safety_review,
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


def _payload_header(
    schema_version: str, result: dict, **extra: Any
) -> dict:
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
        "priority_manifest": _payload_header(
            PRIORITY_MANIFEST_SCHEMA_VERSION,
            result,
            priority_group=PRIORITY_GROUP,
            count=len(result["priority_manifest"]),
            records=result["priority_manifest"],
            note=SAFETY_NOTE,
        ),
        "deferred_manifest": _payload_header(
            DEFERRED_MANIFEST_SCHEMA_VERSION,
            result,
            count=len(result["deferred_manifest"]),
            by_deferred_group=review_prep._count_by(
                result["deferred_manifest"], "deferred_group"
            ),
            records=result["deferred_manifest"],
        ),
        "reconciliation": _payload_header(
            RECONCILIATION_SCHEMA_VERSION,
            result,
            valid=result["reconciliation"]["valid"],
            status=result["reconciliation"]["status"],
            checks=result["reconciliation"]["checks"],
            mismatches=result["reconciliation"]["mismatches"],
        ),
        "pre_import_safety_review": _payload_header(
            SAFETY_REVIEW_SCHEMA_VERSION,
            result,
            count=result["safety_review"]["count"],
            summary=result["safety_review"]["summary"],
            note=result["safety_review"]["note"],
            records=result["safety_review"]["records"],
            additional_import_approval_required=True,
            production_write_allowed=False,
        ),
    }


def render_approval_request(result: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    counts = result["counts"]
    checks = result["reconciliation"]["checks"]
    lines = [
        "# BC-11E-7D Priority 390 Approval Request",
        "",
        f"TASK_ID={result['task_id']}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "REAL_IMPORT_APPROVED=NO",
        "RECORD_IMPORT_APPROVED=NO",
        "PRODUCTION_WRITE_APPROVED=NO",
        "REDACTION_EXECUTION_APPROVED=NO",
        "MANUAL_REVIEW_DISPOSITION_APPROVED=NO",
        "GIT_PUSH_APPROVED=NO",
        "",
        "## 1. Priority candidate scope",
        "",
        f"- PRIORITY_CANDIDATE_COUNT={counts['PRIORITY_COUNT']}",
        f"- PRIORITY_GROUP={PRIORITY_GROUP}",
        "- APPROVAL_STATUS=PENDING_OPERATOR_APPROVAL",
        "- ALL_APPROVED_FALSE=TRUE",
        "- ALL_IMPORT_READY_FALSE=TRUE",
        "- ALL_REAL_IMPORT_ALLOWED_FALSE=TRUE",
        "",
        "The 390 priority candidates are no-finding, eligible candidates from the",
        "existing BC-11E-7B manifest. This pack is a preparation artifact only.",
        "Selecting the priority approach is not an approval to import records.",
        "",
        "## 2. Deferred candidate scope",
        "",
        f"- DEFERRED_CANDIDATE_COUNT={counts['DEFERRED_COUNT']}",
        f"- REDACTION_DEFERRED_COUNT="
        f"{counts['REDACTION_DEFERRED_COUNT']}",
        f"- MANUAL_REVIEW_DEFERRED_COUNT="
        f"{counts['MANUAL_REVIEW_DEFERRED_COUNT']}",
        "",
        "Deferred records remain in the original 491-record manifest. No source",
        "reference, provenance, review result, or approval status was removed or",
        "changed.",
        "",
        "## 3. Reconciliation summary",
        "",
        f"- CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"- SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"- PRIORITY_PLUS_DEFERRED="
        f"{checks['PRIORITY_PLUS_DEFERRED']}",
        f"- PRIORITY_DEFERRED_OVERLAP="
        f"{checks['PRIORITY_DEFERRED_OVERLAP']}",
        f"- SOURCE_REFERENCE_LOSS={checks['SOURCE_REFERENCE_LOSS']}",
        f"- PROVENANCE_LOSS={checks['PROVENANCE_LOSS']}",
        f"- HISTORICAL_AUTHORITY_ESCALATION="
        f"{checks['HISTORICAL_AUTHORITY_ESCALATION']}",
        f"- APPROVAL_FLAG_CHANGES={checks['APPROVAL_FLAG_CHANGES']}",
        "",
        "## 4. Pre-import safety review",
        "",
        "- SECRET_SCAN_COMPLETED_CONFIRMED=YES",
        "- NO_FINDINGS_CONFIRMED=YES",
        "- SOURCE_HASH_CONFIRMED=YES",
        "- EXISTING_MANIFEST_MATCH_CONFIRMED=YES",
        "",
        "NO_FINDINGS does not prove that no secret exists. Additional import",
        "approval is required. Production database writes are forbidden.",
        "",
        "## 5. Operator decisions required",
        "",
        "1. Explicitly approve or reject the 390-record priority manifest.",
        "2. Resolve the 17 deferred redaction candidates in a separate task.",
        "3. Resolve the 84 deferred manual review candidates in a separate task.",
        "4. Authorize any real import only in a separate approved task.",
        "",
        "## 6. Safety boundaries",
        "",
        "- REAL_IMPORT_EXECUTED=NO",
        "- RECORD_IMPORT_APPROVED=NO",
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
        "HISTORICAL_RUNTIME_AUTHORITY_FALSE=TRUE",
        "",
    ]
    return "\n".join(lines)


def render_final(result: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    counts = result["counts"]
    checks = result["reconciliation"]["checks"]
    acceptance = result["acceptance"]
    lines = [
        "# BC-11E-7D Priority 390 Approval Preparation",
        "",
        f"TASK_ID={result['task_id']}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        f"COMMIT={meta.get('commit', 'NONE')}",
        "",
        f"PRIORITY_CANDIDATE_COUNT={counts['PRIORITY_COUNT']}",
        f"DEFERRED_CANDIDATE_COUNT={counts['DEFERRED_COUNT']}",
        f"REDACTION_DEFERRED_COUNT="
        f"{counts['REDACTION_DEFERRED_COUNT']}",
        f"MANUAL_REVIEW_DEFERRED_COUNT="
        f"{counts['MANUAL_REVIEW_DEFERRED_COUNT']}",
        f"CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"PRIORITY_DEFERRED_OVERLAP="
        f"{checks['PRIORITY_DEFERRED_OVERLAP']}",
        f"SOURCE_REFERENCE_LOSS={checks['SOURCE_REFERENCE_LOSS']}",
        f"PROVENANCE_LOSS={checks['PROVENANCE_LOSS']}",
        "",
        f"ALL_APPROVED_FALSE="
        f"{str(acceptance['ALL_APPROVED_FALSE']).upper()}",
        f"ALL_IMPORT_READY_FALSE="
        f"{str(acceptance['ALL_IMPORT_READY_FALSE']).upper()}",
        f"ALL_REAL_IMPORT_ALLOWED_FALSE="
        f"{str(acceptance['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
        f"HISTORICAL_RUNTIME_AUTHORITY_FALSE="
        f"{str(acceptance['HISTORICAL_RUNTIME_AUTHORITY_FALSE']).upper()}",
        "",
        "TEST_RESULTS=" + meta.get("test_results", "PENDING"),
        "CHANGED_FILES=" + meta.get("changed_files", "UNKNOWN"),
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
            "BC-11E-7E_OPERATOR_PRIORITY_390_APPROVAL_DECISION",
        ),
        "",
    ]
    return "\n".join(lines)


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
        "priority_manifest": target / PRIORITY_JSON_NAME,
        "deferred_manifest": target / DEFERRED_JSON_NAME,
        "reconciliation": target / RECONCILIATION_JSON_NAME,
        "pre_import_safety_review": target / SAFETY_JSON_NAME,
        "priority_approval_request": target / APPROVAL_REQUEST_MD_NAME,
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
    payloads["priority_approval_request"] = render_approval_request(
        result, meta
    )
    payloads["final"] = render_final(result, meta)

    for key, path in paths.items():
        payload = payloads[key]
        text = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        review_prep._write_private_text(path, text)
    return {key: str(path) for key, path in paths.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--eligible", default=str(DEFAULT_ELIGIBLE_PATH))
    parser.add_argument(
        "--candidate-summary", default=str(DEFAULT_CANDIDATE_SUMMARY_PATH)
    )
    parser.add_argument(
        "--manual-package", default=str(DEFAULT_MANUAL_PACKAGE_PATH)
    )
    parser.add_argument(
        "--redaction-plan", default=str(DEFAULT_REDACTION_PLAN_PATH)
    )
    parser.add_argument(
        "--finding-review", default=str(DEFAULT_FINDING_REVIEW_PATH)
    )
    parser.add_argument(
        "--operator-request", default=str(DEFAULT_OPERATOR_REQUEST_PATH)
    )
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
    parser.add_argument(
        "--next-recommended-task",
        default="BC-11E-7E_OPERATOR_PRIORITY_390_APPROVAL_DECISION",
    )
    return parser


def _fixture_paths(args: argparse.Namespace) -> dict[str, str]:
    return {
        "manifest": args.manifest,
        "eligible": args.eligible,
        "candidate_summary": args.candidate_summary,
        "manual_package": args.manual_package,
        "redaction_plan": args.redaction_plan,
        "finding_review": args.finding_review,
        "operator_request": args.operator_request,
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
        "next_recommended_task": args.next_recommended_task,
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inputs = load_inputs(_fixture_paths(args))
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
