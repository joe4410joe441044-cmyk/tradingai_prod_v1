"""BC-11E-2 cross-worktree report discovery tests.

Every fixture is synthetic and lives under a pytest temporary directory. No
test reads a real saved report, opens Cursor private state, touches any other
worktree, touches the production knowledge store, or performs a real import.
"""

from __future__ import annotations

import builtins
import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_cross_worktree_inventory as inv  # noqa: E402
from backend.knowledge_hub.import_readiness import PRODUCTION_STORE_PATH  # noqa: E402


def _write(path: Path, text: str = "synthetic\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _worktree(root: Path, name: str = "wt-a", branch: str = "feature/a") -> dict:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return {
        "worktree_path": str(path),
        "branch": branch,
        "head": "a" * 40,
        "detached": False,
        "prunable": False,
        "exists": True,
    }


def _run(root: Path, worktrees, **kwargs) -> dict:
    params = dict(
        worktree_root=root,
        canonical_root=root / "canonical",
        worktrees=worktrees,
    )
    params.update(kwargs)
    return inv.run_cross_worktree_inventory(**params)


def _by_name(payload: dict) -> dict[str, dict]:
    return {entry["filename"]: entry for entry in payload["entries"]}


def _forbid_reads(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("report content was read during metadata-only inventory")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(io, "open", boom)
    monkeypatch.setattr(Path, "open", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    monkeypatch.setattr(Path, "read_bytes", boom)


@pytest.fixture()
def worktree_a(tmp_path: Path) -> dict:
    wt = _worktree(tmp_path, "wt-a", "feature/a")
    base = Path(wt["worktree_path"])
    _write(base / "docs" / "reports" / "BC11E2_SAMPLE.md", "# synthetic\n")
    _write(base / "docs" / "reports" / "CURSOR_NOTES.md", "synthetic\n")
    _write(base / "docs" / "reports" / "chatgpt_review.md", "synthetic\n")
    _write(base / "docs" / "reports" / "codex_notes.txt", "synthetic\n")
    _write(base / "docs" / "reports" / "generic.md", "synthetic\n")
    _write(base / "docs" / "reports" / "data.json", "{}\n")
    _write(base / "docs" / "reports" / "app.py", "x = 1\n")
    _write(base / "docs" / "reports" / "db_password.txt", "not-real\n")
    _write(base / "docs" / "reports" / ".hidden.md", "hidden\n")
    _write(base / "docs" / "opencode" / "reports" / "session.md", "synthetic\n")
    _write(base / "tmp" / "chatgpt_reviews" / "thread.md", "synthetic\n")
    _write(base / "docs" / "other" / "SHOULD_NOT_APPEAR.md", "unapproved\n")
    return wt


def test_metadata_only_fields(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    assert payload["mode"] == "READ_ONLY_CROSS_WORKTREE_METADATA_DISCOVERY"
    assert payload["content_read"] is False
    assert payload["real_import_executed"] is False
    for entry in payload["entries"]:
        for key in (
            "source_id",
            "absolute_path",
            "relative_path",
            "filename",
            "extension",
            "size_bytes",
            "mtime",
            "source_root",
            "worktree_path",
            "branch",
            "head",
            "classification",
            "candidate_reason",
            "duplicate_group",
        ):
            assert key in entry
        assert entry["report_content_read"] is False
        assert not any(
            "text" in key or "content" in key or "hash" in key
            for key in entry
            if key != "report_content_read"
        )
    sample = _by_name(payload)["BC11E2_SAMPLE.md"]
    assert sample["size_bytes"] > 0
    assert sample["mtime"].endswith("+00:00")


def test_no_content_read(worktree_a: dict, tmp_path: Path, monkeypatch) -> None:
    with monkeypatch.context() as patch:
        _forbid_reads(patch)
        payload = _run(tmp_path, [worktree_a])
    assert payload["counts"]["TOTAL_CANDIDATE_COUNT"] > 0
    assert payload["safety"]["body_hash_computed"] is False
    assert payload["safety"]["body_text_stored"] is False
    assert payload["safety"]["content_read_count"] == 0


def test_script_has_no_content_read_primitive() -> None:
    source = (ROOT / "scripts" / "bc11e_cross_worktree_inventory.py").read_text(
        encoding="utf-8"
    )
    assert "read_bytes" not in source
    assert "read_text(" not in source.replace("write_text(", "")
    assert "open(" not in source


def test_approved_root_only(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    names = _by_name(payload)
    assert "SHOULD_NOT_APPEAR.md" not in names
    assert "session.md" in names  # docs/opencode/reports is approved
    assert "thread.md" in names  # tmp/chatgpt_reviews is approved
    assert payload["approved_report_roots"] == list(inv.REPORT_ROOTS)


def test_cross_worktree_isolation(tmp_path: Path) -> None:
    wt_a = _worktree(tmp_path, "wt-a", "feature/a")
    wt_b = _worktree(tmp_path, "wt-b", "feature/b")
    wt_b["head"] = "b" * 40
    _write(Path(wt_a["worktree_path"]) / "docs" / "reports" / "SAME_NAME.md", "one\n")
    _write(Path(wt_b["worktree_path"]) / "docs" / "reports" / "SAME_NAME.md", "two\n")

    payload = _run(tmp_path, [wt_a, wt_b])
    entries = [e for e in payload["entries"] if e["filename"] == "SAME_NAME.md"]
    assert len(entries) == 2
    by_branch = {e["branch"]: e for e in entries}
    assert by_branch["feature/a"]["worktree_path"] == wt_a["worktree_path"]
    assert by_branch["feature/a"]["head"] == "a" * 40
    assert by_branch["feature/b"]["worktree_path"] == wt_b["worktree_path"]
    assert by_branch["feature/b"]["head"] == "b" * 40


def test_symlink_exclusion(tmp_path: Path) -> None:
    wt = _worktree(tmp_path, "wt-a")
    base = Path(wt["worktree_path"])
    target = tmp_path / "outside_target.md"
    _write(target, "target\n")
    (base / "docs" / "reports").mkdir(parents=True, exist_ok=True)
    (base / "docs" / "reports" / "LINKED.md").symlink_to(target)

    dir_target = tmp_path / "outside_dir"
    _write(dir_target / "DIRLINK.md", "dir target\n")
    (base / "docs" / "reports" / "linked_dir").symlink_to(
        dir_target, target_is_directory=True
    )

    payload = _run(tmp_path, [wt])
    entries = _by_name(payload)
    assert entries["LINKED.md"]["classification"] == inv.CLASS_EXCLUDED
    assert entries["LINKED.md"]["exclusion_reason"] == "SYMLINK_REJECTED"
    assert "DIRLINK.md" not in entries


def test_secret_filename_exclusion(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    entry = _by_name(payload)["db_password.txt"]
    assert entry["classification"] == inv.CLASS_EXCLUDED
    assert entry["exclusion_reason"] == "SECRET_FILENAME_REJECTED"


def test_unsupported_extension_exclusion(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    entry = _by_name(payload)["app.py"]
    assert entry["classification"] == inv.CLASS_EXCLUDED
    assert entry["exclusion_reason"] == "UNSUPPORTED_EXTENSION"


def test_hidden_file_exclusion(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    entry = _by_name(payload)[".hidden.md"]
    assert entry["classification"] == inv.CLASS_EXCLUDED
    assert entry["exclusion_reason"] == "HIDDEN_PATH_REJECTED"


def test_depth_limit(tmp_path: Path) -> None:
    wt = _worktree(tmp_path, "wt-a")
    base = Path(wt["worktree_path"]) / "docs" / "reports"
    _write(base / "a" / "b" / "c" / "DEPTH3.md", "ok\n")
    _write(base / "a" / "b" / "c" / "d" / "DEPTH4.md", "too deep\n")

    payload = _run(tmp_path, [wt], max_depth=3)
    names = _by_name(payload)
    assert "DEPTH3.md" in names
    assert "DEPTH4.md" not in names


def test_scan_limit(tmp_path: Path) -> None:
    wt = _worktree(tmp_path, "wt-a")
    base = Path(wt["worktree_path"]) / "docs" / "reports"
    for index in range(5):
        _write(base / f"REPORT_{index}.md", "x\n")

    payload = _run(tmp_path, [wt], max_files_per_root=2)
    assert payload["counts"]["SCAN_LIMIT_REACHED_COUNT"] == 1
    assert payload["coverage_status"] == inv.COVERAGE_SCAN_LIMIT
    assert payload["counts"]["TOTAL_SCANNED_FILES"] == 2


def test_deterministic_source_id(worktree_a: dict, tmp_path: Path) -> None:
    first = _run(tmp_path, [worktree_a])
    second = _run(tmp_path, [worktree_a])
    first_ids = {e["absolute_path"]: e["source_id"] for e in first["entries"]}
    second_ids = {e["absolute_path"]: e["source_id"] for e in second["entries"]}
    assert first_ids == second_ids
    assert all(value.startswith("xwsrc_") for value in first_ids.values())


def test_duplicate_candidate_classification() -> None:
    def entry(name: str, size: int, path: str) -> dict:
        return {
            "source_id": f"id-{path}",
            "absolute_path": path,
            "filename": name,
            "size_bytes": size,
            "worktree_path": "/wt",
            "branch": "b",
            "head": "h",
            "classification": inv.CLASS_UNKNOWN,
            "duplicate_group": None,
            "duplicate_kind": None,
        }

    entries = [
        entry("same.md", 10, "/wt/a/same.md"),
        entry("same.md", 10, "/wt/b/same.md"),
        entry("same.md", 10, "/wt/a/same.md"),
        entry("name_only.md", 1, "/wt/a/name_only.md"),
        entry("name_only.md", 2, "/wt/b/name_only.md"),
    ]
    groups = inv._build_duplicate_groups(entries)
    kinds = {group["duplicate_kind"] for group in groups}
    assert inv.DUP_EXACT_PATH in kinds
    assert inv.DUP_POSSIBLE in kinds
    assert inv.DUP_NAME_COLLISION in kinds

    exact = next(g for g in groups if g["duplicate_kind"] == inv.DUP_EXACT_PATH)
    assert exact["member_count"] == 2
    assert entries[0]["duplicate_kind"] == inv.DUP_EXACT_PATH
    assert entries[1]["duplicate_kind"] == inv.DUP_POSSIBLE
    assert entries[3]["duplicate_kind"] == inv.DUP_NAME_COLLISION


def test_unknown_source_classification(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    entries = _by_name(payload)
    assert entries["generic.md"]["classification"] == inv.CLASS_UNKNOWN
    assert entries["generic.md"]["candidate_reason"] == "ORIGIN_UNCONFIRMED"
    assert entries["BC11E2_SAMPLE.md"]["classification"] == inv.CLASS_UNKNOWN

    # A filename hint creates a candidate, never a confirmed origin.
    assert entries["CURSOR_NOTES.md"]["classification"] == inv.CLASS_CURSOR
    assert entries["chatgpt_review.md"]["classification"] == inv.CLASS_CHATGPT
    assert entries["codex_notes.txt"]["classification"] == inv.CLASS_OTHER_AGENT
    for candidate in payload["candidates"]:
        assert candidate["approved"] is False
        assert candidate["origin_confirmed"] is False
        assert candidate["requires_review"] is True

    assert payload["safety"]["approved_true_count"] == 0
    assert payload["safety"]["origin_confirmed_count"] == 0


def test_json_is_review_required_unknown(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    entry = _by_name(payload)["data.json"]
    assert entry["classification"] == inv.CLASS_UNKNOWN
    assert entry["candidate_reason"] == "JSON_CONTENT_NOT_READ_REVIEW_REQUIRED"
    assert entry["requires_review"] is True


def test_parse_worktree_porcelain_excludes_canonical_and_nondirect(tmp_path: Path) -> None:
    worktree_root = tmp_path / "worktrees"
    canonical = tmp_path / "canonical"
    direct = worktree_root / "wt-a"
    porcelains = "\n\n".join(
        [
            f"worktree {canonical}\nHEAD {'a' * 40}\nbranch refs/heads/main",
            f"worktree {direct}\nHEAD {'b' * 40}\nbranch refs/heads/feature/a",
            f"worktree {worktree_root / 'nested' / 'wt-b'}\nHEAD {'c' * 40}\nbranch refs/heads/feature/b",
            f"worktree {tmp_path / 'elsewhere'}\nHEAD {'d' * 40}\ndetached",
        ]
    )
    records = inv.parse_worktree_porcelain(porcelains, worktree_root, canonical)
    assert [Path(r["worktree_path"]) for r in records] == [direct]
    assert records[0]["branch"] == "feature/a"
    assert records[0]["head"] == "b" * 40


def test_no_production_write(worktree_a: dict, tmp_path: Path) -> None:
    before = None
    if PRODUCTION_STORE_PATH.exists():
        stat_result = PRODUCTION_STORE_PATH.stat()
        before = (stat_result.st_size, stat_result.st_mtime_ns)

    payload = _run(tmp_path, [worktree_a])
    inv.write_outputs(payload, tmp_path / "out")

    if before is None:
        assert not PRODUCTION_STORE_PATH.exists()
    else:
        stat_result = PRODUCTION_STORE_PATH.stat()
        assert (stat_result.st_size, stat_result.st_mtime_ns) == before

    source = (ROOT / "scripts" / "bc11e_cross_worktree_inventory.py").read_text(
        encoding="utf-8"
    )
    assert "PRODUCTION_STORE_PATH" not in source
    assert str(PRODUCTION_STORE_PATH) not in source


def test_outputs_confined_and_named(worktree_a: dict, tmp_path: Path) -> None:
    payload = _run(tmp_path, [worktree_a])
    out = tmp_path / "out"
    paths = inv.write_outputs(payload, out)
    written = {Path(item).resolve() for item in paths.values()}
    for item in written:
        assert item.parent == out.resolve()
    assert written == {
        (out / inv.INVENTORY_JSON_NAME).resolve(),
        (out / inv.INVENTORY_MD_NAME).resolve(),
        (out / inv.ROOTS_JSON_NAME).resolve(),
        (out / inv.DUPLICATES_JSON_NAME).resolve(),
    }

    roots = json.loads(Path(paths["worktree_report_roots"]).read_text(encoding="utf-8"))
    assert roots["schema_version"] == inv.ROOTS_SCHEMA_VERSION
    assert roots["content_read"] is False

    duplicates = json.loads(
        Path(paths["duplicate_candidates"]).read_text(encoding="utf-8")
    )
    assert duplicates["schema_version"] == inv.DUPLICATES_SCHEMA_VERSION
    assert duplicates["content_read"] is False
    assert duplicates["hash_computed"] is False
