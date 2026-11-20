"""BC-11E-5 content deduplication tests.

All fixtures are synthetic and live under a pytest temporary directory. No test
reads a real saved report, touches the production knowledge store, or performs a
real import.
"""

from __future__ import annotations

import builtins
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_content_deduplication as cd  # noqa: E402

BASE_MTIME = 1_700_000_000.0


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _write(path: Path, content: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def _candidate(
    source_id: str,
    *,
    absolute_path: Path,
    source_root: Path,
    content: bytes,
    mtime: float,
    classification: str = cd.CLASS_UNKNOWN,
    source_classification: str = "UNKNOWN_REPORT_CANDIDATE",
    provenance_status: str = cd.PROVENANCE_UNKNOWN,
    duplicate_group: str | None = None,
    duplicate_kind: str | None = None,
    inventory_origin: str = "BC11E2",
    selection_status: str = "UNIQUE_REVIEW_ONLY",
) -> dict:
    return {
        "source_id": source_id,
        "absolute_path": str(absolute_path),
        "filename": absolute_path.name,
        "extension": absolute_path.suffix,
        "size_bytes": len(content),
        "mtime": _iso(mtime),
        "source_root": str(source_root),
        "worktree_path": "/synthetic",
        "inventory_origin": inventory_origin,
        "source_classification": source_classification,
        "classification": classification,
        "candidate_reason": "ORIGIN_UNCONFIRMED",
        "provenance_status": provenance_status,
        "origin_confirmed": False,
        "duplicate_group": duplicate_group,
        "duplicate_kind": duplicate_kind,
        "selection_status": selection_status,
        "approval_status": "UNAPPROVED",
        "approved": False,
        "source_status": "SOURCE_PRESENT",
    }


def _fixtures(root: Path, *, create_files: bool = True) -> dict:
    spec = [
        ("c1", "docs/reports", b"alpha\n", cd.CLASS_CURSOR, "FILENAME_MATCH_CANDIDATE", None, None, "P0"),
        ("o1", "docs/reports", b"same-body\n", cd.CLASS_OTHER_AGENT, "OTHER_AGENT_REPORT_CANDIDATE", "POSSIBLE_DUPLICATE:p1", "POSSIBLE_DUPLICATE", "P1"),
        ("u1", "tmp/reports", b"same-body\n", cd.CLASS_UNKNOWN, "UNKNOWN_REPORT_CANDIDATE", "POSSIBLE_DUPLICATE:p1", "POSSIBLE_DUPLICATE", "P1"),
        ("u2", "tmp/reports", b"unique-body\n", cd.CLASS_UNKNOWN, "UNKNOWN_REPORT_CANDIDATE", None, None, "P4"),
        ("u3", "reports", b"collision-a\n", cd.CLASS_UNKNOWN, "UNKNOWN_REPORT_CANDIDATE", "NAME_COLLISION:n2", "NAME_COLLISION", "P4"),
        ("u4", "reports", b"collision-b\n", cd.CLASS_UNKNOWN, "UNKNOWN_REPORT_CANDIDATE", "NAME_COLLISION:n2", "NAME_COLLISION", "P4"),
    ]

    candidates: list[dict] = []
    priorities: dict[str, str] = {}
    for index, (source_id, rel_dir, content, classification, source_classification, group, kind, priority) in enumerate(spec):
        mtime = BASE_MTIME + index
        source_root = root / rel_dir
        absolute_path = source_root / f"{source_id}.md"
        if create_files:
            _write(absolute_path, content, mtime)
        candidates.append(
            _candidate(
                source_id,
                absolute_path=absolute_path,
                source_root=source_root,
                content=content,
                mtime=mtime,
                classification=classification,
                source_classification=source_classification,
                duplicate_group=group,
                duplicate_kind=kind,
            )
        )
        priorities[source_id] = priority

    by_id = {candidate["source_id"]: candidate for candidate in candidates}
    duplicate_candidates = [c for c in candidates if c["duplicate_group"] is not None]

    groups = [
        {
            "duplicate_group": "POSSIBLE_DUPLICATE:p1",
            "duplicate_kind": "POSSIBLE_DUPLICATE",
            "filename": "o1.md",
            "size_bytes": len(b"same-body\n"),
            "member_count": 2,
            "representative_source_id": "o1",
            "members": [
                {"source_id": "o1"},
                {"source_id": "u1"},
            ],
            "deduplication_confirmed": False,
        },
        {
            "duplicate_group": "NAME_COLLISION:n2",
            "duplicate_kind": "NAME_COLLISION",
            "filename": "name.md",
            "size_bytes": len(b"collision-a\n"),
            "member_count": 2,
            "representative_source_id": "u3",
            "members": [
                {"source_id": "u3"},
                {"source_id": "u4"},
            ],
            "deduplication_confirmed": False,
        },
    ]

    unified = {
        "schema_version": "tradingai-bc11e3-unified-inventory/v1",
        "counts": {
            "UNIFIED_CANDIDATE_COUNT": len(candidates),
            "DUPLICATE_GROUP_COUNT": len(groups),
            "POSSIBLE_DUPLICATE_COUNT": len(duplicate_candidates),
            "UNIQUE_METADATA_COUNT": len(candidates) - len(duplicate_candidates),
            "APPROVED_TRUE_COUNT": 0,
            "SOURCE_MISSING_COUNT": 0,
            "SOURCE_CHANGED_COUNT": 0,
        },
        "candidates": candidates,
    }

    duplicate_review = {
        "schema_version": "tradingai-bc11e3-duplicate-review/v1",
        "counts": {
            "DUPLICATE_GROUP_COUNT": len(groups),
            "POSSIBLE_DUPLICATE_GROUP_COUNT": 1,
            "NAME_COLLISION_GROUP_COUNT": 1,
        },
        "groups": groups,
    }

    manifest = {
        "schema_version": "tradingai-bc11e3-import-manifest-candidate/v1",
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "counts": {"MANIFEST_CANDIDATE_COUNT": len(candidates), "APPROVED_TRUE_COUNT": 0},
        "entries": [
            {
                "sourceId": candidate["source_id"],
                "path": candidate["absolute_path"],
                "sourceType": candidate["classification"],
                "provenanceStatus": candidate["provenance_status"],
                "duplicateGroup": candidate["duplicate_group"],
                "selectionStatus": candidate["selection_status"],
                "approved": False,
                "sourceStatus": candidate["source_status"],
            }
            for candidate in candidates
        ],
    }

    verification_plan = {
        "schema_version": "tradingai-bc11e4-duplicate-verification-plan/v1",
        "groups": [
            {
                "group_id": group["duplicate_group"],
                "duplicate_kind": group["duplicate_kind"],
                "member_count": group["member_count"],
                "member_source_ids": [member["source_id"] for member in group["members"]],
                "verification_status": cd.VERIFICATION_NOT_STARTED,
                "deduplication_confirmed": False,
            }
            for group in groups
        ],
    }

    provenance_plan = {
        "schema_version": "tradingai-bc11e4-provenance-review-plan/v1",
        "entries": [
            {
                "source_id": candidate["source_id"],
                "provenance_status": candidate["provenance_status"],
                "review_status": cd.REVIEW_NOT_STARTED,
                "confirmed_cursor": False,
                "confirmed_other_agent": False,
                "confirmed_chatgpt": False,
            }
            for candidate in candidates
        ],
    }

    verification_queue = {
        "schema_version": "tradingai-bc11e4-verification-queue/v1",
        "items": [
            {
                "source_id": candidate["source_id"],
                "verification_priority": priorities[candidate["source_id"]],
                "verification_status": cd.VERIFICATION_NOT_STARTED,
                "duplicate_group": candidate["duplicate_group"],
            }
            for candidate in candidates
        ],
    }

    readiness = {
        "schema_version": "tradingai-bc11e4-import-readiness-candidate/v1",
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "entries": [
            {
                "source_id": candidate["source_id"],
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "verification_status": cd.VERIFICATION_NOT_STARTED,
            }
            for candidate in candidates
        ],
    }

    return {
        "unified": unified,
        "duplicate_review": duplicate_review,
        "manifest": manifest,
        "verification_plan": verification_plan,
        "provenance_plan": provenance_plan,
        "verification_queue": verification_queue,
        "readiness": readiness,
    }


def _expected(fixtures: dict) -> dict:
    unified = fixtures["unified"]
    return {
        "UNIFIED_CANDIDATE_COUNT": len(unified["candidates"]),
        "MANIFEST_CANDIDATE_COUNT": len(fixtures["manifest"]["entries"]),
        "DUPLICATE_CANDIDATE_COUNT": sum(
            1 for candidate in unified["candidates"] if candidate["duplicate_group"] is not None
        ),
        "SOURCE_DUPLICATE_GROUP_COUNT": len(fixtures["duplicate_review"]["groups"]),
        "NAME_COLLISION_GROUP_COUNT": sum(
            1
            for group in fixtures["duplicate_review"]["groups"]
            if group["duplicate_kind"] == "NAME_COLLISION"
        ),
        "VERIFICATION_GROUP_COUNT": len(fixtures["verification_plan"]["groups"]),
        "VERIFICATION_QUEUE_COUNT": len(fixtures["verification_queue"]["items"]),
        "PROVENANCE_REVIEW_COUNT": len(fixtures["provenance_plan"]["entries"]),
        "IMPORT_READINESS_CANDIDATE_COUNT": len(fixtures["readiness"]["entries"]),
        "ALL_APPROVED_FALSE": True,
        "ALL_VERIFICATION_NOT_STARTED": True,
        "ALL_IMPORT_READY_FALSE": True,
    }


def _stage_a(fixtures: dict, root: Path, *, generated_at: str = "2026-11-08T00:00:00+00:00") -> dict:
    return cd.build_stage_a(
        fixtures,
        expected=_expected(fixtures),
        generated_at=generated_at,
        extra_approved_roots=(root,),
    )


def _stage_b(fixtures: dict, root: Path, *, chunk_size: int = cd.HASH_CHUNK_SIZE) -> dict:
    return cd.build_stage_b(
        fixtures,
        approval=cd.STAGE_B_APPROVAL_TOKEN,
        expected=_expected(fixtures),
        generated_at="2026-11-08T00:00:00+00:00",
        chunk_size=chunk_size,
        extra_approved_roots=(root,),
    )


def test_input_validation(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(cd.InputError) as exc_info:
        cd.load_input(missing)
    assert exc_info.value.code == cd.BLOCKED_MISSING_INPUT

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    with pytest.raises(cd.InputError) as exc_info:
        cd.load_input(invalid)
    assert exc_info.value.code == cd.BLOCKED_INVALID_INPUT

    fixtures = _fixtures(tmp_path)
    fixtures["manifest"]["entries"] = "not a list"
    with pytest.raises(cd.InputError):
        cd.validate_inputs(fixtures, expected=_expected(_fixtures(tmp_path)))

    fixtures = _fixtures(tmp_path)
    del fixtures["unified"]["candidates"][0]["source_id"]
    with pytest.raises(cd.InputError):
        cd.validate_inputs(fixtures, expected=_expected(_fixtures(tmp_path)))

    fixtures = _fixtures(tmp_path)
    bad = _expected(fixtures)
    bad["UNIFIED_CANDIDATE_COUNT"] += 1
    result = cd.validate_inputs(fixtures, expected=bad)
    assert result["status"] == cd.INPUT_COUNT_MISMATCH
    assert any(item["key"] == "UNIFIED_CANDIDATE_COUNT" for item in result["mismatches"])


def test_metadata_consistency(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    plan = _stage_a(fixtures, tmp_path)["plan"]
    by_id = {candidate["source_id"]: candidate for candidate in plan["candidates"]}
    assert by_id["c1"]["source_status"] == cd.SOURCE_PRESENT
    assert by_id["c1"]["hash_required"] is True

    target = tmp_path / "docs" / "reports" / "c1.md"
    target.write_bytes(b"changed-size\n")
    plan = _stage_a(fixtures, tmp_path)["plan"]
    by_id = {candidate["source_id"]: candidate for candidate in plan["candidates"]}
    assert by_id["c1"]["source_status"] == cd.SOURCE_CHANGED_SINCE_INVENTORY
    assert by_id["c1"]["hash_required"] is False

    target.unlink()
    plan = _stage_a(fixtures, tmp_path)["plan"]
    by_id = {candidate["source_id"]: candidate for candidate in plan["candidates"]}
    assert by_id["c1"]["source_status"] == cd.SOURCE_MISSING
    assert plan["counts"]["SOURCE_MISSING_COUNT"] == 1


def test_approved_root_validation(tmp_path: Path) -> None:
    candidate = {
        "source_id": "x1",
        "absolute_path": str(tmp_path / "unapproved" / "reports" / "x1.md"),
        "filename": "x1.md",
        "size_bytes": 1,
        "mtime": _iso(BASE_MTIME),
        "source_root": str(tmp_path / "unapproved" / "reports"),
        "inventory_origin": "BC11E2",
        "source_classification": "UNKNOWN_REPORT_CANDIDATE",
        "provenance_status": "UNKNOWN",
    }
    inspection = cd.inspect_candidate(
        candidate, extra_approved_roots=(tmp_path / "docs",)
    )
    assert inspection["rejection_reason"] == cd.REJECT_SOURCE_ROOT_NOT_APPROVED

    canonical_candidate = dict(candidate)
    canonical_candidate["source_root"] = str(cd.CANONICAL_ROOT / "docs" / "reports")
    canonical_candidate["absolute_path"] = str(
        cd.CANONICAL_ROOT / "docs" / "reports" / "x1.md"
    )
    inspection = cd.inspect_candidate(
        canonical_candidate, extra_approved_roots=(cd.CANONICAL_ROOT,)
    )
    assert inspection["rejection_reason"] == cd.REJECT_SOURCE_ROOT_NOT_APPROVED


def test_symlink_rejection(tmp_path: Path) -> None:
    root = tmp_path
    real = root / "docs" / "reports" / "real.md"
    _write(real, b"symlink-target\n", BASE_MTIME)
    link = root / "docs" / "reports" / "link.md"
    link.symlink_to(real)
    candidate = _candidate(
        "s1",
        absolute_path=link,
        source_root=root / "docs" / "reports",
        content=b"symlink-target\n",
        mtime=BASE_MTIME,
    )
    inspection = cd.inspect_candidate(candidate, extra_approved_roots=(root,))
    assert inspection["rejection_reason"] == cd.REJECT_SYMLINK
    assert inspection["hash_required"] is False


def test_path_traversal_rejection(tmp_path: Path) -> None:
    root = tmp_path
    candidate = _candidate(
        "t1",
        absolute_path=root / "docs" / "reports" / ".." / "escape.md",
        source_root=root / "docs" / "reports",
        content=b"escape\n",
        mtime=BASE_MTIME,
    )
    inspection = cd.inspect_candidate(candidate, extra_approved_roots=(root,))
    assert inspection["rejection_reason"] == cd.REJECT_PATH_TRAVERSAL

    mismatch = _candidate(
        "t2",
        absolute_path=root / "docs" / "reports" / "actual.md",
        source_root=root / "docs" / "reports",
        content=b"x\n",
        mtime=BASE_MTIME,
    )
    mismatch["filename"] = "other.md"
    inspection = cd.inspect_candidate(mismatch, extra_approved_roots=(root,))
    assert inspection["rejection_reason"] == cd.REJECT_FILENAME_MISMATCH


def test_secret_filename_rejection(tmp_path: Path) -> None:
    root = tmp_path
    secret = _candidate(
        "k1",
        absolute_path=root / "docs" / "reports" / "credentials.json",
        source_root=root / "docs" / "reports",
        content=b"{}\n",
        mtime=BASE_MTIME,
    )
    inspection = cd.inspect_candidate(secret, extra_approved_roots=(root,))
    assert inspection["rejection_reason"] == cd.REJECT_SECRET_FILENAME


def test_duplicate_path_handling(tmp_path: Path) -> None:
    root = tmp_path
    shared = root / "docs" / "reports" / "shared.md"
    _write(shared, b"shared\n", BASE_MTIME)
    candidates = [
        _candidate("a1", absolute_path=shared, source_root=root / "docs" / "reports", content=b"shared\n", mtime=BASE_MTIME),
        _candidate("b2", absolute_path=shared, source_root=root / "docs" / "reports", content=b"shared\n", mtime=BASE_MTIME),
    ]
    fixtures = {
        "unified": {"candidates": candidates, "counts": {}},
        "verification_queue": {
            "items": [
                {
                    "source_id": candidate["source_id"],
                    "verification_priority": "P4",
                    "verification_status": cd.VERIFICATION_NOT_STARTED,
                    "duplicate_group": None,
                }
                for candidate in candidates
            ]
        },
    }
    plan = cd.build_hash_plan(
        fixtures, generated_at="fixed", extra_approved_roots=(root,)
    )
    by_id = {candidate["source_id"]: candidate for candidate in plan["candidates"]}
    assert by_id["a1"]["hash_required"] is True
    assert by_id["a1"]["duplicate_path_of"] is None
    assert by_id["b2"]["hash_required"] is False
    assert by_id["b2"]["duplicate_path_of"] == "a1"
    assert plan["counts"]["HASH_TARGET_COUNT"] == 1
    assert plan["counts"]["DUPLICATE_PATH_SKIPPED_COUNT"] == 1


def test_hash_plan_determinism(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    first = _stage_a(fixtures, tmp_path)["plan"]
    second = _stage_a(fixtures, tmp_path)["plan"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    fixtures["unified"]["candidates"] = list(reversed(fixtures["unified"]["candidates"]))
    reordered = _stage_a(fixtures, tmp_path)["plan"]
    assert json.dumps(first, sort_keys=True) == json.dumps(reordered, sort_keys=True)


def test_no_hash_during_stage_a(tmp_path: Path, monkeypatch) -> None:
    fixtures = _fixtures(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("STAGE_A must not hash or read source content")

    with monkeypatch.context() as patch:
        patch.setattr(cd.hashlib, "sha256", boom)
        patch.setattr(builtins, "open", boom)
        patch.setattr(io, "open", boom)
        patch.setattr(Path, "open", boom)
        patch.setattr(Path, "read_text", boom)
        patch.setattr(Path, "read_bytes", boom)
        patch.setattr(os, "read", boom)
        result = _stage_a(fixtures, tmp_path)

    plan = result["plan"]
    assert plan["content_read"] is False
    assert plan["hash_computed"] is False
    assert plan["counts"]["ALL_HASH_STATUS_NOT_STARTED"] is True
    assert all(
        candidate["hash_status"] == cd.HASH_NOT_STARTED
        for candidate in plan["candidates"]
    )


def test_stage_b_approval_gate(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    with pytest.raises(PermissionError):
        cd.build_stage_b(
            fixtures,
            approval=cd.STAGE_B_APPROVED_NO,
            expected=_expected(fixtures),
            extra_approved_roots=(tmp_path,),
        )
    argv = [
        "--stage-b",
        "--unified", str(tmp_path / "missing.json"),
    ]
    assert cd.main(argv) == 3


def test_chunked_hashing(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "chunked.md"
    content = b"0123456789"
    _write(path, content, BASE_MTIME)

    calls: list[int] = []
    real_read = os.read

    def counting_read(fd: int, size: int) -> bytes:
        calls.append(size)
        return real_read(fd, size)

    with monkeypatch.context() as patch:
        patch.setattr(cd.os, "read", counting_read)
        result = cd.hash_file(
            path,
            expected_size=len(content),
            expected_mtime=_iso(BASE_MTIME),
            chunk_size=3,
        )

    assert result["status"] == cd.HASHED
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    assert result["bytes_read"] == len(content)
    assert result["body_stored"] is False
    assert len(calls) >= 5


def test_no_source_body_logging(tmp_path: Path) -> None:
    marker = b"DO-NOT-LOG-THIS-UNIQUE-MARKER"
    fixtures = _fixtures(tmp_path)
    target = tmp_path / "docs" / "reports" / "c1.md"
    _write(target, marker + b"\n", BASE_MTIME)
    fixtures["unified"]["candidates"][0]["size_bytes"] = len(marker) + 1
    fixtures["unified"]["candidates"][0]["mtime"] = _iso(BASE_MTIME)

    stage_b = _stage_b(fixtures, tmp_path)
    dump = json.dumps(
        {
            "results": stage_b["results"],
            "confirmed": stage_b["confirmed_duplicates"],
            "unique": stage_b["unique_content_candidates"],
        },
        sort_keys=True,
    )
    assert marker.decode() not in dump
    assert all(entry["body_stored"] is False for entry in stage_b["results"]["entries"])


def test_source_changed_detection(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    plan = _stage_a(fixtures, tmp_path)["plan"]

    target = tmp_path / "docs" / "reports" / "c1.md"
    changed_mtime = BASE_MTIME + 500
    os.utime(target, (changed_mtime, changed_mtime))
    results = cd.execute_hash_plan(
        plan, generated_at="fixed", chunk_size=cd.HASH_CHUNK_SIZE
    )
    by_id = {entry["source_id"]: entry for entry in results["entries"]}
    assert by_id["c1"]["verification_status"] == cd.SOURCE_CHANGED_DURING_HASH
    assert results["counts"]["SOURCE_CHANGED_DURING_HASH_COUNT"] == 1

    fixtures = _fixtures(tmp_path)
    plan = _stage_a(fixtures, tmp_path)["plan"]
    (tmp_path / "tmp" / "reports" / "u2.md").unlink()
    results = cd.execute_hash_plan(plan, generated_at="fixed")
    by_id = {entry["source_id"]: entry for entry in results["entries"]}
    assert by_id["u2"]["verification_status"] == cd.READ_FAILED
    assert results["counts"]["READ_FAILED_COUNT"] == 1


def test_hash_equality(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    stage_b = _stage_b(fixtures, tmp_path)
    by_id = {entry["source_id"]: entry for entry in stage_b["results"]["entries"]}
    assert by_id["o1"]["verification_status"] == cd.CONTENT_IDENTICAL
    assert by_id["u1"]["verification_status"] == cd.CONTENT_IDENTICAL
    assert by_id["o1"]["sha256"] == by_id["u1"]["sha256"]

    confirmed = stage_b["confirmed_duplicates"]
    assert confirmed["counts"]["CONFIRMED_DUPLICATE_GROUP_COUNT"] == 1
    group = confirmed["groups"][0]
    assert group["member_source_ids"] == ["o1", "u1"]
    assert group["representative_is_import_approval"] is False
    assert group["approved"] is False
    assert len(group["source_paths"]) == 2


def test_hash_difference(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    stage_b = _stage_b(fixtures, tmp_path)
    by_id = {entry["source_id"]: entry for entry in stage_b["results"]["entries"]}
    # Same name/size candidates with different bytes must not be identical.
    assert by_id["u3"]["size_bytes"] == by_id["u4"]["size_bytes"]
    assert by_id["u3"]["sha256"] != by_id["u4"]["sha256"]
    assert by_id["u3"]["verification_status"] == cd.CONTENT_DIFFERENT
    assert by_id["u4"]["verification_status"] == cd.CONTENT_DIFFERENT
    assert by_id["u2"]["verification_status"] == cd.CONTENT_DIFFERENT
    assert stage_b["unique_content_candidates"]["counts"][
        "UNIQUE_CONTENT_CANDIDATE_COUNT"
    ] == 4


def test_provenance_preservation(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    stage_b = _stage_b(fixtures, tmp_path)
    for entry in stage_b["results"]["entries"]:
        assert entry["provenance_status"] == cd.PROVENANCE_UNKNOWN
    for group in stage_b["confirmed_duplicates"]["groups"]:
        assert "provenance_status" not in group
    assert stage_b["plan"]["approved"] is False


def test_manifest_approved_false(tmp_path: Path) -> None:
    fixtures = _fixtures(tmp_path)
    stage_a = _stage_a(fixtures, tmp_path)
    assert stage_a["plan"]["approved"] is False
    assert stage_a["plan"]["import_ready"] is False
    assert stage_a["plan"]["counts"]["ALL_APPROVED_FALSE"] is True
    assert stage_a["plan"]["counts"]["ALL_APPROVAL_REQUIRED_TRUE"] is True

    stage_b = _stage_b(fixtures, tmp_path)
    assert stage_b["confirmed_duplicates"]["approved"] is False
    assert stage_b["unique_content_candidates"]["approved"] is False
    assert stage_b["confirmed_duplicates"]["counts"]["ALL_APPROVED_FALSE"] is True


def test_no_real_import(tmp_path: Path) -> None:
    source = (ROOT / "scripts" / "bc11e_content_deduplication.py").read_text(
        encoding="utf-8"
    )
    for token in ("real_import(", "import_report(", "import_knowledge(", "ingest_report("):
        assert token not in source

    fixtures = _fixtures(tmp_path)
    stage_a = _stage_a(fixtures, tmp_path)
    stage_b = _stage_b(fixtures, tmp_path)
    assert stage_a["plan"]["real_import_executed"] is False
    assert stage_b["results"]["real_import_executed"] is False
    assert stage_b["confirmed_duplicates"]["real_import_executed"] is False


def test_no_production_write(tmp_path: Path) -> None:
    source = (ROOT / "scripts" / "bc11e_content_deduplication.py").read_text(
        encoding="utf-8"
    )
    for token in ("PRODUCTION_STORE_PATH", "sqlite", "production_db", "/var/lib/tradingai"):
        assert token not in source

    fixtures = _fixtures(tmp_path)
    stage_a = _stage_a(fixtures, tmp_path)
    out = tmp_path / "out"
    paths = cd.write_stage_a_outputs(stage_a, output_dir=out, head="test", test_summary="ok")
    written = {Path(item).resolve() for item in paths.values()}
    assert all(item.parent == out.resolve() for item in written)
    assert len(written) == 4

    stage_b = _stage_b(fixtures, tmp_path)
    out_b = tmp_path / "out_b"
    paths_b = cd.write_stage_b_outputs(stage_b, output_dir=out_b)
    written_b = {Path(item).resolve() for item in paths_b.values()}
    assert all(item.parent == out_b.resolve() for item in written_b)
    assert len(written_b) == 4
