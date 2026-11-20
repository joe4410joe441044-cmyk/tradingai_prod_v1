"""BC-11E-3 candidate consolidation tests.

Every fixture is synthetic and lives in memory or under a pytest temporary
directory. No test reads a real saved report, computes a content hash, touches
the production knowledge store, or performs a real import.
"""

from __future__ import annotations

import builtins
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_candidate_consolidation as con  # noqa: E402

BASE_MTIME = 1_700_000_000.0


def _iso(ts: float = BASE_MTIME) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _candidate(
    path: str,
    source_id: str,
    *,
    filename: str | None = None,
    size: int = 10,
    mtime: float = BASE_MTIME,
    classification: str = "UNKNOWN_REPORT_CANDIDATE",
    origin_confirmed: bool = False,
    source_root: str = "/wt/docs/reports",
    worktree_path: str = "/wt",
    branch: str = "feature/a",
    head: str = "a" * 40,
    reason: str = "ORIGIN_UNCONFIRMED",
    extension: str = ".md",
) -> dict:
    return {
        "source_id": source_id,
        "absolute_path": path,
        "filename": filename if filename is not None else Path(path).name,
        "extension": extension,
        "size_bytes": size,
        "mtime": _iso(mtime),
        "source_root": source_root,
        "worktree_path": worktree_path,
        "branch": branch,
        "head": head,
        "classification": classification,
        "candidate_reason": reason,
        "origin_confirmed": origin_confirmed,
        "approved": False,
        "requires_review": True,
    }


def _e1(candidates: list[dict], entries: list[dict] | None = None) -> dict:
    return {
        "schema_version": "tradingai-bc11e-cursor-report-inventory/v1",
        "counts": {
            "CANDIDATE_COUNT": len(candidates),
            "FILENAME_MATCH_COUNT": sum(
                1
                for item in candidates
                if item["classification"] == "FILENAME_MATCH_CANDIDATE"
            ),
            "REVIEW_REQUIRED_COUNT": sum(
                1 for item in candidates if item["classification"] == "REVIEW_REQUIRED"
            ),
            "EXCLUDED_COUNT": 0,
            "TOTAL_DISCOVERED_COUNT": len(candidates),
        },
        "entries": entries or [],
        "candidates": candidates,
    }


def _e2(candidates: list[dict], entries: list[dict] | None = None) -> dict:
    return {
        "schema_version": "tradingai-bc11e2-cross-worktree-inventory/v1",
        "counts": {
            "WORKTREE_COUNT": 1,
            "REPORT_ROOT_COUNT": 1,
            "TOTAL_CANDIDATE_COUNT": len(candidates),
            "EXCLUDED_COUNT": 0,
            "SCAN_LIMIT_REACHED_COUNT": 0,
        },
        "report_roots": [],
        "out_of_scope_locations": [],
        "errors": [],
        "entries": entries or [],
        "candidates": candidates,
    }


def _stat_func(sizes: dict[str, int] | None = None, mtimes: dict[str, float] | None = None):
    sizes = sizes or {}
    mtimes = mtimes or {}

    def _stat(path: str) -> SimpleNamespace:
        return SimpleNamespace(
            st_size=sizes.get(path, 10), st_mtime=mtimes.get(path, BASE_MTIME)
        )

    return _stat


def _run(
    e1: dict,
    e2: dict,
    *,
    generated_at: str = "2026-11-08T00:00:00+00:00",
    stat_func=None,
) -> dict:
    return con.consolidate_inventory(
        e1,
        e2,
        generated_at=generated_at,
        expected_bc11e1=e1["counts"],
        expected_bc11e2=e2["counts"],
        stat_func=stat_func or _stat_func(),
    )


def _missing_stat(path: str):
    raise FileNotFoundError(path)


def test_input_schema_validation(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(con.InputError) as exc_info:
        con.load_input(missing)
    assert exc_info.value.code == con.MISSING_INPUT

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    with pytest.raises(con.InputError) as exc_info:
        con.load_input(invalid)
    assert exc_info.value.code == con.INVALID_INPUT

    invalid_schema = tmp_path / "schema.json"
    invalid_schema.write_text(json.dumps({"candidates": "no"}), encoding="utf-8")
    with pytest.raises(con.InputError) as exc_info:
        con.load_input(invalid_schema)
    assert exc_info.value.code == con.INVALID_INPUT


def test_input_count_reconciliation() -> None:
    e1 = _e1([_candidate("/wt/a.md", "e1-1", classification="REVIEW_REQUIRED")])
    e2 = _e2([_candidate("/wt/b.md", "e2-1")])
    result = con.reconcile_inputs(e1, e2, expected_bc11e1=e1["counts"], expected_bc11e2=e2["counts"])
    assert result["status"] == con.INPUTS_VALID
    assert result["inputs_valid"] is True
    assert result["mismatches"] == []

    broken = con.reconcile_inputs(
        e1,
        e2,
        expected_bc11e1={"CANDIDATE_COUNT": 999},
        expected_bc11e2=e2["counts"],
    )
    assert broken["status"] == con.INPUT_COUNT_MISMATCH
    assert broken["inputs_valid"] is False
    assert broken["mismatches"][0]["key"] == "CANDIDATE_COUNT"


def test_unified_schema_normalization() -> None:
    e1 = _e1([_candidate("/tmp/work_bc_audit/BC1.md", "e1-1", classification="FILENAME_MATCH_CANDIDATE")])
    e2 = _e2([_candidate("/wt/docs/reports/CURSOR_NOTES.md", "e2-1", classification="CURSOR_REPORT_CANDIDATE")])
    result = _run(e1, e2)
    required = {
        "source_id",
        "absolute_path",
        "filename",
        "extension",
        "size_bytes",
        "mtime",
        "source_root",
        "worktree_path",
        "branch",
        "head",
        "inventory_origin",
        "source_classification",
        "classification",
        "candidate_reason",
        "provenance_status",
        "duplicate_group",
        "selection_status",
        "approval_status",
    }
    assert result["counts"]["UNIFIED_CANDIDATE_COUNT"] == 2
    for entry in result["unified_inventory"]["candidates"]:
        assert required.issubset(entry)
        assert entry["approval_status"] == con.APPROVAL_UNAPPROVED
        assert entry["approved"] is False
        assert entry["classification_basis"]


def test_metadata_only_flags() -> None:
    result = _run(_e1([]), _e2([_candidate("/wt/a.md", "e2-1")]))
    inventory = result["unified_inventory"]
    assert inventory["mode"] == "OFFLINE_METADATA_CONSOLIDATION_ONLY"
    assert inventory["content_read"] is False
    assert inventory["hash_computed"] is False
    assert inventory["real_import_executed"] is False
    assert inventory["safety"]["body_hash_computed"] is False
    assert inventory["safety"]["body_text_stored"] is False


def test_no_source_content_read(monkeypatch) -> None:
    e1 = _e1([])
    e2 = _e2([_candidate("/wt/a.md", "e2-1")])

    def boom(*args, **kwargs):
        raise AssertionError("report content was read during consolidation")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        patch.setattr(io, "open", boom)
        patch.setattr(Path, "open", boom)
        patch.setattr(Path, "read_text", boom)
        patch.setattr(Path, "read_bytes", boom)
        result = _run(e1, e2)
    assert result["counts"]["UNIFIED_CANDIDATE_COUNT"] == 1


def test_no_content_hash_in_source() -> None:
    source = (ROOT / "scripts" / "bc11e_candidate_consolidation.py").read_text(
        encoding="utf-8"
    )
    assert "read_bytes" not in source
    assert "read_text" not in source.replace(
        'target.read_text(encoding="utf-8")', ""
    )
    assert "sha256_file" not in source
    assert "content_hash" not in source


def test_provenance_safety() -> None:
    hinted = _candidate(
        "/wt/docs/reports/cursor_report.md",
        "e2-1",
        classification="CURSOR_REPORT_CANDIDATE",
        origin_confirmed=False,
    )
    result = _run(_e1([]), _e2([hinted]))
    entry = result["unified_inventory"]["candidates"][0]
    assert entry["classification"] == con.CLASS_CURSOR
    assert entry["provenance_status"] == con.PROVENANCE_UNKNOWN
    assert entry["origin_confirmed"] is False

    confirmed = _candidate(
        "/wt/docs/reports/cursor_report.md",
        "e2-2",
        classification="CURSOR_REPORT_CANDIDATE",
        origin_confirmed=True,
    )
    result = _run(_e1([]), _e2([confirmed]))
    entry = result["unified_inventory"]["candidates"][0]
    assert entry["provenance_status"] == con.PROVENANCE_CONFIRMED_CURSOR


def test_unknown_origin_preservation() -> None:
    result = _run(
        _e1([]),
        _e2([_candidate("/wt/unknown.md", "e2-1", classification="UNKNOWN_REPORT_CANDIDATE")]),
    )
    entry = result["unified_inventory"]["candidates"][0]
    assert entry["classification"] == con.CLASS_UNKNOWN
    assert entry["provenance_status"] == con.PROVENANCE_UNKNOWN
    assert result["counts"]["UNKNOWN_CANDIDATE_COUNT"] == 1
    assert result["counts"]["UNIFIED_CANDIDATE_COUNT"] == 1
    manifest_ids = {item["sourceId"] for item in result["import_manifest_candidate"]["entries"]}
    assert "e2-1" in manifest_ids


def test_exact_path_duplicate() -> None:
    e1 = _e1([_candidate("/same/report.md", "e1-1", classification="REVIEW_REQUIRED")])
    e2 = _e2([_candidate("/same/report.md", "e2-1")])
    result = _run(e1, e2)
    entry_by_id = {e["source_id"]: e for e in result["unified_inventory"]["candidates"]}
    assert entry_by_id["e1-1"]["duplicate_kind"] == con.DUP_EXACT_PATH
    assert entry_by_id["e2-1"]["duplicate_kind"] == con.DUP_EXACT_PATH
    assert result["counts"]["EXACT_PATH_DUPLICATE_COUNT"] == 2
    group = result["duplicate_review"]["groups"][0]
    assert group["duplicate_kind"] == con.DUP_EXACT_PATH
    assert group["member_count"] == 2


def test_possible_duplicate_and_name_collision() -> None:
    e1 = _e1([])
    e2 = _e2(
        [
            _candidate("/wt/a/same.md", "e2-1", filename="same.md", size=10),
            _candidate("/wt/b/same.md", "e2-2", filename="same.md", size=10),
            _candidate("/wt/a/name.md", "e2-3", filename="name.md", size=1),
            _candidate("/wt/b/name.md", "e2-4", filename="name.md", size=2),
        ]
    )
    result = _run(e1, e2)
    by_id = {e["source_id"]: e for e in result["unified_inventory"]["candidates"]}
    assert by_id["e2-1"]["duplicate_kind"] == con.DUP_POSSIBLE
    assert by_id["e2-2"]["duplicate_kind"] == con.DUP_POSSIBLE
    assert by_id["e2-3"]["duplicate_kind"] == con.DUP_NAME_COLLISION
    assert by_id["e2-4"]["duplicate_kind"] == con.DUP_NAME_COLLISION
    assert result["counts"]["POSSIBLE_DUPLICATE_COUNT"] == 2
    assert result["counts"]["NAME_COLLISION_COUNT"] == 2
    kinds = {group["duplicate_kind"] for group in result["duplicate_review"]["groups"]}
    assert kinds == {con.DUP_POSSIBLE, con.DUP_NAME_COLLISION}


def test_unique_metadata() -> None:
    result = _run(_e1([]), _e2([_candidate("/wt/unique.md", "e2-1")]))
    entry = result["unified_inventory"]["candidates"][0]
    assert entry["duplicate_group"] is None
    assert entry["selection_status"] == con.SELECTION_UNIQUE
    assert result["counts"]["UNIQUE_METADATA_COUNT"] == 1


def test_representative_selection() -> None:
    e1 = _e1([])
    e2 = _e2(
        [
            _candidate(
                "/tmp/work_bc_audit/report.md",
                "e2-bc",
                source_root="/tmp/work_bc_audit",
                worktree_path="",
            ),
            _candidate(
                "/wt/b/report.md",
                "e2-wt",
                source_root="/wt/b/docs/reports",
            ),
            _candidate(
                "/wt/a/report.md",
                "e2-wt-a",
                source_root="/wt/a/docs/reports",
            ),
        ]
    )
    result = _run(e1, e2)
    group = result["duplicate_review"]["groups"][0]
    assert group["representative_source_id"] == "e2-bc"
    by_id = {e["source_id"]: e for e in result["unified_inventory"]["candidates"]}
    assert by_id["e2-bc"]["selection_status"] == con.SELECTION_REPRESENTATIVE
    assert by_id["e2-wt"]["selection_status"] == con.SELECTION_HOLD


def test_no_unverified_deduplication() -> None:
    candidate_a = _candidate("/wt/a/same.md", "e2-1", filename="same.md", size=10)
    candidate_b = _candidate("/wt/b/same.md", "e2-2", filename="same.md", size=10)
    result = _run(_e1([]), _e2([candidate_a, candidate_b]))
    group = result["duplicate_review"]["groups"][0]
    assert group["member_count"] == 2
    assert group["deduplication_confirmed"] is False
    manifest_ids = {item["sourceId"] for item in result["import_manifest_candidate"]["entries"]}
    assert manifest_ids == {"e2-1", "e2-2"}
    statuses = {
        item["selectionStatus"]
        for item in result["import_manifest_candidate"]["entries"]
    }
    assert statuses == {con.SELECTION_REPRESENTATIVE, con.SELECTION_HOLD}


def test_source_missing_detection() -> None:
    result = _run(
        _e1([]),
        _e2([_candidate("/wt/missing.md", "e2-1")]),
        stat_func=_missing_stat,
    )
    entry = result["unified_inventory"]["candidates"][0]
    assert entry["source_status"] == con.SOURCE_MISSING
    assert result["counts"]["SOURCE_MISSING_COUNT"] == 1
    assert result["review_queues"]["counts"]["MISSING_SOURCE_FILES"] == 1


def test_source_changed_detection() -> None:
    result = _run(
        _e1([]),
        _e2([_candidate("/wt/changed.md", "e2-1", size=10, mtime=BASE_MTIME)]),
        stat_func=_stat_func(sizes={"/wt/changed.md": 99}, mtimes={"/wt/changed.md": BASE_MTIME + 5}),
    )
    entry = result["unified_inventory"]["candidates"][0]
    assert entry["source_status"] == con.SOURCE_CHANGED
    assert result["counts"]["SOURCE_CHANGED_COUNT"] == 1


def test_manifest_approved_false() -> None:
    result = _run(
        _e1([_candidate("/tmp/work_bc_audit/BC1.md", "e1-1", classification="FILENAME_MATCH_CANDIDATE")]),
        _e2([_candidate("/wt/a.md", "e2-1")]),
    )
    manifest = result["import_manifest_candidate"]
    assert manifest["approved"] is False
    assert manifest["import_ready"] is False
    assert manifest["real_import_allowed"] is False
    assert manifest["counts"]["ALL_APPROVED_FALSE"] is True
    assert manifest["counts"]["APPROVED_TRUE_COUNT"] == 0
    for entry in manifest["entries"]:
        assert entry["approved"] is False
        assert entry["provenanceStatus"] == con.PROVENANCE_UNKNOWN
        for key in (
            "sourceId",
            "path",
            "sourceType",
            "provenanceStatus",
            "duplicateGroup",
            "selectionStatus",
            "approved",
        ):
            assert key in entry


def test_review_queues_created() -> None:
    result = _run(
        _e1([_candidate("/tmp/work_bc_audit/BC1.md", "e1-1", classification="FILENAME_MATCH_CANDIDATE")]),
        _e2([_candidate("/wt/a.md", "e2-1")]),
    )
    queues = result["review_queues"]["queues"]
    names = [queue["name"] for queue in queues]
    assert names == [
        "CURSOR_CANDIDATES",
        "OTHER_AGENT_CANDIDATES",
        "CHATGPT_CANDIDATES",
        "UNKNOWN_ORIGIN_CANDIDATES",
        "POSSIBLE_DUPLICATES",
        "OUT_OF_SCOPE",
        "MISSING_SOURCE_FILES",
        "SECRET_FILENAME_EXCLUSIONS",
    ]
    for queue in queues:
        assert "count" in queue
        assert "reason_for_review" in queue
        assert "recommended_next_check" in queue
        assert isinstance(queue["representative_examples"], list)


def test_deterministic_output() -> None:
    e1 = _e1([_candidate("/tmp/work_bc_audit/BC1.md", "e1-1", classification="REVIEW_REQUIRED")])
    e2 = _e2(
        [
            _candidate("/wt/b/same.md", "e2-2", filename="same.md", size=10),
            _candidate("/wt/a/same.md", "e2-1", filename="same.md", size=10),
        ]
    )
    first = _run(e1, e2, generated_at="fixed")
    second = _run(e1, e2, generated_at="fixed")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_outputs_confined_and_named(tmp_path: Path) -> None:
    result = _run(_e1([]), _e2([_candidate("/wt/a.md", "e2-1")]))
    out = tmp_path / "out"
    paths = con.write_outputs(result, out)
    written = {Path(item).resolve() for item in paths.values()}
    assert written == {
        (out / con.UNIFIED_JSON_NAME).resolve(),
        (out / con.DUPLICATE_JSON_NAME).resolve(),
        (out / con.QUEUES_JSON_NAME).resolve(),
        (out / con.MANIFEST_JSON_NAME).resolve(),
        (out / con.SUMMARY_MD_NAME).resolve(),
    }
    assert all(item.parent == out.resolve() for item in written)


def test_no_production_write() -> None:
    source = (ROOT / "scripts" / "bc11e_candidate_consolidation.py").read_text(
        encoding="utf-8"
    )
    assert "PRODUCTION_STORE_PATH" not in source
    assert "import_readiness" not in source
    assert "sqlite" not in source
    assert "real_import(" not in source
