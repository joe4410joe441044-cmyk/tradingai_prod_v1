"""BC-11E metadata-only Cursor report inventory tests.

Every fixture is synthetic and lives under a pytest temporary directory. No
test reads a real saved report, opens Cursor private state, touches the
production knowledge store, or performs a real import.
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

import scripts.bc11e_inventory as inv  # noqa: E402
from backend.knowledge_hub.import_readiness import PRODUCTION_STORE_PATH  # noqa: E402


def _write(path: Path, text: str = "synthetic\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def report_root(tmp_path: Path) -> Path:
    root = tmp_path / "approved"
    root.mkdir()
    _write(root / "BC11E_SAMPLE_REPORT.md", "# synthetic report\n")
    _write(root / "BC10C2B_APPROVAL_MANIFEST.txt", "synthetic\n")
    _write(root / "notes.md", "# notes\n")
    _write(root / "README.txt", "hello\n")
    _write(root / "data.json", "{}\n")
    _write(root / "app.py", "x = 1\n")
    _write(root / "db_password.txt", "not-a-real-secret\n")
    _write(root / ".hidden.md", "hidden\n")
    return root


def _run(root: Path, **kwargs) -> dict:
    params = dict(scan_roots=(root,), allowed_roots=(root,))
    params.update(kwargs)
    return inv.run_inventory(**params)


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


def test_metadata_only_fields(report_root: Path) -> None:
    payload = _run(report_root)
    assert payload["mode"] == "METADATA_ONLY"
    assert payload["content_read"] is False
    assert payload["real_import_executed"] is False
    for entry in payload["entries"]:
        assert "source_id" in entry
        assert "absolute_path" in entry
        assert "filename" in entry
        assert "extension" in entry
        assert "size_bytes" in entry
        assert "mtime" in entry
        assert "source_root" in entry
        assert "candidate_reason" in entry
        assert "classification" in entry
        # No body content or body hash is captured.
        assert not any("text" in key or "content" in key or "hash" in key for key in entry)
    sample = _by_name(payload)["BC11E_SAMPLE_REPORT.md"]
    assert sample["size_bytes"] > 0
    assert sample["mtime"].endswith("+00:00")


def test_no_content_read(report_root: Path, monkeypatch) -> None:
    with monkeypatch.context() as patch:
        _forbid_reads(patch)
        payload = _run(report_root)
    assert payload["counts"]["CANDIDATE_COUNT"] > 0
    assert payload["safety"]["body_hash_computed"] is False
    assert payload["safety"]["body_text_stored"] is False


def test_script_has_no_content_read_primitive() -> None:
    source = (ROOT / "scripts" / "bc11e_inventory.py").read_text(encoding="utf-8")
    assert "read_bytes" not in source
    assert "read_text" not in source
    assert "open(" not in source


def test_approved_root_only(tmp_path: Path, report_root: Path) -> None:
    unapproved = tmp_path / "unapproved"
    _write(unapproved / "BC11E_OUTSIDE.md", "outside\n")

    payload = inv.run_inventory(
        scan_roots=(report_root, unapproved),
        allowed_roots=(report_root,),
    )
    assert payload["scanned_roots"] == [str(report_root)]
    assert any(
        item["root"] == str(unapproved) and item["reason"] == "ROOT_NOT_ALLOWLISTED"
        for item in payload["rejected_roots"]
    )
    assert "BC11E_OUTSIDE.md" not in _by_name(payload)


def test_symlink_exclusion(tmp_path: Path, report_root: Path) -> None:
    target = tmp_path / "outside_target.md"
    _write(target, "target\n")
    link = report_root / "BC11E_SYMLINK.md"
    link.symlink_to(target)

    dir_target = tmp_path / "outside_dir"
    _write(dir_target / "BC11E_DIRLINK.md", "dir target\n")
    (report_root / "linked_dir").symlink_to(dir_target, target_is_directory=True)

    payload = _run(report_root)
    entries = _by_name(payload)
    assert entries["BC11E_SYMLINK.md"]["classification"] == inv.CLASS_EXCLUDED
    assert entries["BC11E_SYMLINK.md"]["exclusion_reason"] == "SYMLINK_REJECTED"
    assert "BC11E_DIRLINK.md" not in entries


def test_secret_filename_exclusion(report_root: Path) -> None:
    payload = _run(report_root)
    entry = _by_name(payload)["db_password.txt"]
    assert entry["classification"] == inv.CLASS_EXCLUDED
    assert entry["exclusion_reason"] == "SECRET_FILENAME_REJECTED"


def test_unsupported_extension_exclusion(report_root: Path) -> None:
    payload = _run(report_root)
    entries = _by_name(payload)
    for name in ("data.json", "app.py"):
        assert entries[name]["classification"] == inv.CLASS_EXCLUDED
        assert entries[name]["exclusion_reason"] == "UNSUPPORTED_EXTENSION"


def test_deterministic_source_id(report_root: Path) -> None:
    first = _run(report_root)
    second = _run(report_root)
    first_ids = {e["relative_path"]: e["source_id"] for e in first["entries"]}
    second_ids = {e["relative_path"]: e["source_id"] for e in second["entries"]}
    assert first_ids == second_ids
    assert all(value.startswith("crsrc_") for value in first_ids.values())


def test_classification_safety(report_root: Path) -> None:
    payload = _run(report_root)
    entries = _by_name(payload)

    filename_match = entries["BC11E_SAMPLE_REPORT.md"]
    assert filename_match["classification"] == inv.CLASS_FILENAME_MATCH
    assert filename_match["candidate_reason"] == "FILENAME_MATCH_BC_PREFIX"
    assert filename_match["approved"] is False
    assert filename_match["origin_confirmed"] is False
    assert filename_match["requires_review"] is True

    assert entries["notes.md"]["classification"] == inv.CLASS_REVIEW_REQUIRED
    assert entries["notes.md"]["approved"] is False

    # A BC*.md name is never treated as confirmed or approved.
    for entry in payload["entries"]:
        assert entry["approved"] is False
        assert entry["origin_confirmed"] is False
    assert payload["safety"]["approved_true_count"] == 0
    assert payload["safety"]["origin_confirmed_count"] == 0

    counts = payload["counts"]
    assert counts["FILENAME_MATCH_COUNT"] == 2
    assert counts["REVIEW_REQUIRED_COUNT"] == 2
    assert counts["CANDIDATE_COUNT"] == (
        counts["FILENAME_MATCH_COUNT"] + counts["REVIEW_REQUIRED_COUNT"]
    )
    assert counts["TOTAL_DISCOVERED_COUNT"] == (
        counts["CANDIDATE_COUNT"] + counts["EXCLUDED_COUNT"]
    )


def test_manifest_candidate_not_approved(report_root: Path, tmp_path: Path) -> None:
    payload = _run(report_root)
    out = tmp_path / "out"
    paths = inv.write_outputs(payload, out)

    manifest = json.loads(Path(paths["manifest_candidate"]).read_text(encoding="utf-8"))
    assert manifest["manifest_kind"] == "MANIFEST_CANDIDATE"
    assert manifest["approved"] is False
    assert manifest["import_ready"] is False
    assert manifest["real_import_allowed"] is False
    assert manifest["operator_review_required"] is True
    assert len(manifest["candidates"]) == payload["counts"]["CANDIDATE_COUNT"]
    for candidate in manifest["candidates"]:
        assert candidate["approved"] is False
        assert candidate["origin_confirmed"] is False
        assert candidate["requires_review"] is True

    inventory = json.loads(Path(paths["inventory_json"]).read_text(encoding="utf-8"))
    assert inventory["safety"]["approved_true_count"] == 0
    assert Path(paths["inventory_md"]).exists()


def test_additional_roots_existence_only(tmp_path: Path, report_root: Path) -> None:
    worktree = tmp_path / "worktree"
    _write(worktree / "docs" / "reports" / "BC11E_UNSCANNED.md", "must not be scanned\n")

    payload = _run(
        report_root,
        worktree_root=worktree,
        additional_candidate_roots=("docs/reports", "docs/opencode/reports"),
    )
    statuses = {item["declared"]: item for item in payload["additional_candidate_roots"]}
    assert statuses["docs/reports"]["exists"] is True
    assert statuses["docs/reports"]["scanned"] is False
    assert statuses["docs/opencode/reports"]["exists"] is False
    assert "BC11E_UNSCANNED.md" not in _by_name(payload)
    assert payload["coverage_status"] == inv.COVERAGE_ADDITIONAL
    assert payload["additional_source_roots"]


def test_no_production_write(report_root: Path, tmp_path: Path) -> None:
    before = None
    if PRODUCTION_STORE_PATH.exists():
        stat_result = PRODUCTION_STORE_PATH.stat()
        before = (stat_result.st_size, stat_result.st_mtime_ns)

    payload = _run(report_root)
    inv.write_outputs(payload, tmp_path / "out")

    if before is None:
        assert not PRODUCTION_STORE_PATH.exists()
    else:
        stat_result = PRODUCTION_STORE_PATH.stat()
        assert (stat_result.st_size, stat_result.st_mtime_ns) == before

    source = (ROOT / "scripts" / "bc11e_inventory.py").read_text(encoding="utf-8")
    assert "PRODUCTION_STORE_PATH" not in source
    assert str(PRODUCTION_STORE_PATH) not in source


def test_outputs_are_confined_to_output_dir(report_root: Path, tmp_path: Path) -> None:
    payload = _run(report_root)
    out = tmp_path / "out"
    paths = inv.write_outputs(payload, out)
    written = {Path(item).resolve() for item in paths.values()}
    for item in written:
        assert item.parent == out.resolve()
    assert written == {
        (out / inv.INVENTORY_JSON_NAME).resolve(),
        (out / inv.INVENTORY_MD_NAME).resolve(),
        (out / inv.MANIFEST_NAME).resolve(),
    }
