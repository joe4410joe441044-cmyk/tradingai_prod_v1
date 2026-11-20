"""BC-11E-7D priority 390 approval preparation tests.

Fixtures are synthetic BC-11E-7B/7C payloads held in memory or written to a
temporary directory. No test opens a source report, reads a secret value,
imports a record, or touches a production database.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_priority_approval_preparation as prep  # noqa: E402

GENERATED_AT = "2026-11-12T00:00:00+00:00"
SECRET_DECOY = "SUPER_SECRET_DECOY_VALUE_DO_NOT_SERIALIZE"

TOTAL_RECORDS = 491
PRIORITY_RECORDS = 390
REDACTION_RECORDS = 17
MANUAL_RECORDS = 84
TOTAL_SOURCE_REFERENCES = 6646
TOTAL_FINDINGS = 154
HIGH_FINDINGS = 29
MEDIUM_FINDINGS = 125

VERDICT_TEXT = "VERDICT=BC11E7C_REVIEW_AND_REDACTION_PREPARATION_READY\n"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


LABELS = (
    [f"e{index}" for index in range(PRIORITY_RECORDS)]
    + [f"r{index}" for index in range(REDACTION_RECORDS)]
    + [f"m{index}" for index in range(MANUAL_RECORDS)]
)
INDEX = {label: position for position, label in enumerate(LABELS)}
DEFERRED_LABELS = [label for label in LABELS if not label.startswith("e")]


def _member_count(label: str) -> int:
    return 14 if INDEX[label] < 263 else 13


def _members(label: str) -> list[str]:
    return [f"{label}-src-{index}" for index in range(_member_count(label))]


def _paths(label: str) -> list[str]:
    return [f"/synthetic/{label}/{index}.md" for index in range(_member_count(label))]


def _classification(label: str) -> str:
    if label.startswith("e"):
        return prep.ELIGIBLE_CANDIDATE
    if label.startswith("r"):
        return prep.REDACTION_REQUIRED
    return prep.MANUAL_REVIEW_REQUIRED


def _manifest_record(label: str) -> dict:
    classification = _classification(label)
    confirmed = label in ("e0", "e1", "e2")
    members = _members(label)
    is_eligible = classification == prep.ELIGIBLE_CANDIDATE
    is_redaction = classification == prep.REDACTION_REQUIRED
    is_manual = classification == prep.MANUAL_REVIEW_REQUIRED
    return {
        "content_hash": _sha(label),
        "representative_source_id": members[0],
        "member_source_ids": members,
        "source_paths": _paths(label),
        "provenance_status": "CONFIRMED" if confirmed else "UNKNOWN",
        "provenance_classification": (
            "OPENCODE_CANDIDATE" if confirmed else "UNKNOWN"
        ),
        "provenance_confirmed": confirmed,
        "scan_status": (
            prep.SCAN_COMPLETED_NO_FINDINGS
            if is_eligible
            else "SCAN_COMPLETED_FINDINGS"
        ),
        "finding_count": 0 if is_eligible else 1,
        "import_eligibility": classification,
        "import_disposition": {
            prep.ELIGIBLE_CANDIDATE: (
                prep.review_prep.IMPORT_DISPOSITION_IMPORT
            ),
            prep.REDACTION_REQUIRED: (
                prep.review_prep.IMPORT_DISPOSITION_REDACTED_IMPORT
            ),
            prep.MANUAL_REVIEW_REQUIRED: (
                prep.review_prep.IMPORT_DISPOSITION_MANUAL_REVIEW
            ),
        }[classification],
        "redaction_status": "NOT_APPLIED" if is_redaction else "NOT_REQUIRED",
        "manual_review_status": (
            "PENDING_OPERATOR_REVIEW" if is_manual else "NOT_REQUIRED"
        ),
        "approval_status": prep.APPROVAL_PENDING,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "source_truth_class": prep.SOURCE_TRUTH_CLASS,
        "authority_scope": prep.AUTHORITY_SCOPE,
        "historical_record": True,
        "historical_runtime_authority": False,
    }


def _eligible_candidate(label: str) -> dict:
    members = _members(label)
    return {
        "content_hash": _sha(label),
        "representative_source_id": members[0],
        "member_source_ids": members,
        "source_paths": _paths(label),
        "scan_status": prep.SCAN_COMPLETED_NO_FINDINGS,
        "finding_count": 0,
        "provenance_status": (
            "CONFIRMED" if label in ("e0", "e1", "e2") else "UNKNOWN"
        ),
        "import_disposition": prep.review_prep.IMPORT_DISPOSITION_IMPORT,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
    }


def _manual_package_entry(label: str) -> dict:
    members = _members(label)
    return {
        "content_hash": _sha(label),
        "representative_source_id": members[0],
        "member_source_ids": members,
        "source_paths": _paths(label),
        "finding_ids": [f"finding-{label}"],
        "severity_summary": {"MEDIUM": 1},
        "review_classification": (
            "POSSIBLE_FALSE_POSITIVE"
            if INDEX[label] % 2 == 0
            else "REDACTION_RECOMMENDED"
        ),
        "review_reason": "SYNTHETIC_REASON",
        "recommended_action": "OPERATOR_REVIEW",
        "review_status": "PENDING_OPERATOR_REVIEW",
        "import_disposition": (
            prep.review_prep.IMPORT_DISPOSITION_MANUAL_REVIEW
        ),
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "auto_excluded": False,
    }


def _redaction_plan_entry(label: str) -> dict:
    members = _members(label)
    return {
        "content_hash": _sha(label),
        "representative_source_id": members[0],
        "member_source_ids": members,
        "source_paths": _paths(label),
        "finding_ids": [f"finding-{label}"],
        "secret_types": ["PASSWORD"],
        "severity_summary": {"HIGH": 1},
        "redaction_required": True,
        "redaction_status": "NOT_APPLIED",
        "import_disposition": (
            prep.review_prep.IMPORT_DISPOSITION_REDACTED_IMPORT
        ),
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
    }


def _findings() -> list[dict]:
    findings: list[dict] = []
    for index in range(TOTAL_FINDINGS):
        label = DEFERRED_LABELS[index % len(DEFERRED_LABELS)]
        severity = "HIGH" if index < HIGH_FINDINGS else "MEDIUM"
        disposition = (
            prep.REDACTION_REQUIRED
            if label.startswith("r")
            else prep.MANUAL_REVIEW_REQUIRED
        )
        findings.append(
            {
                "finding_id": f"finding-{index:03d}",
                "content_hash": _sha(label),
                "secret_type": "PASSWORD",
                "severity": severity,
                "confidence": "HIGH",
                "review_disposition": disposition,
                "review_reason_code": "SYNTHETIC_REASON",
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "secret_value": SECRET_DECOY,
                "snippet": SECRET_DECOY,
                "value_hash": SECRET_DECOY,
            }
        )
    return findings


def _candidate_summary(records: list[dict]) -> dict:
    summary_records = [
        {
            "content_hash": record["content_hash"],
            "representative_source_id": record["representative_source_id"],
            "scan_status": record["scan_status"],
            "finding_count": record["finding_count"],
            "provenance_status": record["provenance_status"],
            "import_disposition": record["import_disposition"],
            "approval_status": record["approval_status"],
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
        }
        for record in records
    ]
    return {
        "schema_version": prep.CANDIDATE_SUMMARY_SCHEMA_VERSION,
        "count": len(summary_records),
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "summary": {
            "count": len(summary_records),
            "records": summary_records,
        },
    }


def _make_inputs() -> dict:
    records = [_manifest_record(label) for label in LABELS]
    eligible = [
        _eligible_candidate(label)
        for label in LABELS
        if label.startswith("e")
    ]
    manual = [
        _manual_package_entry(label)
        for label in LABELS
        if label.startswith("m")
    ]
    redaction = [
        _redaction_plan_entry(label)
        for label in LABELS
        if label.startswith("r")
    ]
    findings = _findings()
    return {
        "manifest": {
            "schema_version": prep.MANIFEST_SCHEMA_VERSION,
            "count": len(records),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
            "records": records,
        },
        "eligible": {
            "schema_version": prep.ELIGIBLE_SCHEMA_VERSION,
            "count": len(eligible),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
            "candidates": eligible,
        },
        "candidate_summary": _candidate_summary(records),
        "manual_package": {
            "schema_version": prep.MANUAL_PACKAGE_SCHEMA_VERSION,
            "count": len(manual),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
            "package": manual,
        },
        "redaction_plan": {
            "schema_version": prep.REDACTION_APPROVAL_SCHEMA_VERSION,
            "count": len(redaction),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
            "plan": redaction,
        },
        "finding_review": {
            "schema_version": prep.FINDING_REVIEW_SCHEMA_VERSION,
            "count": len(findings),
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
            "findings": findings,
        },
        "operator_request_text": {
            "path": "/synthetic/BC11E7C_OPERATOR_APPROVAL_REQUEST.md",
            "text": VERDICT_TEXT,
        },
    }


@pytest.fixture(scope="module")
def inputs() -> dict:
    return _make_inputs()


@pytest.fixture(scope="module")
def result(inputs: dict) -> dict:
    return prep.build_result(inputs, generated_at=GENERATED_AT)


def _mutated(inputs: dict, mutate) -> dict:
    clone = copy.deepcopy(inputs)
    mutate(clone)
    return clone


def test_baseline_constants() -> None:
    assert prep.EXPECTED_BASELINE["TOTAL_CONTENT_UNIQUE"] == 491
    assert prep.EXPECTED_BASELINE["TOTAL_SOURCE_REFERENCES"] == 6646
    assert prep.EXPECTED_BASELINE["PRIORITY_CANDIDATES"] == 390
    assert prep.EXPECTED_BASELINE["DEFERRED_CANDIDATES"] == 101
    assert prep.EXPECTED_BASELINE["REDACTION_REQUIRED"] == 17
    assert prep.EXPECTED_BASELINE["MANUAL_REVIEW_REQUIRED"] == 84
    assert prep.EXPECTED_BASELINE["SECRET_FINDINGS"] == 154


def test_priority_candidate_selection(result: dict) -> None:
    priority = result["priority_manifest"]
    assert len(priority) == PRIORITY_RECORDS
    assert result["counts"]["PRIORITY_COUNT"] == PRIORITY_RECORDS
    hashes = [entry["content_hash"] for entry in priority]
    assert len(hashes) == len(set(hashes))
    for entry in priority:
        assert entry["import_eligibility"] == prep.ELIGIBLE_CANDIDATE
        assert entry["scan_status"] == prep.SCAN_COMPLETED_NO_FINDINGS
        assert entry["finding_count"] == 0
        assert entry["priority_group"] == prep.PRIORITY_GROUP
        assert entry["approval_status"] == prep.APPROVAL_PENDING
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False
        assert entry["source_truth_class"] == prep.SOURCE_TRUTH_CLASS
        assert entry["authority_scope"] == prep.AUTHORITY_SCOPE
        assert entry["historical_record"] is True
        assert entry["historical_runtime_authority"] is False


def test_deferred_candidate_selection(result: dict) -> None:
    deferred = result["deferred_manifest"]
    assert len(deferred) == REDACTION_RECORDS + MANUAL_RECORDS
    assert result["counts"]["DEFERRED_COUNT"] == 101
    assert result["counts"]["REDACTION_DEFERRED_COUNT"] == REDACTION_RECORDS
    assert result["counts"]["MANUAL_REVIEW_DEFERRED_COUNT"] == MANUAL_RECORDS
    groups = [entry["deferred_group"] for entry in deferred]
    assert groups.count(prep.DEFERRED_REDACTION_GROUP) == REDACTION_RECORDS
    assert groups.count(prep.DEFERRED_MANUAL_REVIEW_GROUP) == MANUAL_RECORDS
    for entry in deferred:
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False
        assert entry["approval_status"] == prep.APPROVAL_PENDING
        assert entry["finding_ids"]
        assert entry["provenance_status"] in ("CONFIRMED", "UNKNOWN")


def test_reconciliation(result: dict) -> None:
    checks = result["reconciliation"]["checks"]
    assert result["reconciliation"]["valid"] is True
    assert checks["PRIORITY_COUNT"] == 390
    assert checks["DEFERRED_COUNT"] == 101
    assert checks["PRIORITY_PLUS_DEFERRED"] == 491
    assert checks["PRIORITY_HASH_DUPLICATES"] == 0
    assert checks["DEFERRED_HASH_DUPLICATES"] == 0
    assert checks["PRIORITY_DEFERRED_OVERLAP"] == 0
    assert checks["UNION_EQUALS_ORIGINAL_MANIFEST"] is True
    assert checks["SOURCE_REFERENCE_TOTAL"] == 6646
    assert checks["SOURCE_REFERENCE_LOSS"] == 0
    assert checks["SOURCE_PATH_LOSS"] == 0
    assert checks["PROVENANCE_LOSS"] == 0
    assert checks["HISTORICAL_AUTHORITY_ESCALATION"] == 0
    assert checks["APPROVAL_FLAG_CHANGES"] == 0


def test_reconciliation_detects_overlap(inputs: dict, result: dict) -> None:
    priority = result["priority_manifest"]
    deferred = result["deferred_manifest"]
    overlapping = deferred[:-1] + [priority[0]]
    reconciliation = prep.reconcile(inputs, priority, overlapping)
    assert reconciliation["valid"] is False
    assert reconciliation["checks"]["PRIORITY_DEFERRED_OVERLAP"] == 1


def test_no_source_or_provenance_loss(inputs: dict, result: dict) -> None:
    original = inputs["manifest"]["records"]
    combined = result["priority_manifest"] + result["deferred_manifest"]
    original_references = sum(
        len(record["member_source_ids"]) for record in original
    )
    combined_references = sum(
        len(record["member_source_ids"]) for record in combined
    )
    assert original_references == 6646
    assert combined_references == 6646
    original_provenance = {
        record["content_hash"]: record["provenance_status"]
        for record in original
    }
    combined_provenance = {
        record["content_hash"]: record["provenance_status"]
        for record in combined
    }
    assert original_provenance == combined_provenance


def test_all_approval_flags_false(result: dict) -> None:
    acceptance = result["acceptance"]
    assert acceptance["ALL_APPROVED_FALSE"] is True
    assert acceptance["ALL_IMPORT_READY_FALSE"] is True
    assert acceptance["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True
    assert acceptance["HISTORICAL_RUNTIME_AUTHORITY_FALSE"] is True
    assert acceptance["NO_REAL_IMPORT"] is True
    assert acceptance["NO_PRODUCTION_WRITE"] is True
    for entry in result["priority_manifest"] + result["deferred_manifest"]:
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False
    assert result["safety"]["real_import_executed"] is False
    assert result["safety"]["production_database_written"] is False
    assert result["safety"]["source_files_read"] is False


def test_safety_review(result: dict) -> None:
    review = result["safety_review"]
    assert review["count"] == PRIORITY_RECORDS
    assert all(review["summary"].values())
    assert "does not prove" in review["note"]
    for record in review["records"]:
        assert record["secret_scan_completed"] is True
        assert record["no_findings"] is True
        assert record["source_hash_present"] is True
        assert record["matches_existing_manifest"] is True
        assert record["matches_eligible_candidates"] is True


def test_no_secret_value_serialization(inputs: dict) -> None:
    clone = _mutated(inputs, lambda data: None)
    for record in clone["manifest"]["records"]:
        record["secret_value"] = SECRET_DECOY
        record["source_body"] = SECRET_DECOY
    for finding in clone["finding_review"]["findings"]:
        finding["secret_value"] = SECRET_DECOY
        finding["snippet"] = SECRET_DECOY
        finding["value_hash"] = SECRET_DECOY
    built = prep.build_result(clone, generated_at=GENERATED_AT)
    serialized = json.dumps(prep.build_outputs(built), sort_keys=True)
    assert SECRET_DECOY not in serialized
    assert '"secret_value"' not in serialized
    assert '"snippet"' not in serialized
    assert '"source_body"' not in serialized


def test_input_approval_escalation_rejected(inputs: dict) -> None:
    clone = _mutated(
        inputs,
        lambda data: data["manifest"]["records"][0].__setitem__(
            "approved", True
        ),
    )
    with pytest.raises(prep.InputError):
        prep.build_result(clone, generated_at=GENERATED_AT)


def test_input_historical_authority_escalation_rejected(inputs: dict) -> None:
    clone = _mutated(
        inputs,
        lambda data: data["manifest"]["records"][0].__setitem__(
            "historical_runtime_authority", True
        ),
    )
    with pytest.raises(prep.InputError):
        prep.build_result(clone, generated_at=GENERATED_AT)


def test_input_validation_missing_input(tmp_path: Path) -> None:
    with pytest.raises(prep.InputError) as excinfo:
        prep.load_inputs(
            {
                "manifest": str(tmp_path / "missing.json"),
                "eligible": str(tmp_path / "missing.json"),
                "candidate_summary": str(tmp_path / "missing.json"),
                "manual_package": str(tmp_path / "missing.json"),
                "redaction_plan": str(tmp_path / "missing.json"),
                "finding_review": str(tmp_path / "missing.json"),
                "operator_request": str(tmp_path / "missing.md"),
            }
        )
    assert excinfo.value.code == prep.BLOCKED_MISSING_INPUT


def test_input_validation_invalid_schema(inputs: dict) -> None:
    clone = _mutated(
        inputs,
        lambda data: data["manifest"].__setitem__(
            "schema_version", "unexpected"
        ),
    )
    with pytest.raises(prep.InputError) as excinfo:
        prep.validate_shapes(clone)
    assert excinfo.value.code == prep.BLOCKED_INVALID_INPUT


def test_input_validation_reconciliation_mismatch(inputs: dict) -> None:
    clone = _mutated(
        inputs, lambda data: data["manifest"]["records"].pop()
    )
    with pytest.raises(prep.InputError):
        prep.build_result(clone, generated_at=GENERATED_AT)


def test_input_validation_source_reference_loss(inputs: dict) -> None:
    def mutate(data: dict) -> None:
        data["manifest"]["records"][0]["member_source_ids"].pop()

    clone = _mutated(inputs, mutate)
    with pytest.raises(prep.InputError):
        prep.build_result(clone, generated_at=GENERATED_AT)


def test_deterministic_output(inputs: dict, result: dict) -> None:
    first = json.dumps(prep.build_outputs(result), sort_keys=True)
    second = json.dumps(prep.build_outputs(result), sort_keys=True)
    assert first == second
    rebuilt = prep.build_result(inputs, generated_at=GENERATED_AT)
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(
        result, sort_keys=True
    )


def test_write_outputs_and_permissions(tmp_path: Path, result: dict) -> None:
    outputs = prep.write_outputs(
        result,
        output_dir=tmp_path,
        meta={
            "worktree": "/synthetic/worktree",
            "branch": "feature/synthetic",
            "head_before": "a" * 7,
            "head_after": "b" * 7,
            "test_results": "PASS",
            "changed_files": "scripts/example.py,tests/test_example.py",
            "commit": "c" * 7,
        },
    )
    assert set(outputs) == {
        "priority_manifest",
        "deferred_manifest",
        "reconciliation",
        "pre_import_safety_review",
        "priority_approval_request",
        "final",
    }
    for path in outputs.values():
        assert Path(path).stat().st_mode & 0o777 == 0o600
    request = Path(outputs["priority_approval_request"]).read_text(
        encoding="utf-8"
    )
    final = Path(outputs["final"]).read_text(encoding="utf-8")
    for marker in (
        "REAL_IMPORT_APPROVED=NO",
        "RECORD_IMPORT_APPROVED=NO",
        "PRODUCTION_WRITE_APPROVED=NO",
        "REDACTION_EXECUTION_APPROVED=NO",
        "MANUAL_REVIEW_DISPOSITION_APPROVED=NO",
        "PRIORITY_CANDIDATE_COUNT=390",
        "DEFERRED_CANDIDATE_COUNT=101",
        "REDACTION_DEFERRED_COUNT=17",
        "MANUAL_REVIEW_DEFERRED_COUNT=84",
    ):
        assert marker in request
    for marker in (
        "VERDICT=BC11E7D_PRIORITY_390_APPROVAL_PREPARATION_READY",
        "PRIORITY_CANDIDATE_COUNT=390",
        "DEFERRED_CANDIDATE_COUNT=101",
        "CONTENT_UNIQUE_COUNT=491",
        "SOURCE_REFERENCE_COUNT=6646",
        "PRIORITY_DEFERRED_OVERLAP=0",
        "SOURCE_REFERENCE_LOSS=0",
        "PROVENANCE_LOSS=0",
        "ALL_APPROVED_FALSE=TRUE",
        "ALL_IMPORT_READY_FALSE=TRUE",
        "ALL_REAL_IMPORT_ALLOWED_FALSE=TRUE",
        "HISTORICAL_RUNTIME_AUTHORITY_FALSE=TRUE",
        "REAL_IMPORT_EXECUTED=NO",
        "GIT_PUSH=NO",
    ):
        assert marker in final


def test_write_outputs_refuses_existing(tmp_path: Path, result: dict) -> None:
    prep.write_outputs(result, output_dir=tmp_path)
    with pytest.raises(prep.InputError) as excinfo:
        prep.write_outputs(result, output_dir=tmp_path)
    assert excinfo.value.code == prep.BLOCKED_EXISTING_OUTPUT


def _write_input_files(tmp_path: Path, inputs: dict) -> dict[str, Path]:
    paths = {
        "manifest": tmp_path / "BC11E7B_FINAL_APPROVAL_MANIFEST.json",
        "eligible": tmp_path / "BC11E7B_ELIGIBLE_IMPORT_CANDIDATES.json",
        "candidate_summary": tmp_path
        / "BC11E7C_IMPORT_CANDIDATE_SUMMARY.json",
        "manual_package": tmp_path / "BC11E7C_MANUAL_REVIEW_PACKAGE.json",
        "redaction_plan": tmp_path / "BC11E7C_REDACTION_APPROVAL_PLAN.json",
        "finding_review": tmp_path
        / "BC11E7C_FINDING_DISPOSITION_REVIEW.json",
        "operator_request": tmp_path
        / "BC11E7C_OPERATOR_APPROVAL_REQUEST.md",
    }
    for key in (
        "manifest",
        "eligible",
        "candidate_summary",
        "manual_package",
        "redaction_plan",
        "finding_review",
    ):
        paths[key].write_text(
            json.dumps(inputs[key], indent=2), encoding="utf-8"
        )
    paths["operator_request"].write_text(VERDICT_TEXT, encoding="utf-8")
    return paths


def _cli_args(paths: dict[str, Path], output_dir: Path) -> list[str]:
    return [
        "--manifest",
        str(paths["manifest"]),
        "--eligible",
        str(paths["eligible"]),
        "--candidate-summary",
        str(paths["candidate_summary"]),
        "--manual-package",
        str(paths["manual_package"]),
        "--redaction-plan",
        str(paths["redaction_plan"]),
        "--finding-review",
        str(paths["finding_review"]),
        "--operator-request",
        str(paths["operator_request"]),
        "--output-dir",
        str(output_dir),
        "--generated-at",
        GENERATED_AT,
    ]


def test_cli_success(tmp_path: Path, inputs: dict) -> None:
    paths = _write_input_files(tmp_path, inputs)
    output_dir = tmp_path / "out"
    code = prep.main(_cli_args(paths, output_dir))
    assert code == 0
    assert (output_dir / prep.PRIORITY_JSON_NAME).exists()
    assert (output_dir / prep.DEFERRED_JSON_NAME).exists()
    assert (output_dir / prep.RECONCILIATION_JSON_NAME).exists()
    assert (output_dir / prep.SAFETY_JSON_NAME).exists()
    assert (output_dir / prep.APPROVAL_REQUEST_MD_NAME).exists()
    assert (output_dir / prep.FINAL_MD_NAME).exists()


def test_cli_input_blocked(tmp_path: Path) -> None:
    code = prep.main(
        [
            "--manifest",
            str(tmp_path / "missing.json"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
