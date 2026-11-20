"""BC-11D approval-gated Cursor saved report import acceptance tests.

Every report is synthetic and lives under a temporary directory. Every store is
a temporary SQLite file. No test reads a real saved report, opens Cursor private
state, touches the production knowledge store, starts the backend, or calls a
network or an LLM.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from backend.knowledge_hub import cursor_report_import as cursor_import
from backend.knowledge_hub.continuous_sync import ContinuousSyncEngine, SyncLimits
from backend.knowledge_hub.cursor_report_import import (
    ACCEPTANCE_NOT_RUN,
    ACCEPTANCE_PASS,
    ACCEPTANCE_PREVIEW_ONLY,
    CURSOR_APPROVAL_SCHEMA_VERSION,
    CURSOR_IMPORT_SCHEMA_VERSION,
    CURSOR_SOURCE_TYPE,
    ApprovedSource,
    CursorApproval,
    CursorImportError,
    DATA_ORIGIN_REAL,
    DATA_ORIGIN_SYNTHETIC,
    STATUS_APPROVAL_PENDING,
    STATUS_APPROVED,
    STATUS_IMPORT_COMPLETE,
    STATUS_IMPORT_FAILED,
    STATUS_NOT_PROVIDED,
    build_synthetic_cursor_reports,
    parse_approval,
    parse_manifest,
    run_cursor_report_import,
)
from backend.knowledge_hub.import_readiness import (
    PRODUCTION_STORE_PATH,
    SearchProbe,
    assert_temporary_store,
)
from backend.knowledge_hub.knowledge_store import StoreError
from backend.knowledge_hub.reader import ReaderFilters, ReaderLimits, RequestContext, open_reader


INDEXED = "2026-11-07T00:00:00+00:00"
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "bc11d_cursor_report_import.py"
OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc11d-test")
RETENTION = "RETAIN_UNTIL_OPERATOR_DELETE"
REDACTION = "SECRET_PATTERNS_V1"


def _reports(tmp_path: Path) -> dict[str, Path]:
    return build_synthetic_cursor_reports(tmp_path / "reports")


def _sources(reports: dict[str, Path]) -> list[dict[str, object]]:
    return [
        {
            "sourceId": f"cursor_report_{index:03d}",
            "path": str(path),
            "sourceType": CURSOR_SOURCE_TYPE,
            "approved": True,
        }
        for index, path in enumerate(reports.values(), start=1)
    ]


def _write_manifest(tmp_path: Path, sources, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps({"schemaVersion": CURSOR_IMPORT_SCHEMA_VERSION, "sources": sources}),
        encoding="utf-8",
    )
    return path


def _approval_payload(manifest_path, store: Path, sources, **overrides) -> dict:
    payload = {
        "schema_version": CURSOR_APPROVAL_SCHEMA_VERSION,
        "manifest_path": str(manifest_path),
        "store_path": str(store),
        "retention_policy": RETENTION,
        "log_redaction_policy": REDACTION,
        "approved_at": INDEXED,
        "approved_by": "OPERATOR",
        "sources": [
            {"source_id": source["sourceId"], "path": source["path"]} for source in sources
        ],
    }
    payload.update(overrides)
    return payload


def _write_approval(tmp_path: Path, manifest_path, store: Path, sources, name="approval.json", **overrides) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(_approval_payload(manifest_path, store, sources, **overrides)), encoding="utf-8")
    return path


def _run(tmp_path: Path, manifest, approval=None, *, apply=False, store=None, probes=(), limits=None):
    return run_cursor_report_import(
        store or (tmp_path / "store.sqlite3"),
        manifest=manifest,
        approval=approval,
        indexed_at=INDEXED,
        apply=apply,
        data_origin=DATA_ORIGIN_SYNTHETIC,
        search_probes=probes,
        limits=limits,
    )


def _rows(store: Path) -> list[dict]:
    connection = sqlite3.connect(store)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM records ORDER BY record_id")]
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_no_manifest_is_not_provided_and_reads_nothing(tmp_path):
    store = tmp_path / "store.sqlite3"
    result = run_cursor_report_import(store, manifest=None, indexed_at=INDEXED, apply=True)
    payload = result.to_dict()
    assert result.status == STATUS_NOT_PROVIDED
    assert payload["REAL_REPORT_IMPORT_EXECUTED"] == "NO"
    assert payload["REAL_REPORT_ACCEPTANCE"] == ACCEPTANCE_NOT_RUN
    assert store.exists() is False


def test_manifest_without_approval_is_pending_and_reads_nothing(tmp_path):
    sources = [
        {
            "sourceId": "cursor_report_001",
            "path": str(tmp_path / "does_not_exist.md"),
            "sourceType": CURSOR_SOURCE_TYPE,
            "approved": True,
        }
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    result = _run(tmp_path, manifest, apply=True, store=store)
    assert result.status == STATUS_APPROVAL_PENDING
    assert result.errors == ("APPROVAL_REQUIRED",)
    assert result.real_report_import_executed is False
    assert result.real_report_acceptance == ACCEPTANCE_NOT_RUN
    assert store.exists() is False


def test_synthetic_import_complete_and_historical_authority(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)

    assert result.status == STATUS_IMPORT_COMPLETE
    assert result.integrity == "OK"
    assert result.fts_available is True
    assert result.real_report_import_executed is False
    assert result.real_report_acceptance == ACCEPTANCE_NOT_RUN
    assert result.to_dict()["REAL_REPORT_IMPORT_EXECUTED"] == "NO"
    assert result.to_dict()["REAL_REPORT_ACCEPTANCE"] == ACCEPTANCE_NOT_RUN
    assert result.store_snapshot["total"] == 3
    assert result.store_snapshot["by_source_type"] == {"CURSOR_SAVED_REPORT": 3}
    assert result.store_snapshot["by_truth_kind"] == {"AGENT_REPORTED": 3}
    assert result.store_snapshot["by_authority"] == {"NONE": 3}
    assert all(source.status == "IMPORTED" for source in result.sources)

    rows = _rows(store)
    assert len(rows) == 3
    for row in rows:
        assert row["truth_kind"] == "AGENT_REPORTED"
        assert row["authority_scope"] == "NONE"
        metadata = json.loads(row["metadata_json"])
        assert metadata["truth_class"] == "AGENT_REPORTED_HISTORY"
        assert metadata["runtime_truth"] == "NOT_ASSERTED"
        assert metadata["historical_authority"] == "UNTRUSTED_HISTORICAL"
        assert metadata["access_scope"] == "OPERATOR"
        assert metadata["source_agent"] == "CURSOR_SAVED"


def test_preview_does_not_create_store(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=False, store=store)

    assert result.status == STATUS_APPROVED
    assert result.import_executed is False
    assert result.real_report_acceptance == ACCEPTANCE_NOT_RUN
    assert store.exists() is False
    assert {source.state for source in result.sources} == {"NEW"}


def test_duplicate_source_id_is_rejected():
    payload = {
        "schemaVersion": CURSOR_IMPORT_SCHEMA_VERSION,
        "sources": [
            {
                "sourceId": "same",
                "path": "/tmp/a.md",
                "sourceType": CURSOR_SOURCE_TYPE,
                "approved": True,
            },
            {
                "sourceId": "same",
                "path": "/tmp/b.md",
                "sourceType": CURSOR_SOURCE_TYPE,
                "approved": True,
            },
        ],
    }
    with pytest.raises(CursorImportError) as rejected:
        parse_manifest(payload)
    assert rejected.value.code == "DUPLICATE_SOURCE_ID"


def test_duplicate_source_path_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    first = reports["report_a"]
    sources = [
        {"sourceId": "cursor_001", "path": str(first), "sourceType": CURSOR_SOURCE_TYPE, "approved": True},
        {"sourceId": "cursor_002", "path": str(first), "sourceType": CURSOR_SOURCE_TYPE, "approved": True},
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = CursorApproval(
        schema_version=CURSOR_APPROVAL_SCHEMA_VERSION,
        manifest_path=manifest.resolve(),
        store_path=str(store),
        retention_policy=RETENTION,
        log_redaction_policy=REDACTION,
        approved_at=INDEXED,
        approved_by="OPERATOR",
        sources=(
            ApprovedSource("cursor_001", first),
            ApprovedSource("cursor_002", first),
        ),
    )
    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert "DUPLICATE_SOURCE_PATH" in result.errors
    assert store.exists() is False


def test_unapproved_file_requires_exact_source_set(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources[:2])

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("APPROVAL_SOURCE_SET_MISMATCH",)
    assert store.exists() is False


def test_unapproved_destination_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, tmp_path / "other.sqlite3", sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("APPROVAL_STORE_MISMATCH",)
    assert store.exists() is False


def test_manifest_path_mismatch_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    other = _write_manifest(tmp_path, sources, name="other_manifest.json")
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, other, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("APPROVAL_MANIFEST_MISMATCH",)
    assert store.exists() is False


def test_approval_path_mismatch_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    swapped = [dict(source) for source in sources]
    extra = tmp_path / "extra_report.md"
    extra.write_text("TASK_ID: EXTRA\n", encoding="utf-8")
    swapped[0]["path"] = str(extra)
    approval = _write_approval(tmp_path, manifest, store, swapped)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("APPROVAL_PATH_MISMATCH",)
    assert store.exists() is False


def test_approval_policy_missing_is_rejected(tmp_path):
    with pytest.raises(CursorImportError) as rejected:
        parse_approval(
            {
                "schema_version": CURSOR_APPROVAL_SCHEMA_VERSION,
                "manifest_path": "/tmp/manifest.json",
                "store_path": "/tmp/store.sqlite3",
                "retention_policy": "",
                "log_redaction_policy": REDACTION,
                "approved_at": INDEXED,
                "approved_by": "OPERATOR",
                "sources": [{"source_id": "a", "path": "/tmp/a.md"}],
            }
        )
    assert rejected.value.code == "APPROVAL_RETENTION_POLICY_REQUIRED"


def test_manifest_source_type_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    sources[0]["sourceType"] = "CHATGPT_EXPORT"
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("SOURCE_TYPE_REJECTED",)


def test_symlink_source_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    link = tmp_path / "linked_report.md"
    link.symlink_to(reports["report_a"])
    sources = [
        {"sourceId": "cursor_link", "path": str(link), "sourceType": CURSOR_SOURCE_TYPE, "approved": True}
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("cursor_link:SYMLINK_REJECTED",)
    assert store.exists() is False


def test_production_store_destination_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    approval = _write_approval(tmp_path, manifest, PRODUCTION_STORE_PATH, sources)
    before = _sha256(PRODUCTION_STORE_PATH) if PRODUCTION_STORE_PATH.exists() else None

    result = _run(tmp_path, manifest, approval, apply=True, store=PRODUCTION_STORE_PATH)

    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("PRODUCTION_STORE_REJECTED",)
    after = _sha256(PRODUCTION_STORE_PATH) if PRODUCTION_STORE_PATH.exists() else None
    assert before == after


def test_symlinked_store_is_rejected(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    store.symlink_to(tmp_path / "real.sqlite3")
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("STORE_SYMLINK_REJECTED",)


def test_unsupported_file_type_is_rejected(tmp_path):
    report = tmp_path / "report.py"
    report.write_text("TASK_ID: TEST\n", encoding="utf-8")
    sources = [
        {"sourceId": "cursor_py", "path": str(report), "sourceType": CURSOR_SOURCE_TYPE, "approved": True}
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("cursor_py:UNSUPPORTED_FILE_TYPE",)


def test_oversized_file_is_rejected(tmp_path):
    report = tmp_path / "big.md"
    report.write_text("TASK_ID: TEST\n" + ("x" * 200), encoding="utf-8")
    sources = [
        {"sourceId": "cursor_big", "path": str(report), "sourceType": CURSOR_SOURCE_TYPE, "approved": True}
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(
        tmp_path,
        manifest,
        approval,
        apply=True,
        store=store,
        limits=SyncLimits(max_report_file_bytes=50),
    )
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("cursor_big:FILE_TOO_LARGE",)
    assert store.exists() is False


def test_invalid_encoding_is_rejected(tmp_path):
    report = tmp_path / "bad_encoding.md"
    report.write_bytes(b"\xff\xfe\x00TASK_ID: TEST\n")
    sources = [
        {"sourceId": "cursor_bad", "path": str(report), "sourceType": CURSOR_SOURCE_TYPE, "approved": True}
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("cursor_bad:INVALID_ENCODING",)
    assert store.exists() is False


def test_secret_filename_is_rejected(tmp_path):
    report = tmp_path / "secret.md"
    report.write_text("TASK_ID: TEST\n", encoding="utf-8")
    sources = [
        {"sourceId": "cursor_secret", "path": str(report), "sourceType": CURSOR_SOURCE_TYPE, "approved": True}
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("cursor_secret:SECRET_EXCLUDED",)


def test_secret_like_content_is_rejected(tmp_path):
    report = tmp_path / "leak.md"
    report.write_text("TASK_ID: TEST\napi_key=sk-synthetic000000000000\n", encoding="utf-8")
    sources = [
        {"sourceId": "cursor_leak", "path": str(report), "sourceType": CURSOR_SOURCE_TYPE, "approved": True}
    ]
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    result = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert result.status == STATUS_IMPORT_FAILED
    assert result.errors == ("cursor_leak:SECRET_EXCLUDED",)
    assert store.exists() is False


def test_idempotent_reimport_suppresses_duplicates(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    first = _run(tmp_path, manifest, approval, apply=True, store=store)
    second = _run(tmp_path, manifest, approval, apply=True, store=store)

    assert first.sync_report["inserted"] == 3
    assert second.sync_report["inserted"] == 0
    assert second.sync_report["skipped"] == 3
    assert second.store_snapshot["total"] == 3
    assert {source.status for source in second.sources} == {"SKIPPED"}


def test_updated_report_supersedes_and_search_tags_history(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)
    _run(tmp_path, manifest, approval, apply=True, store=store)

    reports["report_a"].write_text(
        "TASK_ID: TEST-CURSOR-A\nVERDICT: PASS\ncursoralphamarker updated version two\n",
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        manifest,
        approval,
        apply=True,
        store=store,
        probes=(SearchProbe("marker", "cursoralphamarker"),),
    )

    assert result.status == STATUS_IMPORT_COMPLETE
    assert result.sync_report["inserted"] == 1
    assert result.sync_report["superseded"] == 1
    assert result.store_snapshot["total"] == 4
    assert result.store_snapshot["by_presence"] == {"CURRENT": 3, "HISTORICAL": 1}
    search = result.search[0]
    assert search["total_count"] == 2
    assert set(search["presences"]) == {"CURRENT", "HISTORICAL"}
    assert search["truth_kinds"] == ["AGENT_REPORTED"]
    assert search["authority_scopes"] == ["NONE"]


def test_new_report_is_added_incrementally(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources[:2])
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources[:2])
    _run(tmp_path, manifest, approval, apply=True, store=store)

    manifest = _write_manifest(tmp_path, sources, name="manifest_all.json")
    approval = _write_approval(tmp_path, manifest, store, sources, name="approval_all.json")
    result = _run(tmp_path, manifest, approval, apply=True, store=store)

    assert result.status == STATUS_IMPORT_COMPLETE
    assert result.sync_report["inserted"] == 1
    assert result.sync_report["skipped"] == 2
    assert result.store_snapshot["total"] == 3


def test_removed_source_is_not_deleted(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)
    _run(tmp_path, manifest, approval, apply=True, store=store)

    manifest = _write_manifest(tmp_path, sources[:2], name="manifest_two.json")
    approval = _write_approval(tmp_path, manifest, store, sources[:2], name="approval_two.json")
    result = _run(tmp_path, manifest, approval, apply=True, store=store)

    assert result.status == STATUS_IMPORT_COMPLETE
    assert result.removed_sources == ("cursor_report_003",)
    assert result.store_snapshot["total"] == 3
    task_ids = {
        json.loads(row["metadata_json"])["task_id"] for row in _rows(store)
    }
    assert "TEST-CURSOR-C" in task_ids


def test_fts_search_filters_and_read_only(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)
    probes = (
        SearchProbe("keyword", "cursoralphamarker", ReaderFilters(source_type="CURSOR_SAVED_REPORT")),
        SearchProbe("task", "TEST-CURSOR-A"),
        SearchProbe("verdict", "PASS"),
        SearchProbe("none", "zzzznomatch"),
    )
    result = _run(tmp_path, manifest, approval, apply=True, store=store, probes=probes)

    by_name = {item["name"]: item for item in result.search}
    assert by_name["keyword"]["status"] == "OK"
    assert by_name["keyword"]["source_types"] == ["CURSOR_SAVED_REPORT"]
    assert by_name["task"]["total_count"] >= 1
    assert by_name["verdict"]["total_count"] >= 1
    assert by_name["none"]["status"] == "EMPTY"
    assert by_name["none"]["total_count"] == 0
    for name in ("keyword", "task", "verdict"):
        assert by_name[name]["truth_kinds"] == ["AGENT_REPORTED"]
        assert by_name[name]["authority_scopes"] == ["NONE"]

    before = _sha256(store)
    reader, failure = open_reader(store, ReaderLimits(max_results=20))
    assert failure is None
    try:
        response = reader.search(
            "cursoralphamarker",
            request=OPERATOR,
            filters=ReaderFilters(source_type="CURSOR_SAVED_REPORT", authority_scope="NONE"),
        )
    finally:
        reader.close()
    assert response.status == "OK"
    assert all(hit.truth_kind == "AGENT_REPORTED" for hit in response.results)
    assert all(hit.authority_scope == "NONE" for hit in response.results)
    assert _sha256(store) == before


def test_retry_after_validation_failure(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    reports["report_b"].write_text("TASK_ID: TEST-CURSOR-B\n" + ("x" * 200), encoding="utf-8")
    blocked = _run(
        tmp_path,
        manifest,
        approval,
        apply=True,
        store=store,
        limits=SyncLimits(max_report_file_bytes=50),
    )
    assert blocked.status == STATUS_IMPORT_FAILED
    assert store.exists() is False

    reports["report_b"].write_text(
        "TASK_ID: TEST-CURSOR-B\nVERDICT: BLOCKED\ncursorbetamarker retry\n",
        encoding="utf-8",
    )
    retried = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert retried.status == STATUS_IMPORT_COMPLETE
    assert retried.sync_report["inserted"] == 3


def test_retry_after_transient_store_error(tmp_path, monkeypatch):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)

    original = ContinuousSyncEngine.sync
    calls = {"count": 0}

    def flaky(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise StoreError("DATABASE_BUSY")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContinuousSyncEngine, "sync", flaky)
    blocked = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert blocked.status == STATUS_IMPORT_FAILED
    assert blocked.errors == ("DATABASE_BUSY",)

    retried = _run(tmp_path, manifest, approval, apply=True, store=store)
    assert retried.status == STATUS_IMPORT_COMPLETE
    assert retried.store_snapshot["total"] == 3


def test_real_origin_flags_pass_without_real_reports(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)
    result = run_cursor_report_import(
        store,
        manifest=manifest,
        approval=approval,
        indexed_at=INDEXED,
        apply=True,
        data_origin=DATA_ORIGIN_REAL,
    )
    assert result.status == STATUS_IMPORT_COMPLETE
    assert result.real_report_import_executed is True
    assert result.real_report_acceptance == ACCEPTANCE_PASS


def test_isolated_store_guard_rejects_root_and_outside(tmp_path):
    with pytest.raises(Exception) as rejected:
        assert_temporary_store("/tmp")
    assert getattr(rejected.value, "code", None) == "STORE_OUTSIDE_ALLOWED_ROOT"

    with pytest.raises(Exception) as rejected:
        assert_temporary_store(PRODUCTION_STORE_PATH)
    assert getattr(rejected.value, "code", None) == "PRODUCTION_STORE_REJECTED"


def test_module_has_no_network_or_subprocess_imports():
    tree = ast.parse((ROOT / "backend" / "knowledge_hub" / "cursor_report_import.py").read_text(encoding="utf-8"))
    forbidden = {"socket", "requests", "httpx", "aiohttp", "subprocess", "openai"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden)
    assert "urllib.request" not in {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }


def test_cli_without_manifest_is_not_provided():
    result = subprocess.run(
        [sys.executable, str(CLI)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == STATUS_NOT_PROVIDED
    assert payload["REAL_REPORT_IMPORT_EXECUTED"] == "NO"
    assert payload["REAL_REPORT_ACCEPTANCE"] == ACCEPTANCE_NOT_RUN


def test_cli_synthetic_preview_then_apply(tmp_path):
    reports = _reports(tmp_path)
    sources = _sources(reports)
    manifest = _write_manifest(tmp_path, sources)
    store = tmp_path / "store.sqlite3"
    approval = _write_approval(tmp_path, manifest, store, sources)
    common = [
        "--manifest",
        str(manifest),
        "--store",
        str(store),
        "--indexed-at",
        INDEXED,
    ]

    preview = subprocess.run(
        [sys.executable, str(CLI), *common, "--approval", str(approval)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["status"] == STATUS_APPROVED
    assert preview_payload["REAL_REPORT_IMPORT_EXECUTED"] == "NO"
    assert store.exists() is False

    applied = subprocess.run(
        [sys.executable, str(CLI), *common, "--approval", str(approval), "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["status"] == STATUS_IMPORT_COMPLETE
    assert applied_payload["store_snapshot"]["total"] == 3
    assert applied_payload["REAL_REPORT_IMPORT_EXECUTED"] == "NO"
