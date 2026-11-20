"""BC-11E-7C operator review and redaction preparation tests.

Fixtures are synthetic BC-11E-7B payloads held in memory. No test opens a
source report, reads a secret value, imports a record, or touches a database.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_review_and_redaction_preparation as prep  # noqa: E402

GENERATED_AT = "2026-11-10T01:00:00+00:00"
SECRET_DECOY = "SUPER_SECRET_DECOY_VALUE_DO_NOT_SERIALIZE"

TEST_EXPECTED = {
    "CONTENT_UNIQUE_COUNT": 9,
    "SOURCE_REFERENCE_COUNT": 18,
    "ELIGIBLE_CANDIDATE_COUNT": 3,
    "REDACTION_REQUIRED_COUNT": 2,
    "MANUAL_REVIEW_REQUIRED_COUNT": 4,
    "SECRET_FINDING_COUNT": 7,
    "PROVENANCE_CONFIRMED_COUNT": 2,
    "PROVENANCE_UNKNOWN_COUNT": 7,
    "FINAL_APPROVAL_MANIFEST_COUNT": 9,
    "REDACTION_DISPOSITION_COUNT": 3,
    "MANUAL_DISPOSITION_COUNT": 4,
    "MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT": 3,
    "MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT": 1,
}

VERDICT_TEXT = "VERDICT=BC11E7B_FINAL_IMPORT_APPROVAL_REVIEW_READY\n"


def _hash(label: str) -> str:
    return f"{label:0<64}"[:64]


def _manifest_record(label: str, classification: str) -> dict:
    content_hash = _hash(label)
    return {
        "content_hash": content_hash,
        "representative_source_id": f"{label}-src-0",
        "member_source_ids": [f"{label}-src-0", f"{label}-src-1"],
        "source_paths": [
            f"/synthetic/{label}/0.md",
            f"/synthetic/{label}/1.md",
        ],
        "provenance_status": (
            "CONFIRMED" if label in ("e0", "e1") else "UNKNOWN"
        ),
        "scan_status": (
            "SCAN_COMPLETED_NO_FINDINGS"
            if classification == prep.ELIGIBLE_CANDIDATE
            else "SCAN_COMPLETED_FINDINGS"
        ),
        "finding_count": (
            0 if classification == prep.ELIGIBLE_CANDIDATE else 1
        ),
        "import_eligibility": classification,
        "import_disposition": {
            prep.ELIGIBLE_CANDIDATE: prep.IMPORT_DISPOSITION_IMPORT,
            prep.REDACTION_REQUIRED: prep.IMPORT_DISPOSITION_REDACTED_IMPORT,
            prep.MANUAL_REVIEW_REQUIRED: prep.IMPORT_DISPOSITION_MANUAL_REVIEW,
        }[classification],
        "redaction_status": (
            prep.REDACTION_STATUS_NOT_APPLIED
            if classification == prep.REDACTION_REQUIRED
            else "NOT_REQUIRED"
        ),
        "manual_review_status": (
            prep.REVIEW_PENDING
            if classification == prep.MANUAL_REVIEW_REQUIRED
            else "NOT_REQUIRED"
        ),
        "approval_status": prep.APPROVAL_PENDING,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "source_truth_class": prep.SOURCE_TRUTH_CLASS,
        "authority_scope": prep.AUTHORITY_SCOPE,
    }


def _make_inputs() -> dict:
    eligible = [
        {
            "content_hash": _hash(f"e{index}"),
            "representative_source_id": f"e{index}-src-0",
            "member_source_ids": [f"e{index}-src-0", f"e{index}-src-1"],
            "source_paths": [
                f"/synthetic/e{index}/0.md",
                f"/synthetic/e{index}/1.md",
            ],
            "scan_status": "SCAN_COMPLETED_NO_FINDINGS",
            "finding_count": 0,
            "provenance_status": "CONFIRMED" if index < 2 else "UNKNOWN",
            "import_disposition": prep.IMPORT_DISPOSITION_IMPORT,
            "approved": False,
            "import_ready": False,
            "real_import_allowed": False,
        }
        for index in range(3)
    ]

    redaction = [
        {
            "content_hash": _hash("r0"),
            "representative_source_id": "r0-src-0",
            "member_source_ids": ["r0-src-0", "r0-src-1"],
            "source_paths": ["/synthetic/r0/0.md", "/synthetic/r0/1.md"],
            "finding_ids": ["f1"],
            "secret_types": ["PASSWORD"],
            "redaction_required": True,
            "redaction_status": prep.REDACTION_STATUS_NOT_APPLIED,
            "import_disposition": prep.IMPORT_DISPOSITION_REDACTED_IMPORT,
        },
        {
            "content_hash": _hash("r1"),
            "representative_source_id": "r1-src-0",
            "member_source_ids": ["r1-src-0", "r1-src-1"],
            "source_paths": ["/synthetic/r1/0.md", "/synthetic/r1/1.md"],
            "finding_ids": ["f2", "f3"],
            "secret_types": ["PASSWORD", "SESSION_COOKIE"],
            "redaction_required": True,
            "redaction_status": prep.REDACTION_STATUS_NOT_APPLIED,
            "import_disposition": prep.IMPORT_DISPOSITION_REDACTED_IMPORT,
        },
    ]

    manual = []
    for index in range(4):
        classification = (
            prep.MANUAL_CLASS_REDACTION_RECOMMENDED
            if index == 0
            else prep.MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE
        )
        manual.append(
            {
                "content_hash": _hash(f"m{index}"),
                "representative_source_id": f"m{index}-src-0",
                "member_source_ids": [f"m{index}-src-0", f"m{index}-src-1"],
                "source_paths": [
                    f"/synthetic/m{index}/0.md",
                    f"/synthetic/m{index}/1.md",
                ],
                "finding_ids": [f"f{index + 4}"],
                "severity_summary": {"MEDIUM": 1},
                "review_classification": classification,
                "review_reason": "SYNTHETIC_REASON",
                "recommended_action": "OPERATOR_REVIEW",
                "review_status": prep.REVIEW_PENDING,
                "import_disposition": prep.IMPORT_DISPOSITION_MANUAL_REVIEW,
            }
        )

    findings = []
    for index in range(1, 4):
        findings.append(
            {
                "finding_id": f"f{index}",
                "content_hash": _hash("r0" if index == 1 else "r1"),
                "secret_type": "PASSWORD",
                "severity": "HIGH",
                "confidence": "HIGH",
                "review_disposition": prep.DISPOSITION_REDACTION_REQUIRED,
                "review_reason_code": "DETECTOR_REQUIRES_REDACTION_BEFORE_IMPORT",
            }
        )
    for index in range(4, 8):
        findings.append(
            {
                "finding_id": f"f{index}",
                "content_hash": _hash(f"m{index - 4}"),
                "secret_type": "CREDENTIAL_LIKE_TEXT",
                "severity": "MEDIUM",
                "confidence": "LOW",
                "review_disposition": prep.DISPOSITION_MANUAL_REVIEW_REQUIRED,
                "review_reason_code": "LOW_CONFIDENCE_CONTEXT_REQUIRES_OPERATOR_REVIEW",
            }
        )

    manifest = (
        [_manifest_record(f"e{index}", prep.ELIGIBLE_CANDIDATE) for index in range(3)]
        + [_manifest_record("r0", prep.REDACTION_REQUIRED)]
        + [_manifest_record("r1", prep.REDACTION_REQUIRED)]
        + [
            _manifest_record(f"m{index}", prep.MANUAL_REVIEW_REQUIRED)
            for index in range(4)
        ]
    )

    return {
        "eligible": {
            "schema_version": prep.ELIGIBLE_SCHEMA_VERSION,
            "count": len(eligible),
            "candidates": eligible,
            "counts": TEST_EXPECTED,
        },
        "disposition": {
            "schema_version": prep.DISPOSITION_SCHEMA_VERSION,
            "count": len(findings),
            "findings": findings,
            "counts": TEST_EXPECTED,
        },
        "redaction": {
            "schema_version": prep.REDACTION_SCHEMA_VERSION,
            "count": len(redaction),
            "plan": redaction,
            "counts": TEST_EXPECTED,
        },
        "manual": {
            "schema_version": prep.MANUAL_SCHEMA_VERSION,
            "count": len(manual),
            "queue": manual,
            "counts": TEST_EXPECTED,
        },
        "manifest": {
            "schema_version": prep.MANIFEST_SCHEMA_VERSION,
            "count": len(manifest),
            "records": manifest,
            "counts": TEST_EXPECTED,
        },
        "approval_request_text": {
            "path": "/synthetic/BC11E7B_IMPORT_APPROVAL_REQUEST.md",
            "text": VERDICT_TEXT,
        },
        "final_text": {
            "path": "/synthetic/BC11E7B_FINAL.md",
            "text": VERDICT_TEXT,
        },
    }


@pytest.fixture(scope="module")
def inputs() -> dict:
    return _make_inputs()


@pytest.fixture(scope="module")
def result(inputs: dict) -> dict:
    return prep.build_result(
        inputs, generated_at=GENERATED_AT, expected=TEST_EXPECTED
    )


def _mutated(inputs: dict, mutate) -> dict:
    clone = copy.deepcopy(inputs)
    mutate(clone)
    return clone


def test_baseline_constants() -> None:
    assert prep.EXPECTED_BASELINE["CONTENT_UNIQUE_COUNT"] == 491
    assert prep.EXPECTED_BASELINE["SOURCE_REFERENCE_COUNT"] == 6646
    assert prep.EXPECTED_BASELINE["ELIGIBLE_CANDIDATE_COUNT"] == 390
    assert prep.EXPECTED_BASELINE["REDACTION_REQUIRED_COUNT"] == 17
    assert prep.EXPECTED_BASELINE["MANUAL_REVIEW_REQUIRED_COUNT"] == 84
    assert prep.EXPECTED_BASELINE["SECRET_FINDING_COUNT"] == 154


def test_input_validation_missing_input(tmp_path: Path) -> None:
    with pytest.raises(prep.InputError) as excinfo:
        prep.load_input(tmp_path / "missing.json", "eligible")
    assert excinfo.value.code == prep.BLOCKED_MISSING_INPUT


def test_input_validation_invalid_schema(inputs: dict) -> None:
    clone = _mutated(
        inputs,
        lambda data: data["eligible"].__setitem__(
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
    reconciliation = prep.reconcile(clone, expected=TEST_EXPECTED)
    assert reconciliation["valid"] is False
    with pytest.raises(prep.InputError):
        prep.build_result(clone, generated_at=GENERATED_AT, expected=TEST_EXPECTED)


def test_manual_package(result: dict) -> None:
    package = result["manual_review_package"]
    assert len(package) == 4
    assert result["counts"]["MANUAL_PACKAGE_COUNT"] == 4
    for entry in package:
        assert entry["decision_status"] == prep.DECISION_PENDING
        assert entry["review_status"] == prep.REVIEW_PENDING
        assert entry["required_operator_decision"] == "UNASSIGNED"
        assert entry["approved"] is False
        assert entry["auto_excluded"] is False
        assert entry["decision_options"]
    classifications = {entry["review_classification"] for entry in package}
    assert prep.MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE in classifications
    assert prep.MANUAL_CLASS_REDACTION_RECOMMENDED in classifications


def test_redaction_approval_plan(result: dict) -> None:
    plan = result["redaction_approval_plan"]
    assert len(plan) == 2
    assert result["counts"]["REDACTION_APPROVAL_COUNT"] == 2
    for entry in plan:
        assert entry["approval_status"] == prep.APPROVAL_PENDING
        assert entry["redaction_status"] == prep.REDACTION_STATUS_NOT_APPLIED
        assert entry["redaction_applied"] is False
        assert entry["original_file_modified"] is False
        assert entry["import_copy_generated"] is False
        assert entry["requires_rescan_before_execution"] is True
        assert entry["execution_task_required"] is True
        assert entry["approved"] is False


def test_finding_review(result: dict) -> None:
    review = result["finding_disposition_review"]
    assert len(review) == 7
    assert result["counts"]["FINDING_REVIEW_COUNT"] == 7
    assert result["reconciliation"]["counts"]["REDACTION_DISPOSITION_COUNT"] == 3
    assert result["reconciliation"]["counts"]["MANUAL_DISPOSITION_COUNT"] == 4
    for entry in review:
        assert entry["operator_decision_status"] == prep.DECISION_PENDING
        assert entry["operator_disposition"] == "UNASSIGNED"
        assert entry["approved"] is False
        assert entry["value_stored"] is False
        assert entry["context_stored"] is False


def test_import_candidate_summary(result: dict) -> None:
    summary = result["import_candidate_summary"]
    assert summary["count"] == 9
    assert result["counts"]["IMPORT_CANDIDATE_SUMMARY_COUNT"] == 9
    assert summary["by_import_disposition"] == {
        prep.IMPORT_DISPOSITION_IMPORT: 3,
        prep.IMPORT_DISPOSITION_REDACTED_IMPORT: 2,
        prep.IMPORT_DISPOSITION_MANUAL_REVIEW: 4,
    }
    for record in summary["records"]:
        assert record["approval_status"] == prep.APPROVAL_PENDING
        assert record["approved"] is False
        assert record["import_ready"] is False
        assert record["real_import_allowed"] is False


def test_all_approved_false(result: dict) -> None:
    assert result["acceptance"]["ALL_APPROVED_FALSE"] is True
    for key in (
        "manual_review_package",
        "redaction_approval_plan",
        "finding_disposition_review",
    ):
        assert all(entry["approved"] is False for entry in result[key])


def test_all_import_ready_false(result: dict) -> None:
    assert result["acceptance"]["ALL_IMPORT_READY_FALSE"] is True
    for key in (
        "manual_review_package",
        "redaction_approval_plan",
        "finding_disposition_review",
    ):
        assert all(entry["import_ready"] is False for entry in result[key])


def test_all_real_import_allowed_false(result: dict) -> None:
    assert result["acceptance"]["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True
    for key in (
        "manual_review_package",
        "redaction_approval_plan",
        "finding_disposition_review",
    ):
        assert all(entry["real_import_allowed"] is False for entry in result[key])


def test_no_secret_value_serialization(inputs: dict) -> None:
    clone = _mutated(inputs, lambda data: None)
    for finding in clone["disposition"]["findings"]:
        finding["secret_value"] = SECRET_DECOY
        finding["snippet"] = SECRET_DECOY
        finding["value_hash"] = SECRET_DECOY
    result = prep.build_result(
        clone, generated_at=GENERATED_AT, expected=TEST_EXPECTED
    )
    serialized = json.dumps(prep.build_outputs(result), sort_keys=True)
    assert SECRET_DECOY not in serialized
    for entry in result["finding_disposition_review"]:
        assert "secret_value" not in entry
        assert "snippet" not in entry
        assert "value_hash" not in entry


def test_no_real_import_and_no_production_write(result: dict) -> None:
    safety = result["safety"]
    assert safety["real_import_executed"] is False
    assert safety["production_database_opened"] is False
    assert safety["production_database_written"] is False
    assert safety["database_created"] is False
    assert safety["database_migrated"] is False
    assert safety["source_files_read"] is False
    assert safety["source_body_stored"] is False
    assert safety["secret_values_stored"] is False
    assert safety["secret_value_hash_stored"] is False


def test_source_report_not_reread(result: dict) -> None:
    assert result["acceptance"]["SOURCE_REPORT_REREAD"] is False
    assert result["safety"]["source_files_read"] is False


def test_deterministic_output(inputs: dict, result: dict) -> None:
    first = json.dumps(prep.build_outputs(result), sort_keys=True)
    second = json.dumps(prep.build_outputs(result), sort_keys=True)
    assert first == second
    rebuilt = prep.build_result(
        inputs, generated_at=GENERATED_AT, expected=TEST_EXPECTED
    )
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(result, sort_keys=True)


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
            "bc11e7b_commit": "a27081f",
        },
    )
    assert set(outputs) == {
        "manual_review_package",
        "redaction_approval_plan",
        "finding_disposition_review",
        "import_candidate_summary",
        "operator_approval_request",
        "final",
    }
    for path in outputs.values():
        assert Path(path).stat().st_mode & 0o777 == 0o600
    request = Path(outputs["operator_approval_request"]).read_text(encoding="utf-8")
    final = Path(outputs["final"]).read_text(encoding="utf-8")
    for marker in (
        "REAL_IMPORT_APPROVED=NO",
        "PRODUCTION_WRITE_APPROVED=NO",
        "GIT_PUSH_APPROVED=NO",
        "MANUAL_PACKAGE_COUNT=4",
        "REDACTION_APPROVAL_COUNT=2",
        "FINDING_REVIEW_COUNT=7",
    ):
        assert marker in request
    for marker in (
        "VERDICT=BC11E7C_REVIEW_AND_REDACTION_PREPARATION_READY",
        "ALL_APPROVED_FALSE=TRUE",
        "ALL_IMPORT_READY_FALSE=TRUE",
        "ALL_REAL_IMPORT_ALLOWED_FALSE=TRUE",
        "REAL_IMPORT_EXECUTED=NO",
        "SOURCE_REPORT_REREAD=NO",
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
        "eligible": tmp_path / "BC11E7B_ELIGIBLE_IMPORT_CANDIDATES.json",
        "disposition": tmp_path / "BC11E7B_SECRET_FINDING_DISPOSITION.json",
        "redaction": tmp_path / "BC11E7B_REDACTION_REVIEW_PLAN.json",
        "manual": tmp_path / "BC11E7B_MANUAL_REVIEW_QUEUE.json",
        "manifest": tmp_path / "BC11E7B_FINAL_APPROVAL_MANIFEST.json",
        "approval_request": tmp_path / "BC11E7B_IMPORT_APPROVAL_REQUEST.md",
        "bc11e7b_final": tmp_path / "BC11E7B_FINAL.md",
    }
    for key in ("eligible", "disposition", "redaction", "manual", "manifest"):
        payload = dict(inputs[key])
        payload.pop("counts", None)
        paths[key].write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    paths["approval_request"].write_text(VERDICT_TEXT, encoding="utf-8")
    paths["bc11e7b_final"].write_text(VERDICT_TEXT, encoding="utf-8")
    return paths


def test_cli_rejects_synthetic_baseline_mismatch(
    tmp_path: Path, inputs: dict
) -> None:
    paths = _write_input_files(tmp_path, inputs)
    output_dir = tmp_path / "out"
    # The CLI applies the production baseline (491/6646), so a tiny synthetic
    # input must be rejected as an input mismatch rather than partially
    # processed.
    code = prep.main(
        [
            "--eligible",
            str(paths["eligible"]),
            "--disposition",
            str(paths["disposition"]),
            "--redaction",
            str(paths["redaction"]),
            "--manual",
            str(paths["manual"]),
            "--manifest",
            str(paths["manifest"]),
            "--approval-request",
            str(paths["approval_request"]),
            "--bc11e7b-final",
            str(paths["bc11e7b_final"]),
            "--output-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
        ]
    )
    assert code == 2


def test_cli_input_blocked(tmp_path: Path) -> None:
    code = prep.main(
        [
            "--eligible",
            str(tmp_path / "missing.json"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
