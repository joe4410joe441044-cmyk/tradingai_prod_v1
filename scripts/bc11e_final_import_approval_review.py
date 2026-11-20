"""BC-11E-7B final historical report import approval review.

This module is a read-only approval-review packager. It consumes the BC-11E-7A
Stage B real-scan artifacts and the BC-11E-5/6 evidence, then produces the
review material an operator needs before approving any historical report
import.

Hard safety boundaries:

* no source report is opened or modified;
* no secret value, partial secret value, surrounding body text, or secret-value
  hash is read or written here;
* no database is opened for writing, no schema is created, no migration runs;
* no record is imported;
* every approval/import flag stays ``false``;
* the production/canonical tree is never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

TASK_ID = "TRADINGAI-WORK-BC-11E7B-FINAL-IMPORT-APPROVAL-REVIEW-1"
MODE = "READ_ONLY_FINAL_IMPORT_APPROVAL_REVIEW"

VERDICT_READY = "BC11E7B_FINAL_IMPORT_APPROVAL_REVIEW_READY"
VERDICT_INPUT_BLOCKED = "BC11E7B_INPUT_BLOCKED"
VERDICT_SECURITY_BLOCKED = "BC11E7B_SECURITY_BLOCKED"
VERDICT_TEST_FAILED = "BC11E7B_TEST_FAILED"

ELIGIBLE_SCHEMA_VERSION = "tradingai-bc11e7b-eligible-import-candidates/v1"
DISPOSITION_SCHEMA_VERSION = "tradingai-bc11e7b-secret-finding-disposition/v1"
REDACTION_SCHEMA_VERSION = "tradingai-bc11e7b-redaction-review-plan/v1"
MANUAL_SCHEMA_VERSION = "tradingai-bc11e7b-manual-review-queue/v1"
MANIFEST_SCHEMA_VERSION = "tradingai-bc11e7b-final-approval-manifest/v1"

SCAN_RESULTS_SCHEMA_VERSION = "tradingai-bc11e7a-real-scan-results/v1"
FINDINGS_SUMMARY_SCHEMA_VERSION = "tradingai-bc11e7a-secret-findings-summary/v1"
PROVENANCE_EVIDENCE_SCHEMA_VERSION = (
    "tradingai-bc11e7a-provenance-evidence-review/v1"
)
IMPORT_ELIGIBILITY_SCHEMA_VERSION = (
    "tradingai-bc11e7a-import-eligibility-review/v1"
)
MANIFEST_REVIEW_SCHEMA_VERSION = "tradingai-bc11e6-import-manifest-review/v1"
CONTENT_HASH_SCHEMA_VERSION = "tradingai-bc11e5-content-hash-results/v1"

DEFAULT_OUTPUT_DIR = Path("/tmp/work_bc_audit")
DEFAULT_SCAN_RESULTS_PATH = DEFAULT_OUTPUT_DIR / "BC11E7A_REAL_SCAN_RESULTS.json"
DEFAULT_SECRET_FINDINGS_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7A_SECRET_FINDINGS_SUMMARY.json"
)
DEFAULT_PROVENANCE_EVIDENCE_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7A_PROVENANCE_EVIDENCE_REVIEW.json"
)
DEFAULT_IMPORT_ELIGIBILITY_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E7A_IMPORT_ELIGIBILITY_REVIEW.json"
)
DEFAULT_STAGE_B_FINAL_PATH = DEFAULT_OUTPUT_DIR / "BC11E7A_STAGE_B_FINAL.md"
DEFAULT_MANIFEST_REVIEW_PATH = (
    DEFAULT_OUTPUT_DIR / "BC11E6_IMPORT_MANIFEST_REVIEW.json"
)
DEFAULT_HASH_RESULTS_PATH = DEFAULT_OUTPUT_DIR / "BC11E5_CONTENT_HASH_RESULTS.json"

ELIGIBLE_JSON_NAME = "BC11E7B_ELIGIBLE_IMPORT_CANDIDATES.json"
DISPOSITION_JSON_NAME = "BC11E7B_SECRET_FINDING_DISPOSITION.json"
REDACTION_JSON_NAME = "BC11E7B_REDACTION_REVIEW_PLAN.json"
MANUAL_JSON_NAME = "BC11E7B_MANUAL_REVIEW_QUEUE.json"
MANIFEST_JSON_NAME = "BC11E7B_FINAL_APPROVAL_MANIFEST.json"
APPROVAL_REQUEST_MD_NAME = "BC11E7B_IMPORT_APPROVAL_REQUEST.md"
FINAL_MD_NAME = "BC11E7B_FINAL.md"

INPUTS_VALID = "INPUTS_VALID"
BLOCKED_MISSING_INPUT = "BLOCKED_MISSING_INPUT"
BLOCKED_INVALID_INPUT = "BLOCKED_INVALID_INPUT"
BLOCKED_EXISTING_OUTPUT = "BLOCKED_EXISTING_OUTPUT"

SCAN_COMPLETED_NO_FINDINGS = "SCAN_COMPLETED_NO_FINDINGS"
SCAN_COMPLETED_FINDINGS = "SCAN_COMPLETED_FINDINGS"

ELIGIBLE_CANDIDATE = "ELIGIBLE_CANDIDATE"
REDACTION_REQUIRED = "REDACTION_REQUIRED"
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"

PROVENANCE_CONFIRMED = "CONFIRMED"
PROVENANCE_UNKNOWN = "UNKNOWN"
SOURCE_TRUTH_CLASS = "AGENT_REPORTED"
AUTHORITY_SCOPE = "NONE"

ACTION_REDACT = "REDACT_BEFORE_IMPORT"
ACTION_REVIEW = "REVIEW_REQUIRED"
ACTION_EXCLUDE = "EXCLUDE_FROM_IMPORT"

DISPOSITION_REDACTION_REQUIRED = "REDACTION_REQUIRED"
DISPOSITION_MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
DISPOSITION_POSSIBLE_FALSE_POSITIVE = "POSSIBLE_FALSE_POSITIVE"
DISPOSITION_UNRESOLVED = "UNRESOLVED"
DISPOSITION_VALUES = (
    DISPOSITION_REDACTION_REQUIRED,
    DISPOSITION_MANUAL_REVIEW_REQUIRED,
    DISPOSITION_POSSIBLE_FALSE_POSITIVE,
    DISPOSITION_UNRESOLVED,
)

MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE = "POSSIBLE_FALSE_POSITIVE"
MANUAL_CLASS_REDACTION_RECOMMENDED = "REDACTION_RECOMMENDED"
MANUAL_CLASS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW = "IMPORT_EXCLUSION_REVIEW"

IMPORT_DISPOSITION_IMPORT = "PROPOSED_IMPORT"
IMPORT_DISPOSITION_REDACTED_IMPORT = "PROPOSED_REDACTED_IMPORT"
IMPORT_DISPOSITION_MANUAL_REVIEW = "PROPOSED_MANUAL_REVIEW"

APPROVAL_PENDING = "PENDING_OPERATOR_APPROVAL"
REVIEW_PENDING = "PENDING_OPERATOR_REVIEW"
REDACTION_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
REDACTION_STATUS_NOT_APPLIED = "NOT_APPLIED"
REVIEW_STATUS_NOT_REQUIRED = "NOT_REQUIRED"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

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

DEFAULT_DESTINATION_PATH = Path(
    "/home/joe4410joe/tradingai_prod_v1/logs/runtime/knowledge_hub/"
    "knowledge_store.sqlite3"
)
DEFAULT_DESTINATION_CONFIG_PATH = (
    ROOT / "backend" / "knowledge_hub" / "import_readiness.py"
)
DESTINATION_STATUS_CONFIRMED = "IMPORT_DESTINATION_CONFIRMED_READ_ONLY"
DESTINATION_STATUS_REVIEW = "IMPORT_DESTINATION_REVIEW_REQUIRED"
DESTINATION_STATUS_MISSING = "IMPORT_DESTINATION_MISSING"

EXPECTED_BASELINE = {
    "TOTAL_CONTENT_UNIQUE": 491,
    "SOURCE_REFERENCE_COUNT": 6646,
    "SCAN_COMPLETED_COUNT": 491,
    "SCAN_COMPLETED_NO_FINDINGS_COUNT": 390,
    "SCAN_COMPLETED_FINDINGS_COUNT": 101,
    "SECRET_FINDING_COUNT": 154,
    "CRITICAL_FINDING_COUNT": 0,
    "HIGH_FINDING_COUNT": 29,
    "MEDIUM_FINDING_COUNT": 125,
    "LOW_FINDING_COUNT": 0,
    "ELIGIBLE_CANDIDATE_COUNT": 390,
    "REDACTION_REQUIRED_COUNT": 17,
    "MANUAL_REVIEW_REQUIRED_COUNT": 84,
    "PROVENANCE_CONFIRMED_COUNT": 3,
    "PROVENANCE_UNKNOWN_COUNT": 488,
    "FINAL_APPROVAL_MANIFEST_COUNT": 491,
}

REQUIRED_SCAN_TARGET_FIELDS = (
    "content_hash",
    "representative_source_id",
    "scan_status",
    "finding_count",
    "findings",
    "severity_counts",
    "provenance_evidence",
)
REQUIRED_FINDING_FIELDS = (
    "finding_id",
    "content_hash",
    "secret_type",
    "severity",
    "confidence",
    "default_action",
)
REQUIRED_PROVENANCE_FIELDS = (
    "content_hash",
    "representative_source_id",
    "provenance_status",
    "source_truth_class",
    "authority_scope",
)
REQUIRED_ELIGIBILITY_FIELDS = (
    "content_hash",
    "representative_source_id",
    "scan_status",
    "secret_finding_count",
    "import_eligibility",
    "approved",
    "import_ready",
    "real_import_allowed",
)
REQUIRED_MANIFEST_FIELDS = (
    "content_hash",
    "representative_source_id",
    "member_source_ids",
    "source_paths",
)
REQUIRED_HASH_FIELDS = ("source_id", "absolute_path", "sha256")


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


def validate_shapes(fixtures: dict) -> None:
    scan = fixtures["scan_results"]
    summary = fixtures["secret_findings"]
    provenance = fixtures["provenance_evidence"]
    eligibility = fixtures["import_eligibility"]
    manifest = fixtures["manifest_review"]
    hashes = fixtures["hash_results"]
    stage_b_final = fixtures["stage_b_final"]

    _require(
        scan.get("schema_version") == SCAN_RESULTS_SCHEMA_VERSION,
        "scan_results",
        "unexpected schema_version",
    )
    _require(
        summary.get("schema_version") == FINDINGS_SUMMARY_SCHEMA_VERSION,
        "secret_findings",
        "unexpected schema_version",
    )
    _require(
        provenance.get("schema_version") == PROVENANCE_EVIDENCE_SCHEMA_VERSION,
        "provenance_evidence",
        "unexpected schema_version",
    )
    _require(
        eligibility.get("schema_version") == IMPORT_ELIGIBILITY_SCHEMA_VERSION,
        "import_eligibility",
        "unexpected schema_version",
    )
    _require(
        manifest.get("schema_version") == MANIFEST_REVIEW_SCHEMA_VERSION,
        "manifest_review",
        "unexpected schema_version",
    )
    _require(
        hashes.get("schema_version") == CONTENT_HASH_SCHEMA_VERSION,
        "hash_results",
        "unexpected schema_version",
    )
    _require(
        "VERDICT=BC11E7A_STAGE_B_REAL_SCAN_COMPLETE"
        in str(stage_b_final.get("text", "")),
        "stage_b_final",
        "baseline verdict missing",
    )

    for key, origin in (
        ("targets", "scan_results"),
        ("per_target", "secret_findings"),
        ("entries", "provenance_evidence"),
        ("entries", "import_eligibility"),
        ("entries", "manifest_review"),
        ("entries", "hash_results"),
    ):
        _require(
            isinstance(fixtures[_origin_key(origin)].get(key), list),
            origin,
            f"{key} must be a list",
        )

    _require_fields(scan["targets"], REQUIRED_SCAN_TARGET_FIELDS, "scan_results")
    for index, target in enumerate(scan["targets"]):
        if not isinstance(target.get("findings"), list):
            raise InputError(
                BLOCKED_INVALID_INPUT,
                "scan_results",
                f"entry {index} findings is not a list",
            )
        _require_fields(target["findings"], REQUIRED_FINDING_FIELDS, "findings")
    _require_fields(
        provenance["entries"], REQUIRED_PROVENANCE_FIELDS, "provenance_evidence"
    )
    _require_fields(
        eligibility["entries"], REQUIRED_ELIGIBILITY_FIELDS, "import_eligibility"
    )
    _require_fields(manifest["entries"], REQUIRED_MANIFEST_FIELDS, "manifest_review")
    _require_fields(hashes["entries"], REQUIRED_HASH_FIELDS, "hash_results")


def _origin_key(origin: str) -> str:
    return {
        "scan_results": "scan_results",
        "secret_findings": "secret_findings",
        "provenance_evidence": "provenance_evidence",
        "import_eligibility": "import_eligibility",
        "manifest_review": "manifest_review",
        "hash_results": "hash_results",
    }[origin]


def _count_by(entries: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _finding_severities(targets: list[dict]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for target in targets:
        for finding in target.get("findings", []):
            severity = str(finding.get("severity") or SEVERITY_UNKNOWN)
            if severity not in counts:
                counts[severity] = 0
            counts[severity] += 1
    return counts


def _mismatch(key: str, expected: Any, actual: Any, detail: str = "") -> dict:
    return {
        "key": key,
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def reconcile(fixtures: dict, *, expected: dict | None = None) -> dict:
    baseline = dict(EXPECTED_BASELINE)
    if expected:
        baseline.update(expected)

    scan_targets = fixtures["scan_results"]["targets"]
    summary_targets = fixtures["secret_findings"]["per_target"]
    provenance_entries = fixtures["provenance_evidence"]["entries"]
    eligibility_entries = fixtures["import_eligibility"]["entries"]
    manifest_entries = fixtures["manifest_review"]["entries"]
    hash_entries = fixtures["hash_results"]["entries"]

    mismatches: list[dict] = []

    def _check(key: str, expected_value: Any, actual_value: Any, detail: str = ""):
        if expected_value != actual_value:
            mismatches.append(_mismatch(key, expected_value, actual_value, detail))

    scan_hashes = {str(target["content_hash"]) for target in scan_targets}
    summary_hashes = {str(entry["content_hash"]) for entry in summary_targets}
    provenance_hashes = {
        str(entry["content_hash"]) for entry in provenance_entries
    }
    eligibility_hashes = {
        str(entry["content_hash"]) for entry in eligibility_entries
    }
    manifest_hashes = {str(entry["content_hash"]) for entry in manifest_entries}

    _check(
        "CONTENT_UNIQUE_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(scan_hashes),
        "distinct scan content hashes",
    )
    _check(
        "SCAN_TARGET_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(scan_targets),
    )
    _check(
        "SUMMARY_TARGET_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(summary_targets),
    )
    _check(
        "PROVENANCE_ENTRY_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(provenance_entries),
    )
    _check(
        "ELIGIBILITY_ENTRY_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(eligibility_entries),
    )
    _check(
        "MANIFEST_ENTRY_COUNT",
        baseline["TOTAL_CONTENT_UNIQUE"],
        len(manifest_entries),
    )
    _check("SCAN_HASH_SET_EQUAL", True, scan_hashes == summary_hashes)
    _check("PROVENANCE_HASH_SET_EQUAL", True, scan_hashes == provenance_hashes)
    _check("ELIGIBILITY_HASH_SET_EQUAL", True, scan_hashes == eligibility_hashes)
    _check("MANIFEST_HASH_SET_EQUAL", True, scan_hashes == manifest_hashes)

    scan_hashes_list = [str(target["content_hash"]) for target in scan_targets]
    _check(
        "CONTENT_HASH_UNIQUE",
        True,
        len(scan_hashes_list) == len(set(scan_hashes_list)),
    )

    source_ids = [str(entry["source_id"]) for entry in hash_entries]
    manifest_members = [
        str(member)
        for entry in manifest_entries
        for member in entry["member_source_ids"]
    ]
    manifest_paths = [
        str(path) for entry in manifest_entries for path in entry["source_paths"]
    ]
    _check(
        "SOURCE_REFERENCE_COUNT",
        baseline["SOURCE_REFERENCE_COUNT"],
        len(hash_entries),
    )
    _check(
        "SOURCE_REFERENCE_ID_UNIQUE",
        baseline["SOURCE_REFERENCE_COUNT"],
        len(set(source_ids)),
    )
    _check(
        "MANIFEST_MEMBER_REFERENCE_COUNT",
        baseline["SOURCE_REFERENCE_COUNT"],
        len(manifest_members),
    )
    _check(
        "MANIFEST_SOURCE_PATH_COUNT",
        baseline["SOURCE_REFERENCE_COUNT"],
        len(manifest_paths),
    )
    _check(
        "SOURCE_ID_SET_EQUAL",
        True,
        set(source_ids) == set(manifest_members),
    )

    scan_status = _count_by(scan_targets, "scan_status")
    no_findings = scan_status.get(SCAN_COMPLETED_NO_FINDINGS, 0)
    findings = scan_status.get(SCAN_COMPLETED_FINDINGS, 0)
    _check(
        "SCAN_COMPLETED_COUNT",
        baseline["SCAN_COMPLETED_COUNT"],
        no_findings + findings,
    )
    _check(
        "SCAN_COMPLETED_NO_FINDINGS_COUNT",
        baseline["SCAN_COMPLETED_NO_FINDINGS_COUNT"],
        no_findings,
    )
    _check(
        "SCAN_COMPLETED_FINDINGS_COUNT",
        baseline["SCAN_COMPLETED_FINDINGS_COUNT"],
        findings,
    )
    _check(
        "SCAN_STATUS_RECONCILIATION",
        baseline["TOTAL_CONTENT_UNIQUE"],
        no_findings + findings,
    )

    severity = _finding_severities(scan_targets)
    finding_total = sum(severity.values())
    _check(
        "SECRET_FINDING_COUNT",
        baseline["SECRET_FINDING_COUNT"],
        finding_total,
    )
    _check(
        "CRITICAL_FINDING_COUNT",
        baseline["CRITICAL_FINDING_COUNT"],
        severity.get(SEVERITY_CRITICAL, 0),
    )
    _check(
        "HIGH_FINDING_COUNT",
        baseline["HIGH_FINDING_COUNT"],
        severity.get(SEVERITY_HIGH, 0),
    )
    _check(
        "MEDIUM_FINDING_COUNT",
        baseline["MEDIUM_FINDING_COUNT"],
        severity.get(SEVERITY_MEDIUM, 0),
    )
    _check(
        "LOW_FINDING_COUNT",
        baseline["LOW_FINDING_COUNT"],
        severity.get(SEVERITY_LOW, 0),
    )
    _check(
        "SEVERITY_RECONCILIATION",
        baseline["SECRET_FINDING_COUNT"],
        (
            severity.get(SEVERITY_CRITICAL, 0)
            + severity.get(SEVERITY_HIGH, 0)
            + severity.get(SEVERITY_MEDIUM, 0)
            + severity.get(SEVERITY_LOW, 0)
        ),
    )

    eligibility_counts = _count_by(eligibility_entries, "import_eligibility")
    eligible = eligibility_counts.get(ELIGIBLE_CANDIDATE, 0)
    redaction = eligibility_counts.get(REDACTION_REQUIRED, 0)
    manual = eligibility_counts.get(MANUAL_REVIEW_REQUIRED, 0)
    _check(
        "ELIGIBLE_CANDIDATE_COUNT",
        baseline["ELIGIBLE_CANDIDATE_COUNT"],
        eligible,
    )
    _check(
        "REDACTION_REQUIRED_COUNT",
        baseline["REDACTION_REQUIRED_COUNT"],
        redaction,
    )
    _check(
        "MANUAL_REVIEW_REQUIRED_COUNT",
        baseline["MANUAL_REVIEW_REQUIRED_COUNT"],
        manual,
    )
    _check(
        "ELIGIBILITY_RECONCILIATION",
        baseline["TOTAL_CONTENT_UNIQUE"],
        eligible + redaction + manual,
    )
    _check(
        "ELIGIBILITY_SCAN_RECONCILIATION",
        baseline["TOTAL_CONTENT_UNIQUE"],
        eligible + findings,
    )
    _check(
        "ELIGIBILITY_FINDINGS_RECONCILIATION",
        True,
        eligible == no_findings and redaction + manual == findings,
    )

    provenance_counts = _count_by(provenance_entries, "provenance_status")
    _check(
        "PROVENANCE_CONFIRMED_COUNT",
        baseline["PROVENANCE_CONFIRMED_COUNT"],
        provenance_counts.get(PROVENANCE_CONFIRMED, 0),
    )
    _check(
        "PROVENANCE_UNKNOWN_COUNT",
        baseline["PROVENANCE_UNKNOWN_COUNT"],
        provenance_counts.get(PROVENANCE_UNKNOWN, 0),
    )

    finding_ids = [
        str(finding["finding_id"])
        for target in scan_targets
        for finding in target.get("findings", [])
    ]
    _check("FINDING_ID_UNIQUE", True, len(finding_ids) == len(set(finding_ids)))

    summary_by_hash = {
        str(entry["content_hash"]): entry for entry in summary_targets
    }
    for target in scan_targets:
        entry = summary_by_hash.get(str(target["content_hash"]))
        if entry is None:
            mismatches.append(
                _mismatch(
                    "SUMMARY_TARGET_MISSING",
                    str(target["content_hash"]),
                    None,
                )
            )
            continue
        _check(
            f"SUMMARY_SCAN_STATUS:{target['content_hash']}",
            target["scan_status"],
            entry.get("scan_status"),
        )
        _check(
            f"SUMMARY_FINDING_COUNT:{target['content_hash']}",
            target["finding_count"],
            entry.get("finding_count"),
        )

    eligibility_by_hash = {
        str(entry["content_hash"]): entry for entry in eligibility_entries
    }
    for target in scan_targets:
        entry = eligibility_by_hash[str(target["content_hash"])]
        classification = str(entry["import_eligibility"])
        if classification == ELIGIBLE_CANDIDATE:
            _check(
                f"ELIGIBLE_SCAN_STATUS:{target['content_hash']}",
                SCAN_COMPLETED_NO_FINDINGS,
                target["scan_status"],
            )
            _check(
                f"ELIGIBLE_FINDING_COUNT:{target['content_hash']}",
                0,
                target["finding_count"],
            )
        elif classification == REDACTION_REQUIRED:
            _check(
                f"REDACTION_SCAN_STATUS:{target['content_hash']}",
                SCAN_COMPLETED_FINDINGS,
                target["scan_status"],
            )
            _check(
                f"REDACTION_ACTION:{target['content_hash']}",
                True,
                all(
                    str(finding.get("default_action")) == ACTION_REDACT
                    for finding in target.get("findings", [])
                ),
            )
        elif classification == MANUAL_REVIEW_REQUIRED:
            _check(
                f"MANUAL_SCAN_STATUS:{target['content_hash']}",
                SCAN_COMPLETED_FINDINGS,
                target["scan_status"],
            )
        else:
            mismatches.append(
                _mismatch(
                    "UNEXPECTED_ELIGIBILITY",
                    "ELIGIBLE|REDACTION|MANUAL",
                    classification,
                    str(target["content_hash"]),
                )
            )
        _check(
            f"ELIGIBILITY_FINDING_COUNT:{target['content_hash']}",
            target["finding_count"],
            entry.get("secret_finding_count"),
        )
        _check(
            f"ELIGIBILITY_APPROVED_FALSE:{target['content_hash']}",
            False,
            entry.get("approved"),
        )
        _check(
            f"ELIGIBILITY_IMPORT_READY_FALSE:{target['content_hash']}",
            False,
            entry.get("import_ready"),
        )
        _check(
            f"ELIGIBILITY_REAL_IMPORT_FALSE:{target['content_hash']}",
            False,
            entry.get("real_import_allowed"),
        )
        _check(
            f"SCAN_APPROVED_FALSE:{target['content_hash']}",
            False,
            target.get("approved"),
        )
        _check(
            f"SCAN_IMPORT_READY_FALSE:{target['content_hash']}",
            False,
            target.get("import_ready"),
        )
        _check(
            f"SCAN_REAL_IMPORT_FALSE:{target['content_hash']}",
            False,
            target.get("real_import_allowed"),
        )

    for entry in provenance_entries:
        _check(
            f"PROVENANCE_TRUTH_CLASS:{entry['content_hash']}",
            SOURCE_TRUTH_CLASS,
            entry.get("source_truth_class"),
        )
        _check(
            f"PROVENANCE_AUTHORITY_SCOPE:{entry['content_hash']}",
            AUTHORITY_SCOPE,
            entry.get("authority_scope"),
        )

    return {
        "status": INPUTS_VALID if not mismatches else BLOCKED_INVALID_INPUT,
        "valid": not mismatches,
        "mismatches": mismatches,
        "counts": {
            "CONTENT_UNIQUE_COUNT": len(scan_hashes),
            "SOURCE_REFERENCE_COUNT": len(hash_entries),
            "SCAN_COMPLETED_NO_FINDINGS_COUNT": no_findings,
            "SCAN_COMPLETED_FINDINGS_COUNT": findings,
            "SECRET_FINDING_COUNT": finding_total,
            "ELIGIBLE_CANDIDATE_COUNT": eligible,
            "REDACTION_REQUIRED_COUNT": redaction,
            "MANUAL_REVIEW_REQUIRED_COUNT": manual,
            "PROVENANCE_CONFIRMED_COUNT": provenance_counts.get(
                PROVENANCE_CONFIRMED, 0
            ),
            "PROVENANCE_UNKNOWN_COUNT": provenance_counts.get(
                PROVENANCE_UNKNOWN, 0
            ),
        },
    }


def _index_by_hash(entries: list[dict]) -> dict[str, dict]:
    return {str(entry["content_hash"]): entry for entry in entries}


def _severity_summary(severity_counts: dict) -> dict[str, int]:
    summary = {severity: 0 for severity in SEVERITY_ORDER}
    for key, value in (severity_counts or {}).items():
        summary[str(key)] = int(value)
    return summary


def _sort_findings(findings: list[dict]) -> list[dict]:
    return sorted(
        findings,
        key=lambda finding: (
            str(finding.get("content_hash")),
            str(finding.get("finding_id")),
        ),
    )


def classify_finding(finding: dict) -> tuple[str, str]:
    """Return a conservative finding-level review disposition and reason code."""

    action = str(finding.get("default_action") or "")
    confidence = str(finding.get("confidence") or "")
    secret_type = str(finding.get("secret_type") or "")
    severity = str(finding.get("severity") or "")

    if action == ACTION_REDACT:
        return (
            DISPOSITION_REDACTION_REQUIRED,
            "DETECTOR_REQUIRES_REDACTION_BEFORE_IMPORT",
        )
    if action == ACTION_EXCLUDE:
        return (
            DISPOSITION_MANUAL_REVIEW_REQUIRED,
            "DETECTOR_RECOMMENDS_IMPORT_EXCLUSION_REVIEW",
        )
    if action == ACTION_REVIEW:
        if confidence == CONFIDENCE_LOW:
            return (
                DISPOSITION_MANUAL_REVIEW_REQUIRED,
                "LOW_CONFIDENCE_CONTEXT_REQUIRES_OPERATOR_REVIEW",
            )
        return (
            DISPOSITION_MANUAL_REVIEW_REQUIRED,
            "SECRET_CONTEXT_REQUIRES_OPERATOR_REVIEW",
        )
    if not action and secret_type and severity:
        return (
            DISPOSITION_UNRESOLVED,
            "INSUFFICIENT_EVIDENCE_FOR_DISPOSITION",
        )
    return (
        DISPOSITION_UNRESOLVED,
        "INSUFFICIENT_EVIDENCE_FOR_DISPOSITION",
    )


def build_eligible_candidates(fixtures: dict) -> list[dict]:
    scan_by_hash = _index_by_hash(fixtures["scan_results"]["targets"])
    provenance_by_hash = _index_by_hash(
        fixtures["provenance_evidence"]["entries"]
    )
    manifest_by_hash = _index_by_hash(
        fixtures["manifest_review"]["entries"]
    )

    candidates: list[dict] = []
    for entry in sorted(
        fixtures["import_eligibility"]["entries"],
        key=lambda item: str(item["content_hash"]),
    ):
        if str(entry["import_eligibility"]) != ELIGIBLE_CANDIDATE:
            continue
        content_hash = str(entry["content_hash"])
        target = scan_by_hash[content_hash]
        manifest = manifest_by_hash[content_hash]
        provenance = provenance_by_hash[content_hash]
        _require(
            target["scan_status"] == SCAN_COMPLETED_NO_FINDINGS,
            "eligible_candidate",
            f"{content_hash} is not SCAN_COMPLETED_NO_FINDINGS",
        )
        _require(
            int(target["finding_count"]) == 0,
            "eligible_candidate",
            f"{content_hash} has findings",
        )
        candidates.append(
            {
                "content_hash": content_hash,
                "representative_source_id": str(
                    manifest["representative_source_id"]
                ),
                "member_source_ids": [
                    str(member) for member in manifest["member_source_ids"]
                ],
                "source_paths": [
                    str(path) for path in manifest["source_paths"]
                ],
                "scan_status": target["scan_status"],
                "finding_count": int(target["finding_count"]),
                "provenance_status": str(
                    provenance.get("provenance_status") or PROVENANCE_UNKNOWN
                ),
                "import_disposition": IMPORT_DISPOSITION_IMPORT,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "review_status": REVIEW_PENDING,
                "note": (
                    "SCAN_COMPLETED_NO_FINDINGS does not prove that no secret "
                    "exists; operator approval is still required."
                ),
            }
        )
    return candidates


def build_secret_finding_disposition(fixtures: dict) -> list[dict]:
    entries: list[dict] = []
    for target in sorted(
        fixtures["scan_results"]["targets"],
        key=lambda item: str(item["content_hash"]),
    ):
        for finding in _sort_findings(target.get("findings", [])):
            disposition, reason = classify_finding(finding)
            entries.append(
                {
                    "finding_id": str(finding["finding_id"]),
                    "content_hash": str(finding["content_hash"]),
                    "secret_type": str(finding["secret_type"]),
                    "severity": str(finding["severity"]),
                    "confidence": str(finding["confidence"]),
                    "review_disposition": disposition,
                    "review_reason_code": reason,
                    "review_status": REVIEW_PENDING,
                    "value_stored": False,
                    "context_stored": False,
                    "approved": False,
                    "import_ready": False,
                    "real_import_allowed": False,
                }
            )
    return entries


def build_redaction_plan(fixtures: dict) -> list[dict]:
    scan_by_hash = _index_by_hash(fixtures["scan_results"]["targets"])
    manifest_by_hash = _index_by_hash(
        fixtures["manifest_review"]["entries"]
    )

    plan: list[dict] = []
    for entry in sorted(
        fixtures["import_eligibility"]["entries"],
        key=lambda item: str(item["content_hash"]),
    ):
        if str(entry["import_eligibility"]) != REDACTION_REQUIRED:
            continue
        content_hash = str(entry["content_hash"])
        target = scan_by_hash[content_hash]
        manifest = manifest_by_hash[content_hash]
        findings = _sort_findings(target.get("findings", []))
        plan.append(
            {
                "content_hash": content_hash,
                "representative_source_id": str(
                    manifest["representative_source_id"]
                ),
                "member_source_ids": [
                    str(member) for member in manifest["member_source_ids"]
                ],
                "source_paths": [
                    str(path) for path in manifest["source_paths"]
                ],
                "finding_ids": [
                    str(finding["finding_id"]) for finding in findings
                ],
                "secret_types": sorted(
                    {str(finding["secret_type"]) for finding in findings}
                ),
                "severity_summary": _severity_summary(
                    target.get("severity_counts", {})
                ),
                "redaction_required": True,
                "redaction_status": REDACTION_STATUS_NOT_APPLIED,
                "redaction_applied": False,
                "original_file_modified": False,
                "import_copy_generated": False,
                "import_disposition": IMPORT_DISPOSITION_REDACTED_IMPORT,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "review_status": REVIEW_PENDING,
            }
        )
    return plan


def _manual_classification(target: dict) -> tuple[str, str, str]:
    findings = target.get("findings", [])
    actions = {str(finding.get("default_action")) for finding in findings}
    severities = {str(finding.get("severity")) for finding in findings}

    if ACTION_EXCLUDE in actions or SEVERITY_CRITICAL in severities:
        return (
            MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW,
            "POTENTIAL_EXCLUSION_OR_CRITICAL_FINDING",
            "OPERATOR_DECIDE_INCLUDE_OR_EXCLUDE",
        )
    if ACTION_REDACT in actions:
        return (
            MANUAL_CLASS_REDACTION_RECOMMENDED,
            "MIXED_REDACTION_AND_REVIEW_FINDINGS",
            "OPERATOR_REVIEW_AND_REDACT",
        )
    if findings and all(
        str(finding.get("confidence")) == CONFIDENCE_LOW
        and str(finding.get("detection_method")) == "CREDENTIAL_LIKE_CONTEXT"
        and str(finding.get("secret_type")) == "CREDENTIAL_LIKE_TEXT"
        for finding in findings
    ):
        return (
            MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE,
            "LOW_CONFIDENCE_CONTEXT_HEURISTIC",
            "OPERATOR_CONFIRM_NOT_A_SECRET",
        )
    return (
        MANUAL_CLASS_INSUFFICIENT_EVIDENCE,
        "INSUFFICIENT_EVIDENCE_FOR_AUTOMATED_DISPOSITION",
        "OPERATOR_REVIEW_SECRET_CONTEXT",
    )


def build_manual_review_queue(fixtures: dict) -> list[dict]:
    scan_by_hash = _index_by_hash(fixtures["scan_results"]["targets"])
    manifest_by_hash = _index_by_hash(
        fixtures["manifest_review"]["entries"]
    )

    queue: list[dict] = []
    for entry in sorted(
        fixtures["import_eligibility"]["entries"],
        key=lambda item: str(item["content_hash"]),
    ):
        if str(entry["import_eligibility"]) != MANUAL_REVIEW_REQUIRED:
            continue
        content_hash = str(entry["content_hash"])
        target = scan_by_hash[content_hash]
        manifest = manifest_by_hash[content_hash]
        findings = _sort_findings(target.get("findings", []))
        classification, reason, action = _manual_classification(target)
        queue.append(
            {
                "content_hash": content_hash,
                "representative_source_id": str(
                    manifest["representative_source_id"]
                ),
                "member_source_ids": [
                    str(member) for member in manifest["member_source_ids"]
                ],
                "source_paths": [
                    str(path) for path in manifest["source_paths"]
                ],
                "finding_ids": [
                    str(finding["finding_id"]) for finding in findings
                ],
                "severity_summary": _severity_summary(
                    target.get("severity_counts", {})
                ),
                "review_classification": classification,
                "review_reason": reason,
                "recommended_action": action,
                "review_status": REVIEW_PENDING,
                "import_disposition": IMPORT_DISPOSITION_MANUAL_REVIEW,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "auto_excluded": False,
            }
        )
    return queue


def _import_disposition_for(classification: str) -> str:
    if classification == ELIGIBLE_CANDIDATE:
        return IMPORT_DISPOSITION_IMPORT
    if classification == REDACTION_REQUIRED:
        return IMPORT_DISPOSITION_REDACTED_IMPORT
    return IMPORT_DISPOSITION_MANUAL_REVIEW


def build_approval_manifest(fixtures: dict) -> list[dict]:
    scan_by_hash = _index_by_hash(fixtures["scan_results"]["targets"])
    provenance_by_hash = _index_by_hash(
        fixtures["provenance_evidence"]["entries"]
    )
    manifest_by_hash = _index_by_hash(
        fixtures["manifest_review"]["entries"]
    )

    records: list[dict] = []
    for entry in sorted(
        fixtures["import_eligibility"]["entries"],
        key=lambda item: str(item["content_hash"]),
    ):
        content_hash = str(entry["content_hash"])
        target = scan_by_hash[content_hash]
        provenance = provenance_by_hash[content_hash]
        manifest = manifest_by_hash[content_hash]
        classification = str(entry["import_eligibility"])
        is_redaction = classification == REDACTION_REQUIRED
        is_manual = classification == MANUAL_REVIEW_REQUIRED
        records.append(
            {
                "content_hash": content_hash,
                "representative_source_id": str(
                    manifest["representative_source_id"]
                ),
                "member_source_ids": [
                    str(member) for member in manifest["member_source_ids"]
                ],
                "source_paths": [
                    str(path) for path in manifest["source_paths"]
                ],
                "provenance_status": str(
                    provenance.get("provenance_status") or PROVENANCE_UNKNOWN
                ),
                "provenance_classification": str(
                    provenance.get("classification") or PROVENANCE_UNKNOWN
                ),
                "provenance_confirmed": bool(
                    provenance.get("confirmed", False)
                ),
                "scan_status": str(target["scan_status"]),
                "finding_count": int(target["finding_count"]),
                "import_eligibility": classification,
                "import_disposition": _import_disposition_for(classification),
                "redaction_status": (
                    REDACTION_STATUS_NOT_APPLIED
                    if is_redaction
                    else REDACTION_STATUS_NOT_REQUIRED
                ),
                "manual_review_status": (
                    REVIEW_PENDING if is_manual else REVIEW_STATUS_NOT_REQUIRED
                ),
                "approval_status": APPROVAL_PENDING,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "source_truth_class": str(
                    provenance.get("source_truth_class") or SOURCE_TRUTH_CLASS
                ),
                "authority_scope": str(
                    provenance.get("authority_scope") or AUTHORITY_SCOPE
                ),
                "historical_record": bool(
                    provenance.get("historical_record", True)
                ),
                "historical_runtime_authority": bool(
                    provenance.get("historical_runtime_authority", False)
                ),
            }
        )
    return records


def _read_configured_destination(
    config_source_path: str | Path,
) -> str | None:
    path = Path(config_source_path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(
        r"PRODUCTION_STORE_PATH\s*=\s*Path\(\s*[\"']([^\"']+)[\"']",
        text,
    )
    return match.group(1) if match else None


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def review_import_destination(
    store_path: str | Path = DEFAULT_DESTINATION_PATH,
    *,
    config_source_path: str | Path = DEFAULT_DESTINATION_CONFIG_PATH,
    inspect_schema: bool = True,
) -> dict:
    """Inspect the knowledge-hub destination strictly read-only.

    The database is never opened for writing, never migrated, and never
    created. If it does not exist, it stays non-existent.
    """

    expected_path = str(DEFAULT_DESTINATION_PATH)
    configured_path = _read_configured_destination(config_source_path)
    store = Path(store_path)
    exists = store.exists() and store.is_file()
    symlink = store.is_symlink()
    size_bytes: int | None = None
    sha256: str | None = None
    tables: list[str] = []
    records_table_present = False
    record_count: int | None = None
    schema_read = False
    read_only_connection_opened = False

    if exists and not symlink:
        try:
            size_bytes = store.stat().st_size
            sha256 = _file_sha256(store)
        except OSError:
            size_bytes = None
            sha256 = None
        if inspect_schema:
            connection = None
            try:
                uri = f"file:{store}?mode=ro"
                connection = sqlite3.connect(uri, uri=True)
                read_only_connection_opened = True
                connection.execute("PRAGMA query_only=ON")
                tables = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' ORDER BY name"
                    )
                ]
                records_table_present = "records" in tables
                if records_table_present:
                    record_count = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM records"
                        ).fetchone()[0]
                    )
                schema_read = True
            except sqlite3.Error:
                schema_read = False
            finally:
                if connection is not None:
                    connection.close()

    matches_expected = configured_path == expected_path and str(store) == expected_path
    if exists and records_table_present and matches_expected:
        status = DESTINATION_STATUS_CONFIRMED
    elif exists:
        status = DESTINATION_STATUS_REVIEW
    else:
        status = DESTINATION_STATUS_MISSING

    return {
        "expected_store_path": expected_path,
        "configured_store_path": configured_path,
        "reviewed_store_path": str(store),
        "configured_path_matches_expected": configured_path == expected_path,
        "reviewed_path_matches_expected": str(store) == expected_path,
        "store_exists": exists,
        "store_is_symlink": symlink,
        "store_size_bytes": size_bytes,
        "store_sha256": sha256,
        "schema_read": schema_read,
        "schema_tables": tables,
        "records_table_present": records_table_present,
        "record_count": record_count,
        "read_only_connection_opened": read_only_connection_opened,
        "write_connection_opened": False,
        "database_created": False,
        "database_migrated": False,
        "database_written": False,
        "status": status,
    }


def build_result(
    fixtures: dict,
    *,
    generated_at: str | None = None,
    expected: dict | None = None,
    destination: dict | None = None,
) -> dict:
    timestamp = generated_at or _now_iso()
    validate_shapes(fixtures)
    reconciliation = reconcile(fixtures, expected=expected)
    if not reconciliation["valid"]:
        raise InputError(
            BLOCKED_INVALID_INPUT,
            "reconciliation",
            "; ".join(item["key"] for item in reconciliation["mismatches"][:10]),
        )

    baseline = dict(EXPECTED_BASELINE)
    if expected:
        baseline.update(expected)

    candidates = build_eligible_candidates(fixtures)
    disposition = build_secret_finding_disposition(fixtures)
    redaction_plan = build_redaction_plan(fixtures)
    manual_queue = build_manual_review_queue(fixtures)
    manifest = build_approval_manifest(fixtures)
    destination_review = destination or review_import_destination()

    _require(
        len(candidates) == baseline["ELIGIBLE_CANDIDATE_COUNT"],
        "eligible_candidates",
        f"expected {baseline['ELIGIBLE_CANDIDATE_COUNT']}, got {len(candidates)}",
    )
    _require(
        len(redaction_plan) == baseline["REDACTION_REQUIRED_COUNT"],
        "redaction_plan",
        f"expected {baseline['REDACTION_REQUIRED_COUNT']}, got {len(redaction_plan)}",
    )
    _require(
        len(manual_queue) == baseline["MANUAL_REVIEW_REQUIRED_COUNT"],
        "manual_review_queue",
        f"expected {baseline['MANUAL_REVIEW_REQUIRED_COUNT']}, got {len(manual_queue)}",
    )
    _require(
        len(disposition) == baseline["SECRET_FINDING_COUNT"],
        "secret_finding_disposition",
        f"expected {baseline['SECRET_FINDING_COUNT']}, got {len(disposition)}",
    )
    _require(
        len(manifest) == baseline["FINAL_APPROVAL_MANIFEST_COUNT"],
        "approval_manifest",
        f"expected {baseline['FINAL_APPROVAL_MANIFEST_COUNT']}, got {len(manifest)}",
    )

    if any(record["approved"] for record in manifest):
        raise SecurityBoundaryError("approved must remain false")
    if any(record["import_ready"] for record in manifest):
        raise SecurityBoundaryError("import_ready must remain false")
    if any(record["real_import_allowed"] for record in manifest):
        raise SecurityBoundaryError("real_import_allowed must remain false")
    if any(record["historical_runtime_authority"] for record in manifest):
        raise SecurityBoundaryError(
            "historical_runtime_authority must remain false"
        )
    if any(
        record["source_truth_class"] != SOURCE_TRUTH_CLASS for record in manifest
    ):
        raise SecurityBoundaryError("source_truth_class must remain AGENT_REPORTED")
    if any(record["authority_scope"] != AUTHORITY_SCOPE for record in manifest):
        raise SecurityBoundaryError("authority_scope must remain NONE")

    disposition_counts = _count_by(disposition, "review_disposition")
    manual_class_counts = _count_by(manual_queue, "review_classification")

    manifest_member_total = sum(
        len(record["member_source_ids"]) for record in manifest
    )
    manifest_path_total = sum(len(record["source_paths"]) for record in manifest)
    _require(
        manifest_member_total == baseline["SOURCE_REFERENCE_COUNT"],
        "approval_manifest",
        "member source reference total mismatch",
    )
    _require(
        manifest_path_total == baseline["SOURCE_REFERENCE_COUNT"],
        "approval_manifest",
        "source path total mismatch",
    )
    _require(
        len({record["content_hash"] for record in manifest})
        == baseline["FINAL_APPROVAL_MANIFEST_COUNT"],
        "approval_manifest",
        "duplicate content hash in manifest",
    )

    unresolved_review_count = disposition_counts.get(
        DISPOSITION_UNRESOLVED, 0
    ) + manual_class_counts.get(MANUAL_CLASS_INSUFFICIENT_EVIDENCE, 0)

    counts = {
        "CONTENT_UNIQUE_COUNT": reconciliation["counts"]["CONTENT_UNIQUE_COUNT"],
        "SOURCE_REFERENCE_COUNT": reconciliation["counts"][
            "SOURCE_REFERENCE_COUNT"
        ],
        "ELIGIBLE_CANDIDATE_COUNT": len(candidates),
        "REDACTION_REQUIRED_COUNT": len(redaction_plan),
        "MANUAL_REVIEW_REQUIRED_COUNT": len(manual_queue),
        "SECRET_FINDING_COUNT": len(disposition),
        "PROVENANCE_CONFIRMED_COUNT": reconciliation["counts"][
            "PROVENANCE_CONFIRMED_COUNT"
        ],
        "PROVENANCE_UNKNOWN_COUNT": reconciliation["counts"][
            "PROVENANCE_UNKNOWN_COUNT"
        ],
        "FINAL_APPROVAL_MANIFEST_COUNT": len(manifest),
        "UNRESOLVED_REVIEW_COUNT": unresolved_review_count,
        "REDACTION_DISPOSITION_COUNT": disposition_counts.get(
            DISPOSITION_REDACTION_REQUIRED, 0
        ),
        "MANUAL_DISPOSITION_COUNT": disposition_counts.get(
            DISPOSITION_MANUAL_REVIEW_REQUIRED, 0
        ),
        "POSSIBLE_FALSE_POSITIVE_FINDING_COUNT": disposition_counts.get(
            DISPOSITION_POSSIBLE_FALSE_POSITIVE, 0
        ),
        "UNRESOLVED_FINDING_COUNT": disposition_counts.get(
            DISPOSITION_UNRESOLVED, 0
        ),
        "MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT": manual_class_counts.get(
            MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE, 0
        ),
        "MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT": manual_class_counts.get(
            MANUAL_CLASS_REDACTION_RECOMMENDED, 0
        ),
        "MANUAL_CLASS_INSUFFICIENT_EVIDENCE_COUNT": manual_class_counts.get(
            MANUAL_CLASS_INSUFFICIENT_EVIDENCE, 0
        ),
        "MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW_COUNT": manual_class_counts.get(
            MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW, 0
        ),
    }

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
        "FINAL_APPROVAL_MANIFEST_COUNT": counts[
            "FINAL_APPROVAL_MANIFEST_COUNT"
        ],
        "ALL_APPROVED_FALSE": all(
            record["approved"] is False for record in manifest
        ),
        "ALL_IMPORT_READY_FALSE": all(
            record["import_ready"] is False for record in manifest
        ),
        "ALL_REAL_IMPORT_ALLOWED_FALSE": all(
            record["real_import_allowed"] is False for record in manifest
        ),
        "APPROVAL_REQUEST_CREATED": True,
        "NO_SECRET_VALUES_EXPORTED": True,
        "NO_REAL_IMPORT": True,
        "NO_PRODUCTION_WRITE": True,
        "CANONICAL_UNCHANGED": True,
    }

    verdict = (
        VERDICT_READY
        if (
            acceptance["ALL_APPROVED_FALSE"]
            and acceptance["ALL_IMPORT_READY_FALSE"]
            and acceptance["ALL_REAL_IMPORT_ALLOWED_FALSE"]
        )
        else VERDICT_SECURITY_BLOCKED
    )

    return {
        "task_id": TASK_ID,
        "verdict": verdict,
        "mode": MODE,
        "generated_at": timestamp,
        "reconciliation": reconciliation,
        "counts": counts,
        "acceptance": acceptance,
        "eligible_candidates": candidates,
        "secret_finding_disposition": disposition,
        "redaction_review_plan": redaction_plan,
        "manual_review_queue": manual_queue,
        "final_approval_manifest": manifest,
        "destination": destination_review,
        "safety": {
            "source_files_modified": False,
            "source_body_stored": False,
            "secret_values_stored": False,
            "secret_value_hash_stored": False,
            "real_import_executed": False,
            "production_database_opened_for_write": False,
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


def build_outputs(result: dict) -> dict[str, dict | str]:
    eligible_payload = _payload_header(
        ELIGIBLE_SCHEMA_VERSION,
        result,
        count=len(result["eligible_candidates"]),
        candidates=result["eligible_candidates"],
    )
    disposition_payload = _payload_header(
        DISPOSITION_SCHEMA_VERSION,
        result,
        count=len(result["secret_finding_disposition"]),
        findings=result["secret_finding_disposition"],
    )
    redaction_payload = _payload_header(
        REDACTION_SCHEMA_VERSION,
        result,
        count=len(result["redaction_review_plan"]),
        plan=result["redaction_review_plan"],
    )
    manual_payload = _payload_header(
        MANUAL_SCHEMA_VERSION,
        result,
        count=len(result["manual_review_queue"]),
        queue=result["manual_review_queue"],
    )
    manifest_payload = _payload_header(
        MANIFEST_SCHEMA_VERSION,
        result,
        count=len(result["final_approval_manifest"]),
        approval_status=APPROVAL_PENDING,
        records=result["final_approval_manifest"],
    )
    return {
        "eligible_candidates": eligible_payload,
        "secret_finding_disposition": disposition_payload,
        "redaction_review_plan": redaction_payload,
        "manual_review_queue": manual_payload,
        "final_approval_manifest": manifest_payload,
        "import_approval_request": render_approval_request(result),
        "final": None,
    }


def render_approval_request(result: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    counts = result["counts"]
    destination = result["destination"]
    acceptance = result["acceptance"]
    lines = [
        "# BC-11E-7B Final Import Approval Request",
        "",
        f"TASK_ID={result['task_id']}",
        f"VERDICT={result['verdict']}",
        f"WORKTREE={meta.get('worktree', 'UNKNOWN')}",
        f"BRANCH={meta.get('branch', 'UNKNOWN')}",
        f"HEAD_BEFORE={meta.get('head_before', 'UNKNOWN')}",
        f"HEAD_AFTER={meta.get('head_after', 'UNKNOWN')}",
        "REAL_IMPORT_APPROVED=NO",
        "PRODUCTION_WRITE_APPROVED=NO",
        "",
        "## 1. Classification of all records",
        "",
        f"- CONTENT_UNIQUE_COUNT={counts['CONTENT_UNIQUE_COUNT']}",
        f"- SOURCE_REFERENCE_COUNT={counts['SOURCE_REFERENCE_COUNT']}",
        f"- ELIGIBLE_CANDIDATE_COUNT={counts['ELIGIBLE_CANDIDATE_COUNT']}",
        f"- REDACTION_REQUIRED_COUNT={counts['REDACTION_REQUIRED_COUNT']}",
        f"- MANUAL_REVIEW_REQUIRED_COUNT={counts['MANUAL_REVIEW_REQUIRED_COUNT']}",
        f"- SECRET_FINDING_COUNT={counts['SECRET_FINDING_COUNT']}",
        f"- FINAL_APPROVAL_MANIFEST_COUNT={counts['FINAL_APPROVAL_MANIFEST_COUNT']}",
        "",
        "## 2. Proposed import candidates (scan completed, no findings)",
        "",
        f"{counts['ELIGIBLE_CANDIDATE_COUNT']} content records are proposed for import.",
        "A no-findings scan does not prove that no secret exists. Every record",
        "remains unapproved until an operator approves this manifest.",
        "",
        "## 3. Redaction candidates",
        "",
        f"{counts['REDACTION_REQUIRED_COUNT']} content records require redaction before",
        "any import. Redaction is planned only; no source file is modified and no",
        "import copy has been generated.",
        "",
        "## 4. Manual review candidates",
        "",
        f"{counts['MANUAL_REVIEW_REQUIRED_COUNT']} content records require operator review.",
        f"- POSSIBLE_FALSE_POSITIVE candidates: "
        f"{counts['MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT']}",
        f"- REDACTION_RECOMMENDED candidates: "
        f"{counts['MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT']}",
        f"- INSUFFICIENT_EVIDENCE candidates: "
        f"{counts['MANUAL_CLASS_INSUFFICIENT_EVIDENCE_COUNT']}",
        f"- IMPORT_EXCLUSION_REVIEW candidates: "
        f"{counts['MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW_COUNT']}",
        "",
        "No record is approved, excluded, or declared a false positive without",
        "an explicit operator decision.",
        "",
        "## 5. Secret finding disposition",
        "",
        f"- REDACTION_REQUIRED findings: {counts['REDACTION_DISPOSITION_COUNT']}",
        f"- MANUAL_REVIEW_REQUIRED findings: {counts['MANUAL_DISPOSITION_COUNT']}",
        f"- POSSIBLE_FALSE_POSITIVE findings: "
        f"{counts['POSSIBLE_FALSE_POSITIVE_FINDING_COUNT']}",
        f"- UNRESOLVED findings: {counts['UNRESOLVED_FINDING_COUNT']}",
        "",
        "No secret value, partial value, surrounding context, or secret-value",
        "hash is included in any BC-11E-7B artifact.",
        "",
        "## 6. Unknown provenance",
        "",
        f"- PROVENANCE_CONFIRMED_COUNT={counts['PROVENANCE_CONFIRMED_COUNT']}",
        f"- PROVENANCE_UNKNOWN_COUNT={counts['PROVENANCE_UNKNOWN_COUNT']}",
        "",
        "Unknown provenance is not, by itself, a reason to forbid import. The",
        "source truth class remains AGENT_REPORTED with authority scope NONE, and",
        "historical_runtime_authority remains false.",
        "",
        "## 7. Import destination review",
        "",
        f"- EXPECTED_STORE_PATH={destination['expected_store_path']}",
        f"- CONFIGURED_STORE_PATH={destination['configured_store_path']}",
        f"- STORE_EXISTS={'YES' if destination['store_exists'] else 'NO'}",
        f"- SCHEMA_READ={'YES' if destination['schema_read'] else 'NO'}",
        f"- RECORDS_TABLE_PRESENT="
        f"{'YES' if destination['records_table_present'] else 'NO'}",
        f"- RECORD_COUNT={destination['record_count']}",
        f"- IMPORT_DESTINATION_STATUS={destination['status']}",
        "- WRITE_CONNECTION_OPENED=NO",
        "- DATABASE_CREATED=NO",
        "- DATABASE_MIGRATED=NO",
        "",
        "## 8. Unresolved items",
        "",
        f"- UNRESOLVED_REVIEW_COUNT={counts['UNRESOLVED_REVIEW_COUNT']}",
        "- Operator approval of the 491-record manifest is outstanding.",
        "- Redaction execution is outstanding for redaction candidates.",
        "- Manual review is outstanding for manual review candidates.",
        "",
        "## 9. Approvals required before any real import",
        "",
        "1. Explicit operator approval of the final 491-record manifest.",
        "2. Explicit operator approval of the redaction execution plan.",
        "3. Explicit operator disposition of every manual review candidate.",
        "4. Explicit operator confirmation of the production destination.",
        "5. A separate approved import execution task with a rollback plan.",
        "",
        "## 10. Recommended next task order",
        "",
        "1. Operator review of the manual review queue.",
        "2. Operator approval of the redaction plan.",
        "3. Operator approval of the final manifest.",
        "4. Separate approved redacted-copy generation task.",
        "5. Separate approved import execution task.",
        "",
        f"ALL_APPROVED_FALSE="
        f"{str(acceptance['ALL_APPROVED_FALSE']).upper()}",
        f"ALL_IMPORT_READY_FALSE="
        f"{str(acceptance['ALL_IMPORT_READY_FALSE']).upper()}",
        f"ALL_REAL_IMPORT_ALLOWED_FALSE="
        f"{str(acceptance['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
        "REAL_IMPORT_EXECUTED=NO",
        "",
    ]
    return "\n".join(lines)


def render_final(result: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    counts = result["counts"]
    acceptance = result["acceptance"]
    destination = result["destination"]
    lines = [
        "# BC-11E-7B Final Import Approval Review",
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
        f"FINAL_APPROVAL_MANIFEST_COUNT="
        f"{counts['FINAL_APPROVAL_MANIFEST_COUNT']}",
        "APPROVAL_REQUEST_CREATED="
        + ("YES" if acceptance["APPROVAL_REQUEST_CREATED"] else "NO"),
        f"IMPORT_DESTINATION_STATUS={destination['status']}",
        f"UNRESOLVED_REVIEW_COUNT={counts['UNRESOLVED_REVIEW_COUNT']}",
        "",
        f"ALL_APPROVED_FALSE="
        f"{str(acceptance['ALL_APPROVED_FALSE']).upper()}",
        f"ALL_IMPORT_READY_FALSE="
        f"{str(acceptance['ALL_IMPORT_READY_FALSE']).upper()}",
        f"ALL_REAL_IMPORT_ALLOWED_FALSE="
        f"{str(acceptance['ALL_REAL_IMPORT_ALLOWED_FALSE']).upper()}",
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
            "BC-11E-7C_OPERATOR_MANUAL_REVIEW_AND_REDACTION_APPROVAL",
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
        "eligible_candidates": target / ELIGIBLE_JSON_NAME,
        "secret_finding_disposition": target / DISPOSITION_JSON_NAME,
        "redaction_review_plan": target / REDACTION_JSON_NAME,
        "manual_review_queue": target / MANUAL_JSON_NAME,
        "final_approval_manifest": target / MANIFEST_JSON_NAME,
        "import_approval_request": target / APPROVAL_REQUEST_MD_NAME,
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
    payloads["import_approval_request"] = render_approval_request(result, meta)
    payloads["final"] = render_final(result, meta)

    for key, path in paths.items():
        payload = payloads[key]
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        _write_private_text(path, text)
    return {key: str(path) for key, path in paths.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scan-results", default=str(DEFAULT_SCAN_RESULTS_PATH)
    )
    parser.add_argument(
        "--secret-findings", default=str(DEFAULT_SECRET_FINDINGS_PATH)
    )
    parser.add_argument(
        "--provenance-evidence",
        default=str(DEFAULT_PROVENANCE_EVIDENCE_PATH),
    )
    parser.add_argument(
        "--import-eligibility", default=str(DEFAULT_IMPORT_ELIGIBILITY_PATH)
    )
    parser.add_argument(
        "--stage-b-final", default=str(DEFAULT_STAGE_B_FINAL_PATH)
    )
    parser.add_argument(
        "--manifest-review", default=str(DEFAULT_MANIFEST_REVIEW_PATH)
    )
    parser.add_argument(
        "--hash-results", default=str(DEFAULT_HASH_RESULTS_PATH)
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--generated-at", default="")
    parser.add_argument(
        "--destination-store", default=str(DEFAULT_DESTINATION_PATH)
    )
    parser.add_argument(
        "--destination-config", default=str(DEFAULT_DESTINATION_CONFIG_PATH)
    )
    parser.add_argument("--skip-schema-review", action="store_true")
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
        default="BC-11E-7C_OPERATOR_MANUAL_REVIEW_AND_REDACTION_APPROVAL",
    )
    return parser


def _fixture_paths(args: argparse.Namespace) -> dict[str, str]:
    return {
        "scan_results": args.scan_results,
        "secret_findings": args.secret_findings,
        "provenance_evidence": args.provenance_evidence,
        "import_eligibility": args.import_eligibility,
        "stage_b_final": args.stage_b_final,
        "manifest_review": args.manifest_review,
        "hash_results": args.hash_results,
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


def load_fixtures(paths: dict[str, str | Path]) -> dict:
    return {
        "scan_results": load_input(paths["scan_results"], "scan_results"),
        "secret_findings": load_input(
            paths["secret_findings"], "secret_findings"
        ),
        "provenance_evidence": load_input(
            paths["provenance_evidence"], "provenance_evidence"
        ),
        "import_eligibility": load_input(
            paths["import_eligibility"], "import_eligibility"
        ),
        "stage_b_final": load_text_reference(
            paths["stage_b_final"], "stage_b_final"
        ),
        "manifest_review": load_input(
            paths["manifest_review"], "manifest_review"
        ),
        "hash_results": load_input(paths["hash_results"], "hash_results"),
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        fixtures = load_fixtures(_fixture_paths(args))
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
        destination = review_import_destination(
            args.destination_store,
            config_source_path=args.destination_config,
            inspect_schema=not args.skip_schema_review,
        )
        result = build_result(
            fixtures,
            generated_at=args.generated_at or None,
            destination=destination,
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
            "destination": result["destination"],
            "outputs": outputs,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
