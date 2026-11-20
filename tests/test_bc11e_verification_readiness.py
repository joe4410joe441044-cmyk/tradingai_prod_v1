"""BC-11E-4 verification readiness tests.

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
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_verification_readiness as rd  # noqa: E402

BASE_MTIME = 1_700_000_000.0


def _iso(ts: float = BASE_MTIME) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _candidate(
    source_id: str,
    *,
    path: str | None = None,
    filename: str | None = None,
    size: int = 100,
    classification: str = "UNKNOWN_CANDIDATE",
    source_classification: str = "UNKNOWN_REPORT_CANDIDATE",
    reason: str = "ORIGIN_UNCONFIRMED",
    duplicate_group: str | None = None,
    duplicate_kind: str | None = None,
    inventory_origin: str = "BC11E2",
    selection_status: str = "UNIQUE_REVIEW_ONLY",
    source_root: str | None = None,
    worktree_path: str = "/wt",
) -> dict:
    absolute_path = path or f"/wt/docs/reports/{source_id}.md"
    return {
        "source_id": source_id,
        "absolute_path": absolute_path,
        "filename": filename if filename is not None else Path(absolute_path).name,
        "extension": ".md",
        "size_bytes": size,
        "mtime": _iso(),
        "source_root": source_root or str(Path(absolute_path).parent),
        "worktree_path": worktree_path,
        "inventory_origin": inventory_origin,
        "source_classification": source_classification,
        "classification": classification,
        "candidate_reason": reason,
        "provenance_status": "UNKNOWN",
        "origin_confirmed": False,
        "duplicate_group": duplicate_group,
        "duplicate_kind": duplicate_kind,
        "selection_status": selection_status,
        "approval_status": "UNAPPROVED",
        "approved": False,
        "source_status": "SOURCE_PRESENT",
    }


def _member(candidate: dict, *, selection_status: str = "HOLD_UNVERIFIED_NOT_DEDUPLICATED") -> dict:
    return {
        "source_id": candidate["source_id"],
        "absolute_path": candidate["absolute_path"],
        "classification": candidate["classification"],
        "inventory_origin": candidate["inventory_origin"],
        "provenance_status": candidate["provenance_status"],
        "selection_status": selection_status,
        "size_bytes": candidate["size_bytes"],
        "mtime": candidate["mtime"],
        "source_root": candidate["source_root"],
        "worktree_path": candidate["worktree_path"],
    }


def _group(
    group_id: str,
    kind: str,
    members: list[dict],
    *,
    representative: str,
    filename: str,
    size_bytes: int | None,
) -> dict:
    return {
        "duplicate_group": group_id,
        "duplicate_kind": kind,
        "filename": filename,
        "size_bytes": size_bytes,
        "member_count": len(members),
        "representative_source_id": representative,
        "members": [_member(member) for member in members],
        "deduplication_confirmed": False,
    }


def _fixtures() -> dict:
    # Priority coverage: cursor, possible duplicate, other agent, chatgpt,
    # unknown, exact path, and a name collision.
    c1 = _candidate(
        "c1",
        path="/tmp/work_bc_audit/CURSOR_REPORT.md",
        classification=rd.CLASS_CURSOR,
        source_classification="FILENAME_MATCH_CANDIDATE",
        reason="FILENAME_MATCH_BC_PREFIX",
        inventory_origin="BC11E1",
    )
    o1 = _candidate(
        "o1",
        filename="same0.md",
        size=100,
        classification=rd.CLASS_OTHER_AGENT,
        source_classification="OTHER_AGENT_REPORT_CANDIDATE",
        reason="OPENCODE_ROOT_HINT",
        duplicate_group="POSSIBLE_DUPLICATE:p1",
        duplicate_kind=rd.DUP_POSSIBLE,
        selection_status="REPRESENTATIVE_REVIEW_ONLY",
    )
    u1 = _candidate(
        "u1",
        filename="same0.md",
        size=100,
        classification=rd.CLASS_UNKNOWN,
        duplicate_group="POSSIBLE_DUPLICATE:p1",
        duplicate_kind=rd.DUP_POSSIBLE,
    )
    u2 = _candidate("u2", classification=rd.CLASS_UNKNOWN)
    o2 = _candidate(
        "o2",
        classification=rd.CLASS_OTHER_AGENT,
        source_classification="OTHER_AGENT_REPORT_CANDIDATE",
        reason="OPENCODE_ROOT_HINT",
    )
    g1 = _candidate(
        "g1",
        classification=rd.CLASS_CHATGPT,
        source_classification="CHATGPT_REVIEW_CANDIDATE",
        reason="CHATGPT_ROOT_OR_FILENAME_HINT",
    )
    u3 = _candidate(
        "u3",
        filename="name.md",
        size=1,
        duplicate_group="NAME_COLLISION:n2",
        duplicate_kind=rd.DUP_NAME_COLLISION,
        selection_status="REPRESENTATIVE_REVIEW_ONLY",
    )
    u4 = _candidate(
        "u4",
        filename="name.md",
        size=2,
        duplicate_group="NAME_COLLISION:n2",
        duplicate_kind=rd.DUP_NAME_COLLISION,
    )
    u5 = _candidate(
        "u5",
        path="/wt/exact/exact.md",
        duplicate_group="EXACT_PATH_DUPLICATE:e1",
        duplicate_kind=rd.DUP_EXACT_PATH,
        selection_status="REPRESENTATIVE_REVIEW_ONLY",
        inventory_origin="BC11E1",
    )
    u6 = _candidate(
        "u6",
        path="/wt/exact/exact.md",
        duplicate_group="EXACT_PATH_DUPLICATE:e1",
        duplicate_kind=rd.DUP_EXACT_PATH,
    )
    candidates = [c1, o1, u1, u2, o2, g1, u3, u4, u5, u6]

    groups = [
        _group(
            "POSSIBLE_DUPLICATE:p1",
            rd.DUP_POSSIBLE,
            [o1, u1],
            representative="o1",
            filename="same0.md",
            size_bytes=100,
        ),
        # Fully overlapping name collision: same members as the possible group.
        _group(
            "NAME_COLLISION:n1",
            rd.DUP_NAME_COLLISION,
            [o1, u1],
            representative="u1",
            filename="same0.md",
            size_bytes=None,
        ),
        _group(
            "NAME_COLLISION:n2",
            rd.DUP_NAME_COLLISION,
            [u3, u4],
            representative="u3",
            filename="name.md",
            size_bytes=None,
        ),
        _group(
            "EXACT_PATH_DUPLICATE:e1",
            rd.DUP_EXACT_PATH,
            [u5, u6],
            representative="u5",
            filename="exact.md",
            size_bytes=100,
        ),
    ]

    counts = {
        "UNIFIED_CANDIDATE_COUNT": len(candidates),
        "DUPLICATE_GROUP_COUNT": len(groups),
        "POSSIBLE_DUPLICATE_COUNT": sum(
            1 for item in candidates if item["duplicate_group"] is not None
        ),
        "UNIQUE_METADATA_COUNT": sum(
            1 for item in candidates if item["duplicate_group"] is None
        ),
        "CURSOR_CANDIDATE_COUNT": sum(
            1 for item in candidates if item["classification"] == rd.CLASS_CURSOR
        ),
        "OTHER_AGENT_CANDIDATE_COUNT": sum(
            1 for item in candidates if item["classification"] == rd.CLASS_OTHER_AGENT
        ),
        "CHATGPT_CANDIDATE_COUNT": sum(
            1 for item in candidates if item["classification"] == rd.CLASS_CHATGPT
        ),
        "UNKNOWN_CANDIDATE_COUNT": sum(
            1 for item in candidates if item["classification"] == rd.CLASS_UNKNOWN
        ),
        "APPROVED_TRUE_COUNT": 0,
        "SOURCE_MISSING_COUNT": 0,
        "SOURCE_CHANGED_COUNT": 0,
        "MANIFEST_CANDIDATE_COUNT": len(candidates),
    }

    unified = {
        "schema_version": "tradingai-bc11e3-unified-inventory/v1",
        "coverage_status": "ADDITIONAL_SOURCE_ROOTS_REQUIRED",
        "full_history_asserted": False,
        "counts": counts,
        "candidates": candidates,
    }

    duplicate_review = {
        "schema_version": "tradingai-bc11e3-duplicate-review/v1",
        "counts": {
            "DUPLICATE_GROUP_COUNT": len(groups),
            "POSSIBLE_DUPLICATE_GROUP_COUNT": sum(
                1 for group in groups if group["duplicate_kind"] == rd.DUP_POSSIBLE
            ),
            "NAME_COLLISION_GROUP_COUNT": sum(
                1 for group in groups if group["duplicate_kind"] == rd.DUP_NAME_COLLISION
            ),
            "EXACT_PATH_DUPLICATE_GROUP_COUNT": sum(
                1 for group in groups if group["duplicate_kind"] == rd.DUP_EXACT_PATH
            ),
        },
        "groups": groups,
    }

    review_queues = {
        "schema_version": "tradingai-bc11e3-review-queues/v1",
        "queues": [],
    }

    manifest = {
        "schema_version": "tradingai-bc11e3-import-manifest-candidate/v1",
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "counts": {
            "MANIFEST_CANDIDATE_COUNT": len(candidates),
            "APPROVED_TRUE_COUNT": 0,
            "ALL_APPROVED_FALSE": True,
        },
        "entries": [
            {
                "sourceId": item["source_id"],
                "path": item["absolute_path"],
                "sourceType": item["classification"],
                "provenanceStatus": item["provenance_status"],
                "duplicateGroup": item["duplicate_group"],
                "selectionStatus": item["selection_status"],
                "approved": False,
                "sourceStatus": item["source_status"],
            }
            for item in candidates
        ],
    }

    return {
        "unified": unified,
        "duplicate_review": duplicate_review,
        "review_queues": review_queues,
        "manifest": manifest,
    }


def _expected(fixtures: dict) -> dict:
    counts = fixtures["unified"]["counts"]
    return {
        "UNIFIED_CANDIDATE_COUNT": counts["UNIFIED_CANDIDATE_COUNT"],
        "MANIFEST_CANDIDATE_COUNT": counts["MANIFEST_CANDIDATE_COUNT"],
        "DUPLICATE_GROUP_COUNT": counts["DUPLICATE_GROUP_COUNT"],
        "POSSIBLE_DUPLICATE_COUNT": counts["POSSIBLE_DUPLICATE_COUNT"],
        "UNIQUE_METADATA_COUNT": counts["UNIQUE_METADATA_COUNT"],
        "CURSOR_CANDIDATE_COUNT": counts["CURSOR_CANDIDATE_COUNT"],
        "OTHER_AGENT_CANDIDATE_COUNT": counts["OTHER_AGENT_CANDIDATE_COUNT"],
        "CHATGPT_CANDIDATE_COUNT": counts["CHATGPT_CANDIDATE_COUNT"],
        "UNKNOWN_CANDIDATE_COUNT": counts["UNKNOWN_CANDIDATE_COUNT"],
        "SOURCE_MISSING_COUNT": counts["SOURCE_MISSING_COUNT"],
        "SOURCE_CHANGED_COUNT": counts["SOURCE_CHANGED_COUNT"],
        "ALL_APPROVED_FALSE": True,
    }


def _run(fixtures: dict | None = None, *, generated_at: str = "2026-11-08T00:00:00+00:00") -> dict:
    fixtures = fixtures or _fixtures()
    return rd.build_readiness(
        fixtures, expected=_expected(fixtures), generated_at=generated_at
    )


def test_input_validation(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(rd.InputError) as exc_info:
        rd.load_input(missing)
    assert exc_info.value.code == rd.BLOCKED_MISSING_INPUT

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    with pytest.raises(rd.InputError) as exc_info:
        rd.load_input(invalid)
    assert exc_info.value.code == rd.BLOCKED_INVALID_INPUT

    fixtures = _fixtures()
    fixtures["unified"]["candidates"] = "not a list"
    with pytest.raises(rd.InputError) as exc_info:
        rd.validate_inputs(fixtures, expected=_expected(_fixtures()))
    assert exc_info.value.code == rd.BLOCKED_INVALID_INPUT

    fixtures = _fixtures()
    del fixtures["unified"]["candidates"][0]["source_id"]
    with pytest.raises(rd.InputError) as exc_info:
        rd.validate_inputs(fixtures, expected=_expected(_fixtures()))
    assert exc_info.value.code == rd.BLOCKED_INVALID_INPUT


def test_candidate_count_reconciliation() -> None:
    fixtures = _fixtures()
    result = rd.validate_inputs(fixtures, expected=_expected(fixtures))
    assert result["status"] == rd.INPUTS_VALID
    assert result["inputs_valid"] is True
    assert result["mismatches"] == []

    bad_expected = _expected(fixtures)
    bad_expected["UNIFIED_CANDIDATE_COUNT"] += 1
    broken = rd.validate_inputs(fixtures, expected=bad_expected)
    assert broken["status"] == rd.INPUT_COUNT_MISMATCH
    assert broken["inputs_valid"] is False
    assert any(item["key"] == "UNIFIED_CANDIDATE_COUNT" for item in broken["mismatches"])

    bad_expected = _expected(fixtures)
    bad_expected["UNKNOWN_CANDIDATE_COUNT"] += 1
    broken = rd.validate_inputs(fixtures, expected=bad_expected)
    assert broken["status"] == rd.INPUT_COUNT_MISMATCH


def test_duplicate_group_integrity() -> None:
    result = _run()
    plan = result["duplicate_verification_plan"]
    candidate_ids = {
        item["source_id"] for item in _fixtures()["unified"]["candidates"]
    }
    registered: list[str] = []
    for group in plan["groups"]:
        assert group["member_count"] == len(group["member_source_ids"])
        assert group["member_source_ids"] == sorted(group["member_source_ids"])
        assert set(group["member_source_ids"]).issubset(candidate_ids)
        assert group["verification_status"] == rd.VERIFICATION_NOT_STARTED
        assert group["deduplication_confirmed"] is False
        registered.extend(group["member_source_ids"])
    assert plan["duplicate_candidate_count"] == len(set(registered))
    assert plan["counts"]["DUPLICATE_CANDIDATE_COUNT"] == 6


def test_overlapping_group_deduplication() -> None:
    result = _run()
    plan = result["duplicate_verification_plan"]
    seen: dict[str, str] = {}
    for group in plan["groups"]:
        for source_id in group["member_source_ids"]:
            assert source_id not in seen, "candidate registered as two verification targets"
            seen[source_id] = group["group_id"]

    assert len(seen) == 6
    merged = {item["duplicate_group"]: item for item in plan["overlapping_groups_merged"]}
    assert "NAME_COLLISION:n1" in merged
    overlap = merged["NAME_COLLISION:n1"]
    assert overlap["overlap_status"] == "FULLY_OVERLAPPING_MERGED"
    assert overlap["registered_member_count"] == 0
    assert overlap["merged_into_group_ids"] == ["POSSIBLE_DUPLICATE:p1"]
    assert plan["counts"]["OVERLAPPING_GROUP_COUNT"] == 1
    assert plan["counts"]["VERIFICATION_GROUP_COUNT"] == 3


def test_representative_preservation() -> None:
    result = _run()
    plan = result["duplicate_verification_plan"]
    groups = {group["group_id"]: group for group in plan["groups"]}
    possible = groups["POSSIBLE_DUPLICATE:p1"]
    assert possible["representative_source_id"] == "o1"
    assert possible["representative_preserved"] is True
    assert possible["representative_change_reason"] is None
    assert possible["member_count"] == 2

    fixtures = _fixtures()
    for group in fixtures["duplicate_review"]["groups"]:
        if group["duplicate_group"] == "POSSIBLE_DUPLICATE:p1":
            group["representative_source_id"] = "does-not-exist"
    plan = rd.build_readiness(
        fixtures, expected=_expected(fixtures), generated_at="fixed"
    )["duplicate_verification_plan"]
    possible = {
        group["group_id"]: group for group in plan["groups"]
    }["POSSIBLE_DUPLICATE:p1"]
    assert possible["representative_preserved"] is False
    assert possible["representative_source_id"] in possible["member_source_ids"]
    assert (
        possible["representative_change_reason"]
        == "ORIGINAL_REPRESENTATIVE_REASSIGNED_DUE_TO_OVERLAP_RESOLUTION"
    )


def test_verification_priority() -> None:
    result = _run()
    queue = result["verification_queue"]
    priorities = {item["source_id"]: item["verification_priority"] for item in queue["items"]}
    assert priorities["c1"] == rd.PRIORITY_P0
    assert priorities["o1"] == rd.PRIORITY_P1
    assert priorities["u1"] == rd.PRIORITY_P1
    assert priorities["u5"] == rd.PRIORITY_P1
    assert priorities["u6"] == rd.PRIORITY_P1
    assert priorities["o2"] == rd.PRIORITY_P2
    assert priorities["g1"] == rd.PRIORITY_P3
    assert priorities["u2"] == rd.PRIORITY_P4
    assert priorities["u3"] == rd.PRIORITY_P4
    assert priorities["u4"] == rd.PRIORITY_P4

    counts = queue["counts"]["PRIORITY_COUNTS"]
    assert counts == {"P0": 1, "P1": 4, "P2": 1, "P3": 1, "P4": 3}

    groups = {
        group["group_id"]: group
        for group in result["duplicate_verification_plan"]["groups"]
    }
    assert groups["POSSIBLE_DUPLICATE:p1"]["verification_priority"] == rd.PRIORITY_P1
    assert groups["NAME_COLLISION:n2"]["verification_priority"] == rd.PRIORITY_P4
    assert groups["EXACT_PATH_DUPLICATE:e1"]["verification_priority"] == rd.PRIORITY_P1

    assert queue["items"][0]["verification_priority"] == rd.PRIORITY_P0
    assert queue["items"][0]["queue_position"] == 1


def test_provenance_safety() -> None:
    result = _run()
    plan = result["provenance_review_plan"]
    assert plan["counts"]["CONFIRMED_CURSOR_COUNT"] == 0
    assert plan["counts"]["CONFIRMED_OTHER_AGENT_COUNT"] == 0
    assert plan["counts"]["CONFIRMED_CHATGPT_COUNT"] == 0
    entries = {entry["source_id"]: entry for entry in plan["entries"]}
    for entry in plan["entries"]:
        assert entry["provenance_status"] == "UNKNOWN"
        assert entry["review_status"] == rd.REVIEW_NOT_STARTED
        assert entry["confirmed_cursor"] is False
        assert entry["confirmed_other_agent"] is False
        assert entry["confirmed_chatgpt"] is False
        assert entry["metadata_confirmed_cursor"] is False
        assert entry["metadata_confirmed_other_agent"] is False
        assert entry["metadata_confirmed_chatgpt"] is False
    assert entries["c1"]["evidence_type"] == "FILENAME_PREFIX_HINT"
    assert entries["o1"]["evidence_type"] == "DIRECTORY_HINT"
    assert entries["g1"]["evidence_type"] == "DIRECTORY_OR_FILENAME_HINT"
    assert entries["g1"]["classification"] == rd.CLASS_CHATGPT
    assert entries["g1"]["confirmed_chatgpt"] is False


def test_unknown_preservation() -> None:
    fixtures = _fixtures()
    result = _run(fixtures)
    unknown_ids = {
        item["source_id"]
        for item in fixtures["unified"]["candidates"]
        if item["classification"] == rd.CLASS_UNKNOWN
    }
    assert unknown_ids == {"u1", "u2", "u3", "u4", "u5", "u6"}

    queue_ids = {item["source_id"] for item in result["verification_queue"]["items"]}
    review_ids = {entry["source_id"] for entry in result["provenance_review_plan"]["entries"]}
    readiness_ids = {
        entry["source_id"] for entry in result["import_readiness_candidate"]["entries"]
    }
    assert unknown_ids.issubset(queue_ids)
    assert unknown_ids.issubset(review_ids)
    assert unknown_ids.issubset(readiness_ids)
    assert result["verification_queue"]["counts"]["PRIORITY_COUNTS"]["P4"] == 3


def test_manifest_approved_false() -> None:
    result = _run()
    readiness = result["import_readiness_candidate"]
    assert readiness["approved"] is False
    assert readiness["import_ready"] is False
    assert readiness["real_import_allowed"] is False
    assert readiness["operator_review_required"] is True
    assert readiness["counts"]["ALL_APPROVED_FALSE"] is True
    assert readiness["counts"]["ALL_IMPORT_READY_FALSE"] is True
    assert readiness["counts"]["APPROVED_TRUE_COUNT"] == 0
    assert readiness["counts"]["IMPORT_READY_TRUE_COUNT"] == 0
    for entry in readiness["entries"]:
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False
        assert entry["approval_status"] == rd.APPROVAL_UNAPPROVED
        for key in (
            "source_id",
            "path",
            "provenance_status",
            "duplicate_group",
            "verification_status",
            "review_status",
            "approval_status",
        ):
            assert key in entry


def test_all_verification_not_started() -> None:
    result = _run()
    assert result["counts"]["ALL_VERIFICATION_NOT_STARTED"] is True
    assert result["duplicate_verification_plan"]["counts"]["ALL_VERIFICATION_NOT_STARTED"] is True
    assert result["verification_queue"]["counts"]["ALL_VERIFICATION_NOT_STARTED"] is True
    assert result["import_readiness_candidate"]["counts"]["ALL_VERIFICATION_NOT_STARTED"] is True
    assert all(
        item["verification_status"] == rd.VERIFICATION_NOT_STARTED
        for item in result["verification_queue"]["items"]
    )


def test_no_source_content_read(monkeypatch) -> None:
    fixtures = _fixtures()

    def boom(*args, **kwargs):
        raise AssertionError("report content was read during readiness planning")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        patch.setattr(io, "open", boom)
        patch.setattr(Path, "open", boom)
        patch.setattr(Path, "read_text", boom)
        patch.setattr(Path, "read_bytes", boom)
        result = _run(fixtures)
    assert result["counts"]["UNIFIED_CANDIDATE_COUNT"] == 10
    assert result["duplicate_verification_plan"]["content_read"] is False


def test_no_content_hash_in_source() -> None:
    source = (ROOT / "scripts" / "bc11e_verification_readiness.py").read_text(
        encoding="utf-8"
    )
    for token in ("import hashlib", "sha256(", "sha1(", "md5(", "blake2", "content_hash("):
        assert token not in source
    assert '"hash_computed": False' in source


def test_no_import_in_source() -> None:
    source = (ROOT / "scripts" / "bc11e_verification_readiness.py").read_text(
        encoding="utf-8"
    )
    for token in ("real_import(", "import_report(", "import_knowledge(", "ingest_report("):
        assert token not in source
    result = _run()
    assert result["duplicate_verification_plan"]["real_import_executed"] is False
    assert result["import_readiness_candidate"]["real_import_executed"] is False


def test_no_production_write(tmp_path: Path) -> None:
    source = (ROOT / "scripts" / "bc11e_verification_readiness.py").read_text(
        encoding="utf-8"
    )
    for token in ("PRODUCTION_STORE_PATH", "sqlite", "production_db", "/var/lib/tradingai"):
        assert token not in source

    result = _run()
    out = tmp_path / "out"
    paths = rd.write_outputs(result, out)
    written = {Path(item).resolve() for item in paths.values()}
    assert all(item.parent == out.resolve() for item in written)
    assert len(written) == 5


def test_outputs_named_and_distinct_from_bc11e3(tmp_path: Path) -> None:
    result = _run()
    out = tmp_path / "out"
    paths = rd.write_outputs(result, out)
    assert {Path(item).name for item in paths.values()} == {
        rd.DUPLICATE_PLAN_JSON_NAME,
        rd.PROVENANCE_PLAN_JSON_NAME,
        rd.QUEUE_JSON_NAME,
        rd.READINESS_JSON_NAME,
        rd.SUMMARY_MD_NAME,
    }
    assert not any(name.startswith("BC11E3") for name in {Path(item).name for item in paths.values()})


def test_coverage_and_metadata_flags() -> None:
    result = _run()
    assert result["coverage_status"] == "ADDITIONAL_SOURCE_ROOTS_REQUIRED"
    assert result["full_history_asserted"] is False
    for key in (
        "duplicate_verification_plan",
        "provenance_review_plan",
        "verification_queue",
        "import_readiness_candidate",
    ):
        payload = result[key]
        assert payload["content_read"] is False
        assert payload["hash_computed"] is False
        assert payload["real_import_executed"] is False


def test_deterministic_output() -> None:
    first = _run()
    second = _run()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    fixtures = _fixtures()
    fixtures["duplicate_review"]["groups"] = list(
        reversed(fixtures["duplicate_review"]["groups"])
    )
    reordered = rd.build_readiness(
        fixtures, expected=_expected(fixtures), generated_at="2026-11-08T00:00:00+00:00"
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(reordered, sort_keys=True)
