"""BC-11E-6 import target finalization tests.

All fixtures are synthetic and in-memory. No test reads a saved report body,
recomputes a hash, touches production, or performs a real import.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_import_target_finalization as itf  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_U1 = "c" * 64
HASH_U2 = "d" * 64
GENERATED_AT = "2026-11-09T00:00:00+00:00"


def _source(
    source_id: str,
    content_hash: str,
    status: str,
    *,
    root: str = "/synthetic/root",
) -> dict:
    return {
        "source_id": source_id,
        "absolute_path": f"{root}/{source_id}.md",
        "source_root": root,
        "sha256": content_hash,
        "verification_status": status,
        "bytes_read": 10,
        "body_stored": False,
        "provenance_status": itf.PROVENANCE_UNKNOWN,
    }


def _provenance(
    source_id: str,
    classification: str,
    *,
    source_classification: str = "UNKNOWN_REPORT_CANDIDATE",
    review_priority: str = "P3",
) -> dict:
    return {
        "source_id": source_id,
        "classification": classification,
        "source_classification": source_classification,
        "provenance_status": itf.PROVENANCE_UNKNOWN,
        "review_priority": review_priority,
        "review_status": itf.REVIEW_NOT_STARTED,
        "review_required": True,
        "confirmed_cursor": False,
        "confirmed_other_agent": False,
        "confirmed_chatgpt": False,
        "metadata_confirmed_cursor": False,
        "metadata_confirmed_other_agent": False,
        "metadata_confirmed_chatgpt": False,
    }


def _fixtures() -> dict:
    hash_entries = [
        _source("a1", HASH_A, itf.CONTENT_IDENTICAL),
        _source("a2", HASH_A, itf.CONTENT_IDENTICAL),
        _source("a3", HASH_A, itf.CONTENT_IDENTICAL),
        _source("b1", HASH_B, itf.CONTENT_IDENTICAL),
        _source("b2", HASH_B, itf.CONTENT_IDENTICAL),
        _source("u1", HASH_U1, itf.CONTENT_DIFFERENT),
        _source("u2", HASH_U2, itf.CONTENT_DIFFERENT),
    ]
    classifications = {
        "a1": itf.CLASS_CURSOR,
        "a2": itf.CLASS_OTHER_AGENT,
        "a3": itf.CLASS_UNKNOWN,
        "b1": itf.CLASS_CHATGPT,
        "b2": itf.CLASS_UNKNOWN,
        "u1": itf.CLASS_UNKNOWN,
        "u2": itf.CLASS_OTHER_AGENT,
    }
    source_classification = {
        "a1": "FILENAME_MATCH_CANDIDATE",
        "a2": "OTHER_AGENT_REPORT_CANDIDATE",
        "a3": "UNKNOWN_REPORT_CANDIDATE",
        "b1": "CHATGPT_REVIEW_CANDIDATE",
        "b2": "UNKNOWN_REPORT_CANDIDATE",
        "u1": "UNKNOWN_REPORT_CANDIDATE",
        "u2": "OTHER_AGENT_REPORT_CANDIDATE",
    }
    provenance = [
        _provenance(
            source_id,
            classification,
            source_classification=source_classification[source_id],
        )
        for source_id, classification in classifications.items()
    ]
    paths = {entry["source_id"]: entry["absolute_path"] for entry in hash_entries}
    confirmed = [
        {
            "content_hash": HASH_A,
            "representative_source_id": "a1",
            "representative_is_import_approval": False,
            "member_source_ids": ["a1", "a2", "a3"],
            "source_paths": [paths["a1"], paths["a2"], paths["a3"]],
            "member_count": 3,
            "verification_status": "CONTENT_IDENTICAL_CONFIRMED",
            "approved": False,
            "import_ready": False,
        },
        {
            "content_hash": HASH_B,
            "representative_source_id": "b1",
            "representative_is_import_approval": False,
            "member_source_ids": ["b1", "b2"],
            "source_paths": [paths["b1"], paths["b2"]],
            "member_count": 2,
            "verification_status": "CONTENT_IDENTICAL_CONFIRMED",
            "approved": False,
            "import_ready": False,
        },
    ]
    unique = [
        {
            "source_id": "u1",
            "absolute_path": paths["u1"],
            "sha256": HASH_U1,
            "verification_status": itf.CONTENT_DIFFERENT,
            "approved": False,
            "import_ready": False,
        },
        {
            "source_id": "u2",
            "absolute_path": paths["u2"],
            "sha256": HASH_U2,
            "verification_status": itf.CONTENT_DIFFERENT,
            "approved": False,
            "import_ready": False,
        },
    ]
    readiness = {
        "entries": [
            {
                "source_id": entry["source_id"],
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "verification_status": itf.REVIEW_NOT_STARTED,
            }
            for entry in hash_entries
        ]
    }
    manifest = {
        "entries": [
            {
                "sourceId": entry["source_id"],
                "path": entry["absolute_path"],
                "sourceStatus": "SOURCE_PRESENT",
                "approved": False,
            }
            for entry in hash_entries
        ]
    }
    return {
        "hash_results": {"entries": hash_entries},
        "confirmed_duplicates": {"groups": confirmed},
        "unique_content_candidates": {"entries": unique},
        "provenance_plan": {"entries": provenance},
        "readiness": readiness,
        "manifest": manifest,
        "content_final": {
            "path": "/synthetic/BC11E5_CONTENT_VERIFICATION_FINAL.md",
            "exists": True,
            "size_bytes": 10,
        },
    }


def _expected() -> dict:
    return {
        "TOTAL_SOURCE_ENTRIES": 7,
        "DISTINCT_CONTENT_HASHES": 4,
        "SINGLETON_CONTENT_COUNT": 2,
        "CONFIRMED_DUPLICATE_GROUPS": 2,
        "CONFIRMED_DUPLICATE_GROUP_MEMBERS": 5,
        "ADDITIONAL_COPY_COUNT": 3,
        "UNIQUE_CONTENT_CANDIDATE_COUNT": 2,
        "PROVENANCE_REVIEW_COUNT": 7,
        "IMPORT_READINESS_CANDIDATE_COUNT": 7,
        "MANIFEST_CANDIDATE_COUNT": 7,
    }


def _build(fixtures: dict | None = None) -> dict:
    return itf.build_import_target_review(
        fixtures or _fixtures(),
        expected=_expected(),
        generated_at=GENERATED_AT,
    )


def _records_by_hash(result: dict) -> dict[str, dict]:
    return {record["content_hash"]: record for record in result["records"]}


def test_input_validation(tmp_path: Path) -> None:
    with pytest.raises(itf.InputError) as exc_info:
        itf.load_input(tmp_path / "missing.json")
    assert exc_info.value.code == itf.BLOCKED_MISSING_INPUT

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    with pytest.raises(itf.InputError) as exc_info:
        itf.load_input(invalid)
    assert exc_info.value.code == itf.BLOCKED_INVALID_INPUT

    fixtures = _fixtures()
    fixtures["manifest"]["entries"] = "not a list"
    with pytest.raises(itf.InputError):
        itf.validate_inputs(fixtures, expected=_expected())

    fixtures = _fixtures()
    del fixtures["hash_results"]["entries"][0]["source_id"]
    with pytest.raises(itf.InputError):
        itf.validate_inputs(fixtures, expected=_expected())

    fixtures = _fixtures()
    result = itf.validate_inputs(fixtures, expected=_expected())
    assert result["status"] == itf.INPUTS_VALID
    assert result["inputs_valid"] is True

    bad = _expected()
    bad["TOTAL_SOURCE_ENTRIES"] += 1
    result = itf.validate_inputs(_fixtures(), expected=bad)
    assert result["status"] == itf.INPUT_COUNT_MISMATCH
    assert any(item["key"] == "TOTAL_SOURCE_ENTRIES" for item in result["mismatches"])


def test_hash_reconciliation_and_unique_content_count() -> None:
    result = _build()
    counts = result["counts"]
    assert counts["TOTAL_SOURCE_ENTRIES"] == 7
    assert counts["CONTENT_UNIQUE_COUNT"] == 4
    assert counts["DISTINCT_CONTENT_HASHES"] == 4
    assert counts["SINGLETON_CONTENT_COUNT"] == 2
    assert counts["CONFIRMED_DUPLICATE_GROUPS"] == 2
    assert counts["ADDITIONAL_COPY_COUNT"] == 3
    assert counts["SOURCE_REFERENCE_COUNT"] == 7
    assert [record["content_hash"] for record in result["records"]] == sorted(
        [HASH_A, HASH_B, HASH_U1, HASH_U2]
    )


def test_duplicate_source_preservation() -> None:
    result = _build()
    preserved = []
    for record in result["records"]:
        assert record["member_count"] == len(record["member_source_ids"])
        assert len(record["source_paths"]) == record["member_count"]
        preserved.extend(record["member_source_ids"])
    assert sorted(preserved) == ["a1", "a2", "a3", "b1", "b2", "u1", "u2"]
    assert len(preserved) == len(set(preserved))

    by_hash = _records_by_hash(result)
    assert by_hash[HASH_A]["member_source_ids"] == ["a1", "a2", "a3"]
    assert by_hash[HASH_B]["member_source_ids"] == ["b1", "b2"]
    assert by_hash[HASH_U1]["member_source_ids"] == ["u1"]


def test_representative_selection_and_determinism() -> None:
    first = _build()
    second = _build()
    assert first["content_unique_review"] == second["content_unique_review"]
    assert first["provenance_review_queue"] == second["provenance_review_queue"]
    assert first["import_manifest_review"] == second["import_manifest_review"]

    reordered = _fixtures()
    reordered["hash_results"]["entries"] = list(
        reversed(reordered["hash_results"]["entries"])
    )
    reordered["confirmed_duplicates"]["groups"] = list(
        reversed(reordered["confirmed_duplicates"]["groups"])
    )
    reordered["unique_content_candidates"]["entries"] = list(
        reversed(reordered["unique_content_candidates"]["entries"])
    )
    reordered["provenance_plan"]["entries"] = list(
        reversed(reordered["provenance_plan"]["entries"])
    )
    third = _build(reordered)
    assert third["content_unique_review"] == first["content_unique_review"]
    assert third["import_manifest_review"] == first["import_manifest_review"]

    by_hash = _records_by_hash(first)
    assert by_hash[HASH_A]["representative_source_id"] == "a1"
    assert by_hash[HASH_B]["representative_source_id"] == "b1"
    assert by_hash[HASH_U1]["representative_source_id"] == "u1"
    assert by_hash[HASH_U2]["representative_source_id"] == "u2"


def test_provenance_unknown_preservation() -> None:
    result = _build()
    queue = result["provenance_review_queue"]
    assert queue["counts"]["CONFIRMED_CURSOR_COUNT"] == 0
    assert queue["counts"]["CONFIRMED_OTHER_AGENT_COUNT"] == 0
    assert queue["counts"]["CONFIRMED_CHATGPT_COUNT"] == 0
    for record in result["records"]:
        assert record["provenance_status"] == itf.PROVENANCE_UNKNOWN
        assert record["confirmed_cursor"] is False
        assert record["confirmed_other_agent"] is False
        assert record["confirmed_chatgpt"] is False
        assert record["source_truth_class"] == itf.SOURCE_TRUTH_CLASS
        assert record["authority_scope"] == itf.AUTHORITY_SCOPE
        assert record["historical_runtime_authority"] is False
    for entry in queue["entries"]:
        assert entry["provenance_status"] == itf.PROVENANCE_UNKNOWN
        assert entry["confirmed_cursor"] is False
        assert entry["confirmed_other_agent"] is False
        assert entry["confirmed_chatgpt"] is False


def test_multiple_source_classification_preservation() -> None:
    result = _build()
    record = _records_by_hash(result)[HASH_A]
    assert record["classifications"] == sorted(
        [itf.CLASS_CURSOR, itf.CLASS_OTHER_AGENT, itf.CLASS_UNKNOWN]
    )
    assert record["classification_counts"] == {
        itf.CLASS_CURSOR: 1,
        itf.CLASS_OTHER_AGENT: 1,
        itf.CLASS_UNKNOWN: 1,
    }
    assert record["source_classifications"] == {
        "a1": "FILENAME_MATCH_CANDIDATE",
        "a2": "OTHER_AGENT_REPORT_CANDIDATE",
        "a3": "UNKNOWN_REPORT_CANDIDATE",
    }
    assert record["source_classification"] == "FILENAME_MATCH_CANDIDATE"
    assert record["review_priority"] == itf.PRIORITY_P0


def test_review_priority() -> None:
    result = _build()
    by_hash = _records_by_hash(result)
    assert by_hash[HASH_A]["review_priority"] == itf.PRIORITY_P0
    assert by_hash[HASH_B]["review_priority"] == itf.PRIORITY_P2
    assert by_hash[HASH_U1]["review_priority"] == itf.PRIORITY_P3
    assert by_hash[HASH_U2]["review_priority"] == itf.PRIORITY_P1
    assert result["counts"]["PRIORITY_COUNTS"] == {
        itf.PRIORITY_P0: 1,
        itf.PRIORITY_P1: 1,
        itf.PRIORITY_P2: 1,
        itf.PRIORITY_P3: 1,
    }


def test_import_eligibility_review_required_by_default() -> None:
    result = _build()
    assert result["counts"]["ELIGIBLE_CANDIDATE_COUNT"] == 0
    assert result["counts"]["REVIEW_REQUIRED_COUNT"] == 4
    assert result["counts"]["EXCLUDED_BY_POLICY_COUNT"] == 0
    assert result["counts"]["SOURCE_UNAVAILABLE_COUNT"] == 0
    for record in result["records"]:
        assert record["import_eligibility"] == itf.REVIEW_REQUIRED
        assert "SECRET_REVIEW_NOT_PERFORMED" in record["eligibility_reasons"]


def test_import_eligibility_source_unavailable_and_policy() -> None:
    fixtures = _fixtures()
    for entry in fixtures["hash_results"]["entries"]:
        if entry["source_id"] == "u1":
            entry["absolute_path"] = "relative/path/u1.md"
    result = _build(fixtures)
    by_hash = _records_by_hash(result)
    assert by_hash[HASH_U1]["import_eligibility"] == itf.SOURCE_UNAVAILABLE
    assert result["counts"]["SOURCE_UNAVAILABLE_COUNT"] == 1

    fixtures = _fixtures()
    for entry in fixtures["manifest"]["entries"]:
        if entry["sourceId"] == "u2":
            entry["sourceStatus"] = "SOURCE_REJECTED"
    result = _build(fixtures)
    by_hash = _records_by_hash(result)
    assert by_hash[HASH_U2]["import_eligibility"] == itf.EXCLUDED_BY_POLICY
    assert result["counts"]["EXCLUDED_BY_POLICY_COUNT"] == 1


def test_secret_review_not_performed() -> None:
    result = _build()
    assert result["counts"]["SECRET_REVIEW_NOT_PERFORMED_COUNT"] == 4
    for record in result["records"]:
        assert record["secret_review_status"] == itf.SECRET_REVIEW_NOT_PERFORMED
    for entry in result["import_manifest_review"]["entries"]:
        assert entry["secret_review_status"] == itf.SECRET_REVIEW_NOT_PERFORMED


def test_manifest_approval_false() -> None:
    result = _build()
    manifest = result["import_manifest_review"]
    assert manifest["approved"] is False
    assert manifest["import_ready"] is False
    assert manifest["real_import_allowed"] is False
    assert manifest["counts"]["IMPORT_MANIFEST_COUNT"] == 4
    assert manifest["counts"]["ALL_APPROVED_FALSE"] is True
    assert manifest["counts"]["ALL_IMPORT_READY_FALSE"] is True
    assert manifest["counts"]["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True
    for entry in manifest["entries"]:
        assert entry["approval_status"] == itf.APPROVAL_NOT_APPROVED
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False
    assert result["counts"]["ALL_APPROVED_FALSE"] is True
    assert result["counts"]["ALL_IMPORT_READY_FALSE"] is True
    assert result["counts"]["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True


def test_no_source_body_read(tmp_path: Path, monkeypatch) -> None:
    fixtures = _fixtures()
    marker = "DO_NOT_READ_THIS_REPORT_BODY"
    path_by_id: dict[str, str] = {}
    for entry in fixtures["hash_results"]["entries"]:
        path = tmp_path / f"{entry['source_id']}.md"
        path.write_text(marker, encoding="utf-8")
        entry["absolute_path"] = str(path)
        entry["source_root"] = str(tmp_path)
        path_by_id[entry["source_id"]] = str(path)
    for group in fixtures["confirmed_duplicates"]["groups"]:
        group["source_paths"] = [
            path_by_id[source_id] for source_id in group["member_source_ids"]
        ]
    for entry in fixtures["unique_content_candidates"]["entries"]:
        entry["absolute_path"] = path_by_id[entry["source_id"]]

    def _forbidden_read(*args, **kwargs):
        raise AssertionError("source body must not be read")

    monkeypatch.setattr(Path, "read_text", _forbidden_read)
    result = _build(fixtures)
    assert marker not in json.dumps(result)


def test_no_hash_recalculation(monkeypatch) -> None:
    source = (ROOT / "scripts" / "bc11e_import_target_finalization.py").read_text(
        encoding="utf-8"
    )
    assert "import hashlib" not in source
    assert "hashlib.sha256" not in source
    assert "hash_file(" not in source

    def _forbidden_hash(*args, **kwargs):
        raise AssertionError("hash must not be recomputed")

    monkeypatch.setattr(hashlib, "sha256", _forbidden_hash)
    result = _build()
    assert result["content_unique_review"]["hash_recalculated"] is False


def test_no_real_import() -> None:
    source = (ROOT / "scripts" / "bc11e_import_target_finalization.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "real_import(",
        "import_report(",
        "import_knowledge(",
        "ingest_report(",
    ):
        assert token not in source

    result = _build()
    assert result["content_unique_review"]["real_import_executed"] is False
    assert result["provenance_review_queue"]["real_import_executed"] is False
    assert result["import_manifest_review"]["real_import_executed"] is False


def test_no_production_write(tmp_path: Path) -> None:
    source = (ROOT / "scripts" / "bc11e_import_target_finalization.py").read_text(
        encoding="utf-8"
    )
    for token in ("sqlite", "production_db", "/var/lib/tradingai"):
        assert token not in source

    result = _build()
    out = tmp_path / "out"
    paths = itf.write_outputs(result, output_dir=out)
    written = {Path(item).resolve() for item in paths.values()}
    assert all(item.parent == out.resolve() for item in written)
    assert len(written) == 5
    assert {item.name for item in written} == {
        itf.CONTENT_REVIEW_JSON_NAME,
        itf.PROVENANCE_QUEUE_JSON_NAME,
        itf.MANIFEST_REVIEW_JSON_NAME,
        itf.SUMMARY_MD_NAME,
        itf.FINAL_MD_NAME,
    }


def test_outputs_and_coverage(tmp_path: Path) -> None:
    result = _build()
    out = tmp_path / "out"
    itf.write_outputs(
        result,
        output_dir=out,
        meta={
            "worktree": "/synthetic/worktree",
            "branch": "feature/synthetic",
            "head_before": "0" * 40,
            "head_after": "1" * 40,
            "test_results": "PASS",
            "changed_files": "two",
            "commit": "abc1234",
        },
    )
    review = json.loads((out / itf.CONTENT_REVIEW_JSON_NAME).read_text("utf-8"))
    queue = json.loads((out / itf.PROVENANCE_QUEUE_JSON_NAME).read_text("utf-8"))
    manifest = json.loads((out / itf.MANIFEST_REVIEW_JSON_NAME).read_text("utf-8"))
    final = (out / itf.FINAL_MD_NAME).read_text("utf-8")
    summary = (out / itf.SUMMARY_MD_NAME).read_text("utf-8")

    assert review["coverage_status"] == itf.COVERAGE_STATUS
    assert review["full_history_asserted"] is False
    assert queue["counts"]["PROVENANCE_REVIEW_COUNT"] == 4
    assert manifest["counts"]["IMPORT_MANIFEST_COUNT"] == 4
    for field in (
        "TASK_ID",
        "VERDICT",
        "TOTAL_SOURCE_ENTRIES",
        "CONTENT_UNIQUE_COUNT",
        "ADDITIONAL_COPY_COUNT",
        "IMPORT_MANIFEST_COUNT",
        "COVERAGE_STATUS",
        "FULL_HISTORY_ASSERTED",
        "REAL_IMPORT_EXECUTED",
        "GIT_PUSH",
        "PRODUCTION_RESTART",
    ):
        assert f"{field}=" in final
    assert "REAL_IMPORT_EXECUTED=NO" in summary
