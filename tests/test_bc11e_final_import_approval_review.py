"""BC-11E-7B final import approval review tests.

Every fixture here is synthetic and in-memory. No test opens a real report
body, imports a record, or writes to production. Destination review tests use
temporary SQLite databases only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_final_import_approval_review as app  # noqa: E402

GENERATED_AT = "2026-11-10T00:00:00+00:00"
SECRET_DECOY = "SUPER_SECRET_DECOY_VALUE_DO_NOT_SERIALIZE"
TOTAL_TARGETS = 491
TOTAL_REFERENCES = 6646


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _finding(
    content_hash: str,
    index: int,
    *,
    severity: str,
    confidence: str,
    action: str,
    secret_type: str,
    method: str,
) -> dict:
    return {
        "finding_id": f"secfind_{index:06d}",
        "content_hash": content_hash,
        "secret_type": secret_type,
        "severity": severity,
        "confidence": confidence,
        "default_action": action,
        "detection_method": method,
        "line_number": index + 1,
        "review_status": "NOT_REVIEWED",
        "value_stored": False,
    }


def _severity_counts(findings: list[dict]) -> dict[str, int]:
    counts = {name: 0 for name in app.SEVERITY_ORDER}
    for finding in findings:
        counts[finding["severity"]] += 1
    return counts


def _manual_findings(content_hash: str, counter: list[int], high: int, medium: int):
    findings: list[dict] = []
    for _ in range(high):
        counter[0] += 1
        findings.append(
            _finding(
                content_hash,
                counter[0],
                severity="HIGH",
                confidence="HIGH",
                action="REDACT_BEFORE_IMPORT",
                secret_type="PASSWORD",
                method="KEY_VALUE_ASSIGNMENT",
            )
        )
    for _ in range(medium):
        counter[0] += 1
        findings.append(
            _finding(
                content_hash,
                counter[0],
                severity="MEDIUM",
                confidence="LOW",
                action="REVIEW_REQUIRED",
                secret_type="CREDENTIAL_LIKE_TEXT",
                method="CREDENTIAL_LIKE_CONTEXT",
            )
        )
    return findings


def _build_specs() -> list[dict]:
    specs: list[dict] = []
    counter = [0]

    for index in range(390):
        content_hash = _sha(f"eligible-{index:04d}")
        specs.append(
            {
                "content_hash": content_hash,
                "classification": app.ELIGIBLE_CANDIDATE,
                "scan_status": app.SCAN_COMPLETED_NO_FINDINGS,
                "findings": [],
                "provenance_status": (
                    app.PROVENANCE_CONFIRMED if index < 3 else app.PROVENANCE_UNKNOWN
                ),
                "provenance_classification": (
                    "OTHER_AGENT_CANDIDATE"
                    if index < 3
                    else app.PROVENANCE_UNKNOWN
                ),
            }
        )

    for index in range(17):
        content_hash = _sha(f"redaction-{index:04d}")
        high = 2 if index < 5 else 1
        findings = []
        for _ in range(high):
            counter[0] += 1
            findings.append(
                _finding(
                    content_hash,
                    counter[0],
                    severity="HIGH",
                    confidence="HIGH",
                    action="REDACT_BEFORE_IMPORT",
                    secret_type="PASSWORD",
                    method="KEY_VALUE_ASSIGNMENT",
                )
            )
        specs.append(
            {
                "content_hash": content_hash,
                "classification": app.REDACTION_REQUIRED,
                "scan_status": app.SCAN_COMPLETED_FINDINGS,
                "findings": findings,
                "provenance_status": app.PROVENANCE_UNKNOWN,
                "provenance_classification": app.PROVENANCE_UNKNOWN,
            }
        )

    for index in range(79):
        content_hash = _sha(f"manual-low-{index:04d}")
        low = 2 if index < 39 else 1
        findings = _manual_findings(content_hash, counter, 0, low)
        specs.append(
            {
                "content_hash": content_hash,
                "classification": app.MANUAL_REVIEW_REQUIRED,
                "scan_status": app.SCAN_COMPLETED_FINDINGS,
                "findings": findings,
                "provenance_status": app.PROVENANCE_UNKNOWN,
                "provenance_classification": app.PROVENANCE_UNKNOWN,
            }
        )

    mixed_high = [2, 2, 1, 1, 1]
    mixed_medium = [2, 2, 1, 1, 1]
    for index in range(5):
        content_hash = _sha(f"manual-mixed-{index:04d}")
        findings = _manual_findings(
            content_hash,
            counter,
            mixed_high[index],
            mixed_medium[index],
        )
        specs.append(
            {
                "content_hash": content_hash,
                "classification": app.MANUAL_REVIEW_REQUIRED,
                "scan_status": app.SCAN_COMPLETED_FINDINGS,
                "findings": findings,
                "provenance_status": app.PROVENANCE_UNKNOWN,
                "provenance_classification": app.PROVENANCE_UNKNOWN,
            }
        )

    assert len(specs) == TOTAL_TARGETS
    return specs


def _make_fixture() -> dict:
    specs = _build_specs()
    scan_targets: list[dict] = []
    summary_targets: list[dict] = []
    provenance_entries: list[dict] = []
    eligibility_entries: list[dict] = []
    manifest_entries: list[dict] = []
    hash_entries: list[dict] = []

    for index, spec in enumerate(specs):
        member_count = 14 if index < 263 else 13
        member_ids = [
            f"src_{index:04d}_{member:02d}" for member in range(member_count)
        ]
        source_paths = [
            f"/synthetic/reports/{index:04d}/{member}.md"
            for member in range(member_count)
        ]
        content_hash = spec["content_hash"]
        representative = member_ids[0]
        severity_counts = _severity_counts(spec["findings"])
        provenance_status = spec["provenance_status"]
        confirmed = provenance_status == app.PROVENANCE_CONFIRMED

        provenance_evidence = {
            "content_hash": content_hash,
            "representative_source_id": representative,
            "classification": spec["provenance_classification"],
            "classifications": [spec["provenance_classification"]],
            "provenance_status": provenance_status,
            "confirmed": confirmed,
            "confirmed_cursor": False,
            "confirmed_opencode": False,
            "confirmed_chatgpt": False,
            "confirmed_other_agent": confirmed,
            "body_read": True,
            "review_required": True,
            "review_status": "NOT_STARTED",
            "historical_record": True,
            "historical_runtime_authority": False,
            "source_truth_class": app.SOURCE_TRUTH_CLASS,
            "authority_scope": app.AUTHORITY_SCOPE,
        }
        provenance_entries.append(provenance_evidence)

        scan_targets.append(
            {
                "content_hash": content_hash,
                "representative_source_id": representative,
                "absolute_path": source_paths[0],
                "source_root": "/synthetic/reports",
                "scan_status": spec["scan_status"],
                "finding_count": len(spec["findings"]),
                "severity_counts": severity_counts,
                "confidence_counts": {
                    name: sum(
                        1
                        for finding in spec["findings"]
                        if finding["confidence"] == name
                    )
                    for name in ("HIGH", "MEDIUM", "LOW")
                },
                "highest_severity": (
                    "HIGH" if severity_counts["HIGH"] else None
                ),
                "findings": spec["findings"],
                "review_required": True,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "content_hash_verified": True,
                "source_metadata_match": True,
                "provenance_evidence": provenance_evidence,
                "import_eligibility": spec["classification"],
                "eligibility_reasons": [],
            }
        )

        summary_targets.append(
            {
                "content_hash": content_hash,
                "representative_source_id": representative,
                "scan_status": spec["scan_status"],
                "finding_count": len(spec["findings"]),
                "severity_counts": severity_counts,
                "review_required": True,
            }
        )

        eligibility_entries.append(
            {
                "content_hash": content_hash,
                "representative_source_id": representative,
                "scan_status": spec["scan_status"],
                "secret_finding_count": len(spec["findings"]),
                "severity_counts": severity_counts,
                "import_eligibility": spec["classification"],
                "eligibility_reasons": [],
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "source_truth_class": app.SOURCE_TRUTH_CLASS,
                "authority_scope": app.AUTHORITY_SCOPE,
            }
        )

        manifest_entries.append(
            {
                "content_hash": content_hash,
                "representative_source_id": representative,
                "member_source_ids": member_ids,
                "source_paths": source_paths,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
            }
        )

        for member_id in member_ids:
            hash_entries.append(
                {
                    "source_id": member_id,
                    "absolute_path": f"/synthetic/reports/{member_id}.md",
                    "source_root": "/synthetic/reports",
                    "sha256": content_hash,
                    "verification_status": "CONTENT_IDENTICAL",
                }
            )

    for finding in [f for spec in specs for f in spec["findings"]]:
        finding["value_stored"] = False

    scan_counts = {
        name: sum(1 for spec in specs if spec["scan_status"] == name)
        for name in (app.SCAN_COMPLETED_NO_FINDINGS, app.SCAN_COMPLETED_FINDINGS)
    }
    all_findings = [finding for spec in specs for finding in spec["findings"]]

    def _count(field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for finding in all_findings:
            value = str(finding[field])
            result[value] = result.get(value, 0) + 1
        return result

    return {
        "scan_results": {
            "schema_version": app.SCAN_RESULTS_SCHEMA_VERSION,
            "targets": scan_targets,
            "counts": {
                "ACTUAL_SCAN_TARGET_COUNT": len(scan_targets),
                "SOURCE_REFERENCE_COUNT": len(hash_entries),
                **scan_counts,
                "SECRET_FINDING_COUNT": len(all_findings),
            },
        },
        "secret_findings": {
            "schema_version": app.FINDINGS_SUMMARY_SCHEMA_VERSION,
            "per_target": summary_targets,
            "by_severity": _severity_counts(all_findings),
            "by_secret_type": _count("secret_type"),
            "by_confidence": _count("confidence"),
            "counts": {
                "SECRET_FINDING_COUNT": len(all_findings),
                **_severity_counts(all_findings),
            },
        },
        "provenance_evidence": {
            "schema_version": app.PROVENANCE_EVIDENCE_SCHEMA_VERSION,
            "entries": provenance_entries,
            "counts": {
                "PROVENANCE_REVIEW_COUNT": len(provenance_entries),
                "PROVENANCE_CONFIRMED_COUNT": sum(
                    1
                    for entry in provenance_entries
                    if entry["provenance_status"] == app.PROVENANCE_CONFIRMED
                ),
                "PROVENANCE_UNKNOWN_COUNT": sum(
                    1
                    for entry in provenance_entries
                    if entry["provenance_status"] == app.PROVENANCE_UNKNOWN
                ),
            },
        },
        "import_eligibility": {
            "schema_version": app.IMPORT_ELIGIBILITY_SCHEMA_VERSION,
            "entries": eligibility_entries,
            "counts": {
                "IMPORT_ELIGIBILITY_REVIEW_COUNT": len(eligibility_entries),
            },
        },
        "manifest_review": {
            "schema_version": app.MANIFEST_REVIEW_SCHEMA_VERSION,
            "entries": manifest_entries,
            "counts": {
                "IMPORT_MANIFEST_COUNT": len(manifest_entries),
                "SOURCE_REFERENCE_COUNT": len(hash_entries),
            },
        },
        "hash_results": {
            "schema_version": app.CONTENT_HASH_SCHEMA_VERSION,
            "entries": hash_entries,
            "counts": {"SOURCE_REFERENCE_COUNT": len(hash_entries)},
        },
        "stage_b_final": {
            "path": "/synthetic/BC11E7A_STAGE_B_FINAL.md",
            "text": "VERDICT=BC11E7A_STAGE_B_REAL_SCAN_COMPLETE\n",
        },
    }


DESTINATION_STUB = {
    "expected_store_path": str(app.DEFAULT_DESTINATION_PATH),
    "configured_store_path": str(app.DEFAULT_DESTINATION_PATH),
    "reviewed_store_path": str(app.DEFAULT_DESTINATION_PATH),
    "configured_path_matches_expected": True,
    "reviewed_path_matches_expected": True,
    "store_exists": True,
    "store_is_symlink": False,
    "store_size_bytes": 40960,
    "store_sha256": "0" * 64,
    "schema_read": True,
    "schema_tables": ["records"],
    "records_table_present": True,
    "record_count": 0,
    "read_only_connection_opened": True,
    "write_connection_opened": False,
    "database_created": False,
    "database_migrated": False,
    "database_written": False,
    "status": app.DESTINATION_STATUS_CONFIRMED,
}


@pytest.fixture(scope="module")
def fixture() -> dict:
    return _make_fixture()


@pytest.fixture(scope="module")
def result(fixture: dict) -> dict:
    return app.build_result(
        fixture,
        generated_at=GENERATED_AT,
        destination=copy.deepcopy(DESTINATION_STUB),
    )


def _mutated(fixture: dict, mutate) -> dict:
    clone = copy.deepcopy(fixture)
    mutate(clone)
    return clone


def test_baseline_constants() -> None:
    assert app.EXPECTED_BASELINE["TOTAL_CONTENT_UNIQUE"] == 491
    assert app.EXPECTED_BASELINE["SOURCE_REFERENCE_COUNT"] == 6646
    assert app.EXPECTED_BASELINE["ELIGIBLE_CANDIDATE_COUNT"] == 390
    assert app.EXPECTED_BASELINE["REDACTION_REQUIRED_COUNT"] == 17
    assert app.EXPECTED_BASELINE["MANUAL_REVIEW_REQUIRED_COUNT"] == 84
    assert app.EXPECTED_BASELINE["SECRET_FINDING_COUNT"] == 154
    assert app.EXPECTED_BASELINE["PROVENANCE_CONFIRMED_COUNT"] == 3
    assert app.EXPECTED_BASELINE["PROVENANCE_UNKNOWN_COUNT"] == 488
    assert app.EXPECTED_BASELINE["FINAL_APPROVAL_MANIFEST_COUNT"] == 491


def test_input_validation_missing_input(tmp_path: Path) -> None:
    with pytest.raises(app.InputError) as excinfo:
        app.load_input(tmp_path / "missing.json", "scan_results")
    assert excinfo.value.code == app.BLOCKED_MISSING_INPUT


def test_input_validation_invalid_schema(fixture: dict) -> None:
    clone = _mutated(
        fixture,
        lambda data: data["scan_results"].__setitem__(
            "schema_version", "unexpected"
        ),
    )
    with pytest.raises(app.InputError) as excinfo:
        app.validate_shapes(clone)
    assert excinfo.value.code == app.BLOCKED_INVALID_INPUT


def test_input_validation_reconciliation_mismatch(fixture: dict) -> None:
    clone = _mutated(
        fixture,
        lambda data: data["manifest_review"]["entries"].pop(),
    )
    reconciliation = app.reconcile(clone)
    assert reconciliation["valid"] is False
    with pytest.raises(app.InputError):
        app.build_result(
            clone, generated_at=GENERATED_AT, destination=DESTINATION_STUB
        )


def test_content_unique_count_491(result: dict) -> None:
    manifest = result["final_approval_manifest"]
    assert result["counts"]["CONTENT_UNIQUE_COUNT"] == 491
    assert len(manifest) == 491
    assert len({record["content_hash"] for record in manifest}) == 491


def test_source_reference_count_6646(result: dict) -> None:
    manifest = result["final_approval_manifest"]
    assert result["counts"]["SOURCE_REFERENCE_COUNT"] == 6646
    assert sum(len(record["member_source_ids"]) for record in manifest) == 6646
    assert sum(len(record["source_paths"]) for record in manifest) == 6646


def test_eligible_reconciliation_390(result: dict) -> None:
    candidates = result["eligible_candidates"]
    assert len(candidates) == 390
    assert result["counts"]["ELIGIBLE_CANDIDATE_COUNT"] == 390
    for candidate in candidates:
        assert candidate["scan_status"] == app.SCAN_COMPLETED_NO_FINDINGS
        assert candidate["finding_count"] == 0
        assert candidate["import_disposition"] == app.IMPORT_DISPOSITION_IMPORT
        assert candidate["approved"] is False
        assert candidate["import_ready"] is False
        assert candidate["real_import_allowed"] is False


def test_redaction_reconciliation_17(result: dict) -> None:
    plan = result["redaction_review_plan"]
    assert len(plan) == 17
    assert result["counts"]["REDACTION_REQUIRED_COUNT"] == 17
    for entry in plan:
        assert entry["redaction_required"] is True
        assert entry["redaction_status"] == app.REDACTION_STATUS_NOT_APPLIED
        assert entry["redaction_applied"] is False
        assert entry["original_file_modified"] is False
        assert entry["import_copy_generated"] is False
        assert entry["import_disposition"] == app.IMPORT_DISPOSITION_REDACTED_IMPORT
        assert entry["approved"] is False


def test_manual_review_reconciliation_84(result: dict) -> None:
    queue = result["manual_review_queue"]
    assert len(queue) == 84
    assert result["counts"]["MANUAL_REVIEW_REQUIRED_COUNT"] == 84
    assert result["counts"]["MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE_COUNT"] == 79
    assert result["counts"]["MANUAL_CLASS_REDACTION_RECOMMENDED_COUNT"] == 5
    for entry in queue:
        assert entry["review_status"] == app.REVIEW_PENDING
        assert entry["import_disposition"] == app.IMPORT_DISPOSITION_MANUAL_REVIEW
        assert entry["approved"] is False
        assert entry["auto_excluded"] is False
        assert entry["review_classification"] in {
            app.MANUAL_CLASS_POSSIBLE_FALSE_POSITIVE,
            app.MANUAL_CLASS_REDACTION_RECOMMENDED,
            app.MANUAL_CLASS_INSUFFICIENT_EVIDENCE,
            app.MANUAL_CLASS_IMPORT_EXCLUSION_REVIEW,
        }


def test_finding_reconciliation_154(result: dict) -> None:
    disposition = result["secret_finding_disposition"]
    assert len(disposition) == 154
    assert result["counts"]["SECRET_FINDING_COUNT"] == 154
    assert result["counts"]["REDACTION_DISPOSITION_COUNT"] == 29
    assert result["counts"]["MANUAL_DISPOSITION_COUNT"] == 125
    assert result["counts"]["POSSIBLE_FALSE_POSITIVE_FINDING_COUNT"] == 0
    assert result["counts"]["UNRESOLVED_FINDING_COUNT"] == 0


def test_finding_disposition_is_conservative(result: dict) -> None:
    for entry in result["secret_finding_disposition"]:
        assert entry["review_disposition"] in app.DISPOSITION_VALUES
        assert entry["review_reason_code"]
        assert entry["review_status"] == app.REVIEW_PENDING
        assert entry["approved"] is False
        assert entry["value_stored"] is False
        assert entry["context_stored"] is False


def test_redaction_plan_is_plan_only(result: dict) -> None:
    for entry in result["redaction_review_plan"]:
        assert entry["finding_ids"]
        assert entry["secret_types"]
        assert entry["import_copy_generated"] is False
        assert entry["redaction_applied"] is False


def test_manual_review_queue_is_not_auto_resolved(result: dict) -> None:
    for entry in result["manual_review_queue"]:
        assert entry["review_status"] == app.REVIEW_PENDING
        assert entry["auto_excluded"] is False
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False


def test_provenance_preservation(result: dict) -> None:
    manifest = result["final_approval_manifest"]
    confirmed = [
        record for record in manifest if record["provenance_status"] == "CONFIRMED"
    ]
    unknown = [
        record for record in manifest if record["provenance_status"] == "UNKNOWN"
    ]
    assert len(confirmed) == 3
    assert len(unknown) == 488
    assert all(record["provenance_confirmed"] is True for record in confirmed)
    assert all(record["provenance_confirmed"] is False for record in unknown)
    assert all(record["historical_record"] is True for record in manifest)
    assert all(
        record["historical_runtime_authority"] is False for record in manifest
    )
    assert all(
        record["source_truth_class"] == app.SOURCE_TRUTH_CLASS
        for record in manifest
    )
    assert all(record["authority_scope"] == app.AUTHORITY_SCOPE for record in manifest)


def test_unknown_provenance_not_an_exclusion(result: dict) -> None:
    manifest = result["final_approval_manifest"]
    unknown = [
        record for record in manifest if record["provenance_status"] == "UNKNOWN"
    ]
    assert len(unknown) == 488
    for record in unknown:
        assert record["provenance_classification"] == "UNKNOWN"
        assert record["import_disposition"] in {
            app.IMPORT_DISPOSITION_IMPORT,
            app.IMPORT_DISPOSITION_REDACTED_IMPORT,
            app.IMPORT_DISPOSITION_MANUAL_REVIEW,
        }
        assert record["approval_status"] == app.APPROVAL_PENDING


def test_destination_read_only_review(tmp_path: Path) -> None:
    store = tmp_path / "knowledge_store.sqlite3"
    connection = sqlite3.connect(store)
    try:
        connection.execute("CREATE TABLE records (record_id TEXT)")
        connection.execute("INSERT INTO records VALUES ('one')")
        connection.commit()
    finally:
        connection.close()
    before = (store.read_bytes(), store.stat().st_mtime_ns)

    config = tmp_path / "config.py"
    config.write_text(
        "from pathlib import Path\n"
        f'PRODUCTION_STORE_PATH = Path("{store}")\n',
        encoding="utf-8",
    )
    review = app.review_import_destination(store, config_source_path=config)
    after = (store.read_bytes(), store.stat().st_mtime_ns)

    assert review["status"] == app.DESTINATION_STATUS_REVIEW
    assert review["store_exists"] is True
    assert review["schema_read"] is True
    assert review["records_table_present"] is True
    assert review["record_count"] == 1
    assert review["read_only_connection_opened"] is True
    assert review["write_connection_opened"] is False
    assert review["database_created"] is False
    assert review["database_migrated"] is False
    assert review["database_written"] is False
    assert before == after


def test_destination_missing_is_not_created(tmp_path: Path) -> None:
    store = tmp_path / "does_not_exist.sqlite3"
    review = app.review_import_destination(store)
    assert review["status"] == app.DESTINATION_STATUS_MISSING
    assert review["store_exists"] is False
    assert review["database_created"] is False
    assert store.exists() is False


def test_destination_never_opens_write_connection(
    tmp_path: Path, monkeypatch
) -> None:
    store = tmp_path / "store.sqlite3"
    connection = sqlite3.connect(store)
    try:
        connection.execute("CREATE TABLE records (record_id TEXT)")
        connection.commit()
    finally:
        connection.close()

    seen: list[tuple] = []
    real_connect = sqlite3.connect

    def _spy(database, *args, **kwargs):
        seen.append((database, args, kwargs))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _spy)
    app.review_import_destination(store)
    assert seen
    for database, _args, kwargs in seen:
        assert kwargs.get("uri") is True
        assert str(database).endswith("?mode=ro")


def test_approval_manifest_491(result: dict) -> None:
    manifest = result["final_approval_manifest"]
    assert result["counts"]["FINAL_APPROVAL_MANIFEST_COUNT"] == 491
    assert len(manifest) == 491
    required = {
        "content_hash",
        "representative_source_id",
        "member_source_ids",
        "source_paths",
        "provenance_status",
        "scan_status",
        "finding_count",
        "import_disposition",
        "redaction_status",
        "manual_review_status",
        "approval_status",
        "approved",
        "import_ready",
        "real_import_allowed",
    }
    for record in manifest:
        assert required <= set(record)
        assert record["approval_status"] == app.APPROVAL_PENDING


def test_all_approved_false(result: dict) -> None:
    assert result["acceptance"]["ALL_APPROVED_FALSE"] is True
    assert all(
        record["approved"] is False
        for record in result["final_approval_manifest"]
    )


def test_all_import_ready_false(result: dict) -> None:
    assert result["acceptance"]["ALL_IMPORT_READY_FALSE"] is True
    assert all(
        record["import_ready"] is False
        for record in result["final_approval_manifest"]
    )


def test_all_real_import_allowed_false(result: dict) -> None:
    assert result["acceptance"]["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True
    assert all(
        record["real_import_allowed"] is False
        for record in result["final_approval_manifest"]
    )


def test_no_secret_value_serialization(fixture: dict) -> None:
    clone = _mutated(fixture, lambda data: None)
    target = clone["scan_results"]["targets"][390]
    assert target["findings"]
    for finding in target["findings"]:
        finding["secret_value"] = SECRET_DECOY
        finding["snippet"] = SECRET_DECOY
        finding["value_hash"] = SECRET_DECOY

    result = app.build_result(
        clone, generated_at=GENERATED_AT, destination=DESTINATION_STUB
    )
    serialized = json.dumps(app.build_outputs(result), sort_keys=True)
    assert SECRET_DECOY not in serialized
    for entry in result["secret_finding_disposition"]:
        assert "secret_value" not in entry
        assert "snippet" not in entry
        assert "value_hash" not in entry


def test_no_real_import_and_no_production_write(result: dict) -> None:
    safety = result["safety"]
    assert safety["real_import_executed"] is False
    assert safety["production_database_opened_for_write"] is False
    assert safety["production_database_written"] is False
    assert safety["database_created"] is False
    assert safety["database_migrated"] is False
    assert safety["source_files_modified"] is False
    assert safety["source_body_stored"] is False
    assert safety["secret_values_stored"] is False
    assert safety["secret_value_hash_stored"] is False
    assert result["acceptance"]["NO_REAL_IMPORT"] is True
    assert result["acceptance"]["NO_PRODUCTION_WRITE"] is True


def test_deterministic_output(fixture: dict, result: dict) -> None:
    first = json.dumps(app.build_outputs(result), sort_keys=True)
    second = json.dumps(app.build_outputs(result), sort_keys=True)
    assert first == second

    rebuilt = app.build_result(
        fixture,
        generated_at=GENERATED_AT,
        destination=copy.deepcopy(DESTINATION_STUB),
    )
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(result, sort_keys=True)


def test_write_outputs_and_permissions(tmp_path: Path, result: dict) -> None:
    outputs = app.write_outputs(
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
        "eligible_candidates",
        "secret_finding_disposition",
        "redaction_review_plan",
        "manual_review_queue",
        "final_approval_manifest",
        "import_approval_request",
        "final",
    }
    for path in outputs.values():
        assert Path(path).stat().st_mode & 0o777 == 0o600

    manifest = json.loads(
        Path(outputs["final_approval_manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["count"] == 491
    assert manifest["approval_status"] == app.APPROVAL_PENDING
    assert manifest["counts"]["FINAL_APPROVAL_MANIFEST_COUNT"] == 491

    request = Path(outputs["import_approval_request"]).read_text(encoding="utf-8")
    final = Path(outputs["final"]).read_text(encoding="utf-8")
    for marker in (
        "ELIGIBLE_CANDIDATE_COUNT=390",
        "REDACTION_REQUIRED_COUNT=17",
        "MANUAL_REVIEW_REQUIRED_COUNT=84",
        "SECRET_FINDING_COUNT=154",
        "FINAL_APPROVAL_MANIFEST_COUNT=491",
        "REAL_IMPORT_APPROVED=NO",
        "PRODUCTION_WRITE_APPROVED=NO",
    ):
        assert marker in request
    for marker in (
        "VERDICT=BC11E7B_FINAL_IMPORT_APPROVAL_REVIEW_READY",
        "CONTENT_UNIQUE_COUNT=491",
        "SOURCE_REFERENCE_COUNT=6646",
        "ALL_APPROVED_FALSE=TRUE",
        "ALL_IMPORT_READY_FALSE=TRUE",
        "ALL_REAL_IMPORT_ALLOWED_FALSE=TRUE",
        "REAL_IMPORT_EXECUTED=NO",
        "GIT_PUSH=NO",
    ):
        assert marker in final


def test_write_outputs_refuses_existing(tmp_path: Path, result: dict) -> None:
    app.write_outputs(result, output_dir=tmp_path)
    with pytest.raises(app.InputError) as excinfo:
        app.write_outputs(result, output_dir=tmp_path)
    assert excinfo.value.code == app.BLOCKED_EXISTING_OUTPUT


def _write_fixture_files(tmp_path: Path, fixture: dict) -> dict[str, Path]:
    paths = {
        "scan_results": tmp_path / "BC11E7A_REAL_SCAN_RESULTS.json",
        "secret_findings": tmp_path / "BC11E7A_SECRET_FINDINGS_SUMMARY.json",
        "provenance_evidence": tmp_path
        / "BC11E7A_PROVENANCE_EVIDENCE_REVIEW.json",
        "import_eligibility": tmp_path
        / "BC11E7A_IMPORT_ELIGIBILITY_REVIEW.json",
        "stage_b_final": tmp_path / "BC11E7A_STAGE_B_FINAL.md",
        "manifest_review": tmp_path / "BC11E6_IMPORT_MANIFEST_REVIEW.json",
        "hash_results": tmp_path / "BC11E5_CONTENT_HASH_RESULTS.json",
    }
    for key, path in paths.items():
        if key == "stage_b_final":
            path.write_text(fixture[key]["text"], encoding="utf-8")
        else:
            path.write_text(
                json.dumps(fixture[key], indent=2), encoding="utf-8"
            )
    return paths


def test_cli_success(tmp_path: Path, fixture: dict) -> None:
    paths = _write_fixture_files(tmp_path, fixture)
    store = tmp_path / "store.sqlite3"
    connection = sqlite3.connect(store)
    try:
        connection.execute("CREATE TABLE records (record_id TEXT)")
        connection.commit()
    finally:
        connection.close()
    config = tmp_path / "config.py"
    config.write_text(
        "from pathlib import Path\n"
        f'PRODUCTION_STORE_PATH = Path("{store}")\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "outputs"
    code = app.main(
        [
            "--scan-results",
            str(paths["scan_results"]),
            "--secret-findings",
            str(paths["secret_findings"]),
            "--provenance-evidence",
            str(paths["provenance_evidence"]),
            "--import-eligibility",
            str(paths["import_eligibility"]),
            "--stage-b-final",
            str(paths["stage_b_final"]),
            "--manifest-review",
            str(paths["manifest_review"]),
            "--hash-results",
            str(paths["hash_results"]),
            "--output-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
            "--destination-store",
            str(store),
            "--destination-config",
            str(config),
        ]
    )
    assert code == 0
    assert (output_dir / app.MANIFEST_JSON_NAME).exists()
    assert (output_dir / app.FINAL_MD_NAME).exists()


def test_cli_input_blocked(tmp_path: Path) -> None:
    code = app.main(
        [
            "--scan-results",
            str(tmp_path / "missing.json"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
