"""BC-11A offline import readiness acceptance tests.

All sources are synthetic. Every database is a temporary SQLite file. The
production knowledge store, the production backend, real ChatGPT exports,
Cursor private state, and real LLMs are never used.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import time
import tracemalloc
import zipfile

import pytest

from backend.knowledge_hub import import_readiness as readiness
from backend.knowledge_hub.advisor_supervisor_connection import (
    ADVISOR_ENABLED_ENV,
    SUPERVISOR_ENABLED_ENV,
    advisor_knowledge_block,
    advisor_knowledge_enabled,
    attach_advisor_knowledge,
    attach_supervisor_knowledge,
    supervisor_knowledge_block,
    supervisor_knowledge_enabled,
)
from backend.knowledge_hub.chatgpt_import import (
    ImportLimits,
    import_export,
    preview_export,
    resolve_account,
)
from backend.knowledge_hub.chatgpt_import.adapter import commit_items
from backend.knowledge_hub.config import CollectorConfig
from backend.knowledge_hub.continuous_sync import ContinuousSyncEngine
from backend.knowledge_hub.import_readiness import (
    PRODUCTION_STORE_PATH,
    ReadinessError,
    SearchProbe,
    assert_temporary_store,
    build_synthetic_corpus,
    build_synthetic_stress_export,
    run_import_readiness,
)
from backend.knowledge_hub.knowledge_access import (
    executed_commands,
    query_advisor_knowledge,
    query_supervisor_knowledge,
)
from backend.knowledge_hub.knowledge_ingest import ingest_collection
from backend.knowledge_hub.knowledge_store import (
    KnowledgeStore,
    StoreError,
    StoreItem,
    StoreLimits,
)
from backend.knowledge_hub.reader import ReaderFilters, RequestContext, open_reader
from backend.knowledge_hub.report_collector import collect_reports


INDEXED = "2026-11-04T00:00:00+00:00"
INDEXED2 = "2026-11-04T01:00:00+00:00"
OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc11a-test")
PUBLIC = RequestContext(caller_scope="PUBLIC", caller_id="bc11a-public")


def _corpus(tmp_path: Path):
    return build_synthetic_corpus(tmp_path / "corpus")


def _run(
    tmp_path: Path,
    corpus,
    *,
    probes=(),
    exports=None,
    store=None,
    indexed_at=INDEXED,
    with_reports=True,
):
    chosen_exports = exports if exports is not None else {
        "chatgpt_account_a": corpus.export_a,
        "chatgpt_account_b": corpus.export_b,
    }
    return run_import_readiness(
        store or (tmp_path / "store.sqlite3"),
        chatgpt_exports=chosen_exports,
        report_directories=(corpus.report_dir,) if with_reports else (),
        report_roots=(corpus.report_dir,),
        indexed_at=indexed_at,
        search_probes=probes,
    )


def _rows(path: Path) -> tuple[dict, ...]:
    store = KnowledgeStore.open(path, StoreLimits(max_results=500))
    try:
        return store.list_records(limit=500)
    finally:
        store.close()


def _chatgpt_rows(path: Path) -> tuple[dict, ...]:
    return tuple(row for row in _rows(path) if row["source_type"] == "CHATGPT_EXPORT")


def _report_rows(path: Path) -> tuple[dict, ...]:
    return tuple(row for row in _rows(path) if row["source_type"] == "CURSOR_REPORT")


def _message(mid: str, role: str, text: str, created: int = 1700000000) -> dict:
    return {
        "id": mid,
        "author": {"role": role},
        "create_time": created,
        "content": {"content_type": "text", "parts": [text]},
    }


def _node(mid: str, parent, children, message) -> dict:
    return {"id": mid, "parent": parent, "children": children, "message": message}


def _conversation(cid: str, messages: list[tuple[str, str, str]], title="TradingAI test") -> dict:
    nodes = []
    parent = None
    for index, (mid, role, text) in enumerate(messages):
        next_id = messages[index + 1][0] if index + 1 < len(messages) else None
        nodes.append(_node(mid, parent, [next_id] if next_id else [], _message(mid, role, text)))
        parent = mid
    return {
        "id": cid,
        "title": title,
        "create_time": 1700000000,
        "update_time": 1700000100,
        "mapping": {node["id"]: node for node in nodes},
    }


def _zip(path: Path, document) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("conversations.json", json.dumps(document))
    return path


def _plain_item(*, source_identifier: str, truth_kind: str = "HISTORICAL_CONTEXT") -> StoreItem:
    return StoreItem(
        source_type="CHATGPT_EXPORT",
        source_identifier=source_identifier,
        record_type="CHATGPT_MESSAGE",
        title="synthetic",
        content="synthetic TradingAI content",
        collected_at=INDEXED,
        verification_state="COLLECTED",
        truth_kind=truth_kind,
        metadata={"access_scope": "OPERATOR"},
    )


# A01 / A10 / A20 ------------------------------------------------------------


def test_guard_rejects_production_symlink_outside_root_and_report_escape(tmp_path):
    with pytest.raises(ReadinessError) as production:
        assert_temporary_store(PRODUCTION_STORE_PATH)
    assert production.value.code == "PRODUCTION_STORE_REJECTED"

    link = tmp_path / "link.sqlite3"
    link.symlink_to(tmp_path / "real.sqlite3")
    with pytest.raises(ReadinessError) as symlinked:
        assert_temporary_store(link, allowed_root=tmp_path)
    assert symlinked.value.code == "STORE_SYMLINK_REJECTED"

    outside = Path("/home/joe4410joe/bc11a-outside.sqlite3")
    with pytest.raises(ReadinessError) as escaped:
        assert_temporary_store(outside, allowed_root=tmp_path)
    assert escaped.value.code == "STORE_OUTSIDE_ALLOWED_ROOT"

    corpus = build_synthetic_corpus(tmp_path / "corpus")
    with pytest.raises(ReadinessError) as not_allowed:
        run_import_readiness(
            tmp_path / "store.sqlite3",
            chatgpt_exports={"chatgpt_account_a": corpus.export_a},
            report_directories=(corpus.report_dir,),
            report_roots=(tmp_path / "other",),
            indexed_at=INDEXED,
        )
    assert not_allowed.value.code == "REPORT_ROOT_NOT_ALLOWLISTED"
    assert (tmp_path / "store.sqlite3").exists() is False

    with pytest.raises(ReadinessError) as tmp_root:
        run_import_readiness(
            tmp_path / "store.sqlite3",
            chatgpt_exports={"chatgpt_account_a": corpus.export_a},
            report_directories=(Path("/tmp"),),
            report_roots=(Path("/tmp"),),
            indexed_at=INDEXED,
        )
    assert tmp_root.value.code == "REPORT_ROOT_REJECTED"

    production_report = readiness.PRODUCTION_RUNTIME_ROOT / "knowledge_hub"
    with pytest.raises(ReadinessError) as production_root:
        run_import_readiness(
            tmp_path / "store.sqlite3",
            chatgpt_exports={"chatgpt_account_a": corpus.export_a},
            report_directories=(production_report,),
            report_roots=(production_report,),
            indexed_at=INDEXED,
        )
    assert production_root.value.code == "PRODUCTION_RUNTIME_ROOT_REJECTED"


def test_synthetic_e2e_temp_store_and_integrity(tmp_path):
    corpus = _corpus(tmp_path)
    result = _run(tmp_path, corpus)
    payload = result.to_dict()
    assert result.schema_version == "tradingai-knowledge-import-readiness/v1"
    assert result.store_path == str(tmp_path / "store.sqlite3")
    assert result.integrity == "OK"
    assert result.store_bytes > 0
    assert payload["counts"]["total"] == 7
    assert payload["counts"]["fts"] == 7
    assert payload["counts"]["by_source_type"] == {"CHATGPT_EXPORT": 4, "CURSOR_REPORT": 3}
    assert payload["counts"]["by_account"] == {
        "chatgpt_account_a": 2,
        "chatgpt_account_b": 2,
    }
    assert payload["counts"]["by_authority"] == {"NONE": 7}
    assert payload["counts"]["by_truth_kind"] == {
        "AGENT_REPORTED": 3,
        "HISTORICAL_CONTEXT": 4,
    }
    assert payload["counts"]["by_presence"] == {"CURRENT": 7}
    assert result.accounts[0]["import"]["inserted"] == 2
    assert result.accounts[1]["import"]["inserted"] == 2
    assert result.reports["inserted"] == 3
    assert result.reports_reimport["skipped"] == 3
    assert result.advisor["operator_status"] == "OK"
    assert result.advisor["public_status"] == "EMPTY"
    assert result.supervisor["operator_status"] == "OK"
    assert result.supervisor["public_status"] == "EMPTY"
    assert corpus.export_a.exists() and corpus.export_b.exists()

    connection = sqlite3.connect(str(tmp_path / "store.sqlite3"))
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        assert {"records", "records_fts"} <= tables
    finally:
        connection.close()
    store = KnowledgeStore.open(tmp_path / "store.sqlite3")
    assert store.schema_version() == "tradingai-knowledge-store/v1"
    assert store.integrity_check() == "OK"
    store.close()


# A04 / A09 / A11 ------------------------------------------------------------


def test_account_separation_same_conversation_and_message_ids(tmp_path):
    _run(tmp_path, _corpus(tmp_path))
    rows = _chatgpt_rows(tmp_path / "store.sqlite3")
    assert len(rows) == 4
    assert {row["source_account"] for row in rows} == {
        "chatgpt_account_a",
        "chatgpt_account_b",
    }
    identifiers = {row["source_identifier"] for row in rows}
    assert len(identifiers) == 4
    assert "chatgpt/chatgpt_account_a/conv-shared/m1" in identifiers
    assert "chatgpt/chatgpt_account_b/conv-shared/m1" in identifiers
    assert {row["conversation_id"] for row in rows} == {"conv-shared"}
    by_account = {(row["source_account"], row["message_id"]): row for row in rows}
    assert "alphamarker" in by_account[("chatgpt_account_a", "m1")]["content"]
    assert "betamarker" in by_account[("chatgpt_account_b", "m1")]["content"]
    assert "betamarker" not in by_account[("chatgpt_account_a", "m1")]["content"]
    assert all(row["metadata"]["account_alias"] == row["source_account"] for row in rows)


def test_source_identity_content_hash_and_timestamp(tmp_path):
    corpus = build_synthetic_corpus(tmp_path / "corpus")
    store = KnowledgeStore.create(tmp_path / "store.sqlite3")
    report = import_export(corpus.export_a, "chatgpt_account_a", store, indexed_at=INDEXED)
    assert report.status == "OK"
    store.close()
    rows = _chatgpt_rows(tmp_path / "store.sqlite3")
    assert rows
    for row in rows:
        assert row["content_hash"] == hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
        assert len(row["metadata"]["source_export_id"]) == 64
        assert row["source_timestamp"]
        assert row["collected_at"] == INDEXED
        assert row["source_identifier"] == (
            f"chatgpt/{row['source_account']}/{row['conversation_id']}/{row['message_id']}"
        )
    assert resolve_account("chatgpt_account_a").alias == "chatgpt_account_a"
    with pytest.raises(Exception) as rejected:
        resolve_account("user@example.com")
    assert getattr(rejected.value, "code", None) == "INVALID_ACCOUNT_ALIAS"


# A06 / A07 -----------------------------------------------------------------


def test_import_idempotency_reimport_and_duplicate_namespace(tmp_path):
    corpus = build_synthetic_corpus(tmp_path / "corpus")
    store = KnowledgeStore.create(tmp_path / "store.sqlite3")
    first = import_export(corpus.export_a, "chatgpt_account_a", store, indexed_at=INDEXED)
    second = import_export(corpus.export_a, "chatgpt_account_a", store, indexed_at=INDEXED2)
    assert first.inserted == 2
    assert second.inserted == 0 and second.skipped == 2 and second.superseded == 0
    assert len(_chatgpt_rows(tmp_path / "store.sqlite3")) == 2
    store.close()


def test_incremental_edited_message_supersedes(tmp_path):
    v1 = _zip(
        tmp_path / "v1.zip",
        [_conversation("conv-v", [("m1", "user", "TradingAI version one")])],
    )
    v2 = _zip(
        tmp_path / "v2.zip",
        [_conversation("conv-v", [("m1", "user", "TradingAI version two")])],
    )
    store = KnowledgeStore.create(tmp_path / "store.sqlite3")
    first = import_export(v1, "chatgpt_account_a", store, indexed_at=INDEXED)
    second = import_export(v2, "chatgpt_account_a", store, indexed_at=INDEXED2)
    assert first.inserted == 1
    assert second.inserted == 1 and second.superseded == 1
    store.close()
    rows = _chatgpt_rows(tmp_path / "store.sqlite3")
    assert len(rows) == 2
    states = {row["presence"]: row for row in rows}
    assert "version one" in states["HISTORICAL"]["content"]
    assert "version two" in states["CURRENT"]["content"]
    assert states["HISTORICAL"]["superseded_by"] == states["CURRENT"]["record_id"]


def test_deleted_message_is_not_inferred(tmp_path):
    both = _zip(
        tmp_path / "both.zip",
        [
            _conversation(
                "conv-del",
                [("m1", "user", "TradingAI first"), ("m2", "assistant", "TradingAI second")],
            )
        ],
    )
    only_one = _zip(
        tmp_path / "one.zip",
        [_conversation("conv-del", [("m1", "user", "TradingAI first")])],
    )
    store = KnowledgeStore.create(tmp_path / "store.sqlite3")
    import_export(both, "chatgpt_account_a", store, indexed_at=INDEXED)
    import_export(only_one, "chatgpt_account_a", store, indexed_at=INDEXED2)
    store.close()
    rows = _chatgpt_rows(tmp_path / "store.sqlite3")
    assert {row["message_id"] for row in rows} == {"m1", "m2"}
    assert all(row["presence"] == "CURRENT" for row in rows)


def test_partial_import_failure_rolls_back_then_retry_succeeds(tmp_path):
    store = KnowledgeStore.create(tmp_path / "store.sqlite3")
    good = _plain_item(source_identifier="chatgpt/a/c/m1")
    bad = _plain_item(source_identifier="chatgpt/a/c/m2", truth_kind="RUNTIME_VERIFIED")
    with pytest.raises(StoreError):
        commit_items(store, (good, bad), indexed_at=INDEXED)
    assert store.list_records(limit=20) == ()
    retried = commit_items(store, (good,), indexed_at=INDEXED)
    assert retried.inserted == 1
    store.close()


def test_cursor_report_incremental_update_and_removed_file_not_inferred(tmp_path):
    corpus = _corpus(tmp_path)
    result = _run(tmp_path, corpus)
    assert result.reports["inserted"] == 3
    target = corpus.report_dir / "cursor_alpha.md"
    target.write_text(
        "TASK_ID: TRADINGAI-WORK-BC-11A-SYNTHETIC-A\ncursoralphamarker version two TradingAI\n",
        encoding="utf-8",
    )
    second = _run(
        tmp_path,
        corpus,
        exports={
            "chatgpt_account_a": corpus.export_a,
            "chatgpt_account_b": corpus.export_b,
        },
        indexed_at=INDEXED2,
    )
    assert second.reports["inserted"] == 1 and second.reports["superseded"] == 1
    rows = _report_rows(tmp_path / "store.sqlite3")
    versions = [row for row in rows if row["relative_path"] == "cursor_alpha.md"]
    assert len(versions) == 2
    states = {row["presence"]: row for row in versions}
    assert "version two" in states["CURRENT"]["content"]
    assert states["HISTORICAL"]["superseded_by"] == states["CURRENT"]["record_id"]

    (corpus.report_dir / "notes.txt").unlink()
    third = _run(
        tmp_path,
        corpus,
        exports={
            "chatgpt_account_a": corpus.export_a,
            "chatgpt_account_b": corpus.export_b,
        },
        indexed_at="2026-11-04T02:00:00+00:00",
    )
    assert third.reports["status"] in {"OK", "PARTIAL"}
    remaining = {row["relative_path"] for row in _report_rows(tmp_path / "store.sqlite3")}
    assert "notes.txt" in remaining


def test_complete_report_scan_marks_removed_file_missing(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "one.md").write_text("TASK_ID: ONE TradingAI\n", encoding="utf-8")
    (reports / "two.md").write_text("TASK_ID: TWO TradingAI\n", encoding="utf-8")
    config = CollectorConfig(include_text=True)
    store = KnowledgeStore.create(tmp_path / "complete.sqlite3")
    first = collect_reports((reports,), allowed_roots=(reports,), config=config)
    result = ingest_collection(store, first, indexed_at=INDEXED, scan_scope="reports")
    assert result.inserted == 2
    (reports / "two.md").unlink()
    second = collect_reports((reports,), allowed_roots=(reports,), config=config)
    assert second.error is None and second.stopped_reason is None
    result = ingest_collection(store, second, indexed_at=INDEXED2, scan_scope="reports")
    assert result.missing == 1
    store.close()
    rows = _rows(tmp_path / "complete.sqlite3")
    states = {row["relative_path"]: row["presence"] for row in rows}
    assert states["one.md"] == "CURRENT"
    assert states["two.md"] == "MISSING"


# A05 / A08 / A17 -----------------------------------------------------------


def test_zip_security_errors_leave_store_unchanged_and_do_not_leak(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network or subprocess access")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    corpus = build_synthetic_corpus(tmp_path / "corpus")
    store = KnowledgeStore.create(tmp_path / "store.sqlite3")
    import_export(corpus.export_a, "chatgpt_account_a", store, indexed_at=INDEXED)
    before = store.list_records(limit=20)

    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"not a zip")
    slip = tmp_path / "slip.zip"
    with zipfile.ZipFile(slip, "w") as archive:
        archive.writestr("../escape.json", b"x")
        archive.writestr("conversations.json", json.dumps([]))
    absolute = tmp_path / "absolute.zip"
    with zipfile.ZipFile(absolute, "w") as archive:
        archive.writestr("/etc/passwd", b"x")
        archive.writestr("conversations.json", json.dumps([]))
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w"):
        pass
    unknown = _zip(tmp_path / "unknown.zip", {"unexpected": "shape"})
    large = _zip(
        tmp_path / "large.zip",
        [_conversation("conv-large", [("m1", "user", "TradingAI " + "x" * 200)])],
    )

    cases = (
        (corrupt, None, "INVALID_ZIP"),
        (slip, None, "PATH_TRAVERSAL"),
        (absolute, None, "ABSOLUTE_PATH"),
        (empty, None, "MISSING_CONVERSATIONS"),
        (unknown, None, "UNSUPPORTED_FORMAT"),
        (large, ImportLimits(max_json_bytes=64), "JSON_TOO_LARGE"),
    )
    for source, limits, code in cases:
        report = import_export(source, "chatgpt_account_a", store, indexed_at=INDEXED, limits=limits)
        assert report.status == "ERROR"
        assert report.error == code
        rendered = json.dumps(report.to_dict())
        assert "hunter" not in rendered
        assert "sk-synthetic" not in rendered

    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("conversations.json", json.dumps([]))
        archive.writestr("conversations.json", json.dumps([]))
    assert import_export(duplicate, "chatgpt_account_a", store, indexed_at=INDEXED).error == "DUPLICATE_ENTRY"

    assert store.list_records(limit=20) == before
    assert all("sk-synthetic" not in json.dumps(row) for row in store.list_records(limit=20))
    store.close()


def test_cursor_report_allowlist_extensions_secrets_and_encoding(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "ok.md").write_text("TASK_ID: OK TradingAI\n", encoding="utf-8")
    (reports / "api_key.txt").write_text("safe-looking\n", encoding="utf-8")
    (reports / "body.md").write_text("TASK_ID: BAD\npassword=hunter2\n", encoding="utf-8")
    (reports / ".hidden.md").write_text("hidden cursorhiddenmarker\n", encoding="utf-8")
    (reports / "ignored.py").write_text("cursorignoredmarker = 1\n", encoding="utf-8")
    (reports / "binary.md").write_bytes(b"\xff\xfe\x00")
    (reports / "big.md").write_text("x" * 500, encoding="utf-8")
    config = CollectorConfig(include_text=True, max_file_bytes=100)
    batch = collect_reports((reports,), allowed_roots=(reports,), config=config)
    statuses = {record.provenance.relative_path: record.collection_status for record in batch.records}
    assert statuses["ok.md"] == "METADATA_ONLY"
    assert next(
        record for record in batch.records if record.provenance.relative_path == "ok.md"
    ).text is not None
    assert statuses["api_key.txt"] == "SECRET_EXCLUDED"
    assert statuses["body.md"] == "SECRET_EXCLUDED"
    assert statuses[".hidden.md"] == "SECRET_EXCLUDED"
    assert statuses["binary.md"] == "UNSUPPORTED_ENCODING"
    assert statuses["big.md"] == "FILE_TOO_LARGE"
    assert "ignored.py" not in statuses
    rendered = json.dumps(batch.to_dict())
    assert "hunter2" not in rendered
    assert "cursorhiddenmarker" not in rendered

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text("TASK_ID: OUTSIDE\n", encoding="utf-8")
    assert collect_reports((outside,), allowed_roots=(reports,), config=config).error == (
        "REPORT_ROOT_NOT_ALLOWLISTED"
    )
    assert collect_reports((Path("/tmp"),), config=config).error == "REPORT_ROOT_NOT_ALLOWLISTED"
    assert collect_reports((Path.home(),), allowed_roots=(Path.home(),), config=config).error == (
        "REPORT_ROOT_NOT_ALLOWLISTED"
    )
    link = tmp_path / "link_dir"
    link.symlink_to(reports)
    assert collect_reports((link,), allowed_roots=(tmp_path,), config=config).error == "SYMLINK_REJECTED"


def test_error_isolation_between_accounts_and_retry(tmp_path):
    corpus = build_synthetic_corpus(tmp_path / "corpus")
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"broken")
    first = run_import_readiness(
        tmp_path / "store.sqlite3",
        chatgpt_exports={
            "chatgpt_account_a": corpus.export_a,
            "chatgpt_account_b": corrupt,
        },
        report_directories=(corpus.report_dir,),
        report_roots=(corpus.report_dir,),
        indexed_at=INDEXED,
    )
    assert first.accounts[0]["import"]["status"] == "OK"
    assert first.accounts[0]["import"]["inserted"] == 2
    assert first.accounts[1]["import"]["status"] == "ERROR"
    assert first.accounts[1]["import"]["error"] == "INVALID_ZIP"
    assert first.counts["by_account"] == {"chatgpt_account_a": 2}

    retried = run_import_readiness(
        tmp_path / "store.sqlite3",
        chatgpt_exports={"chatgpt_account_b": corpus.export_b},
        indexed_at=INDEXED2,
        report_directories=(corpus.report_dir,),
        report_roots=(corpus.report_dir,),
    )
    assert retried.accounts[0]["import"]["inserted"] == 2
    assert retried.counts["by_account"] == {
        "chatgpt_account_a": 2,
        "chatgpt_account_b": 2,
    }


# A12 -----------------------------------------------------------------------


def test_search_acceptance_and_read_only_access(tmp_path):
    corpus = _corpus(tmp_path)
    result = _run(
        tmp_path,
        corpus,
        probes=(
            SearchProbe("keyword", "alphamarker"),
            SearchProbe("phrase", "cursoralphamarker"),
            SearchProbe("source", "TradingAI", ReaderFilters(source_type="CHATGPT_EXPORT")),
            SearchProbe("account", "TradingAI", ReaderFilters(source_account="chatgpt_account_b")),
            SearchProbe("message", "betamarker", ReaderFilters(
                source_account="chatgpt_account_b",
                conversation_id="conv-shared",
                message_id="m1",
            )),
            SearchProbe("empty", "zzzznotfoundmarker"),
            SearchProbe("invalid", "!!!"),
        ),
    )
    by_name = {item["name"]: item for item in result.to_dict()["search"]}
    assert by_name["keyword"]["status"] == "OK"
    assert by_name["keyword"]["total_count"] == 2
    assert by_name["keyword"]["accounts"] == ["chatgpt_account_a"]
    assert by_name["keyword"]["source_types"] == ["CHATGPT_EXPORT"]
    assert by_name["phrase"]["status"] == "OK"
    assert by_name["phrase"]["source_types"] == ["CURSOR_REPORT"]
    assert by_name["phrase"]["source_identifiers"] == ["cursor_alpha.md"]
    assert by_name["source"]["status"] == "OK" and by_name["source"]["total_count"] == 4
    assert by_name["account"]["status"] == "OK" and by_name["account"]["total_count"] == 2
    assert by_name["message"]["status"] == "OK" and by_name["message"]["total_count"] == 1
    assert by_name["message"]["conversation_ids"] == ["conv-shared"]
    assert by_name["message"]["message_ids"] == ["m1"]
    assert by_name["empty"]["status"] == "EMPTY" and by_name["empty"]["total_count"] == 0
    assert by_name["invalid"]["status"] == "INVALID_QUERY"

    path = tmp_path / "store.sqlite3"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    reader, failure = open_reader(path)
    assert failure is None and reader is not None
    page = reader.search("cursoralphamarker", request=OPERATOR)
    assert page.status == "OK" and page.total_count == 1
    record_id = page.results[0].record_id
    direct = reader.get_record(record_id, request=OPERATOR)
    assert direct.status == "OK"
    assert direct.results[0].source_identifier == "cursor_alpha.md"
    assert direct.results[0].relative_path == "cursor_alpha.md"
    assert reader.search("cursoralphamarker", request=PUBLIC).status == "EMPTY"
    denied = reader.get_record(record_id, request=PUBLIC)
    assert denied.status == "ACCESS_DENIED" and denied.results == ()
    reader.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

    missing = tmp_path / "missing.sqlite3"
    reader, failure = open_reader(missing)
    assert reader is None and failure == "NOT_AVAILABLE"
    assert missing.exists() is False


# A13 / A14 / A15 -----------------------------------------------------------


def test_advisor_and_supervisor_contract(tmp_path):
    corpus = build_synthetic_corpus(tmp_path / "corpus")
    store_path = tmp_path / "store.sqlite3"
    result = run_import_readiness(
        store_path,
        chatgpt_exports={"chatgpt_account_a": corpus.export_a},
        indexed_at=INDEXED,
    )
    assert result.integrity == "OK"
    assert advisor_knowledge_enabled({}) is False
    assert supervisor_knowledge_enabled({}) is False
    assert advisor_knowledge_block(
        "TradingAI", store_path=str(store_path), identity="operator", environ={}
    ).status == "DISABLED"
    assert supervisor_knowledge_block(
        "TradingAI", store_path=str(store_path), identity="operator", environ={}
    ).status == "DISABLED"
    assert advisor_knowledge_block(
        "TradingAI", store_path=str(store_path), identity=None,
        environ={ADVISOR_ENABLED_ENV: "1"},
    ).status == "UNAUTHENTICATED"
    assert supervisor_knowledge_block(
        "TradingAI", store_path=str(store_path), identity=None,
        environ={SUPERVISOR_ENABLED_ENV: "1"},
    ).status == "UNAUTHENTICATED"

    advisor = advisor_knowledge_block(
        "TradingAI", store_path=str(store_path), identity="operator-session",
        environ={ADVISOR_ENABLED_ENV: "1"},
    )
    assert advisor.attached is True and advisor.status == "OK"
    assert advisor.block.startswith("BEGIN_UNTRUSTED_KNOWLEDGE")
    assert "truthKind=UNTRUSTED_HISTORICAL" in advisor.block
    supervisor = supervisor_knowledge_block(
        "TradingAI", store_path=str(store_path), identity="operator-session",
        environ={SUPERVISOR_ENABLED_ENV: "1"},
    )
    assert supervisor.attached is True and supervisor.status == "OK"

    class Payload:
        def __init__(self) -> None:
            self.knowledgeContextBlock = None

        def model_copy(self, update):
            clone = Payload()
            clone.knowledgeContextBlock = update.get("knowledgeContextBlock")
            return clone

    service_input = Payload()
    attached = attach_advisor_knowledge(
        service_input,
        question="TradingAI",
        identity="operator-session",
        store_path=str(store_path),
        environ={ADVISOR_ENABLED_ENV: "1"},
    )
    assert attached is not service_input
    assert service_input.knowledgeContextBlock is None
    assert attached.knowledgeContextBlock.startswith("BEGIN_UNTRUSTED_KNOWLEDGE")

    bb = {"schemaVersion": "tradingai-context/v1", "authority": "NONE"}
    merged = attach_supervisor_knowledge(
        bb,
        question="TradingAI",
        identity="operator-session",
        store_path=str(store_path),
        environ={SUPERVISOR_ENABLED_ENV: "1"},
    )
    assert merged is not bb
    assert bb == {"schemaVersion": "tradingai-context/v1", "authority": "NONE"}
    entry = merged["knowledgeContext"]
    assert entry["classification"] == "UNTRUSTED_KNOWLEDGE"
    assert entry["truthKind"] == "UNTRUSTED_HISTORICAL"
    assert entry["authority"] == "NONE"
    assert entry["tradingControl"] == "FORBIDDEN"
    assert entry["systemInstruction"] is False

    attachment = query_advisor_knowledge(
        "TradingAI", store_path=str(store_path), request=OPERATOR, bb_context=bb
    )
    assert attachment["bb_context"] is bb and attachment["bb_context_unchanged"] is True
    assert attachment["authority"] == "NONE"
    assert attachment["trading_control"] == "FORBIDDEN"
    assert attachment["system_instruction"] is False
    assert executed_commands(attachment) == ()
    public = query_supervisor_knowledge("TradingAI", store_path=str(store_path), request=PUBLIC)
    assert public["knowledge_status"] == "EMPTY"
    assert public["authority"] == "NONE"


def test_bb_cc_separation_and_no_runtime_truth(tmp_path):
    corpus = _corpus(tmp_path)
    result = _run(tmp_path, corpus)
    assert result.integrity == "OK"
    rows = _rows(tmp_path / "store.sqlite3")
    assert all(row["authority_scope"] == "NONE" for row in rows)
    assert {row["truth_kind"] for row in rows} == {"HISTORICAL_CONTEXT", "AGENT_REPORTED"}
    forbidden_metadata = ("position", "account_truth", "owner_scope", "trading_authority")
    for row in rows:
        rendered = json.dumps(row["metadata"]).lower()
        assert not any(term in rendered for term in forbidden_metadata)
    chatgpt = [row for row in rows if row["source_type"] == "CHATGPT_EXPORT"]
    assert all(row["metadata"]["trust"] == "UNTRUSTED_KNOWLEDGE" for row in chatgpt)
    assert all(row["metadata"]["authority"] == "NONE" for row in chatgpt)
    assert all(row["metadata"]["historical"] == "true" for row in chatgpt)
    cursor = [row for row in rows if row["source_type"] == "CURSOR_REPORT"]
    assert all(row["metadata"]["runtime_truth"] == "NOT_ASSERTED" for row in cursor)
    assert all(row["metadata"]["trust"] == "UNTRUSTED_KNOWLEDGE" for row in cursor)

    package = Path(__file__).resolve().parents[1] / "backend" / "knowledge_hub"
    forbidden = (
        "backend.context",
        "backend.bot_manager",
        "backend.main",
        "backend.api",
        "socket",
        "http.client",
        "requests",
        "urllib.request",
        "subprocess",
    )
    for name in ("import_readiness.py", "chatgpt_import/adapter.py", "chatgpt_import/importer.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                assert not any(
                    module == item or module.startswith(item + ".") for item in forbidden
                ), (name, module)


# A02 / A03 / A16 / A18 -----------------------------------------------------


def test_existing_importer_and_collector_are_reused():
    from backend.knowledge_hub.chatgpt_import.importer import import_export as canonical_import
    from backend.knowledge_hub.chatgpt_import.preview import preview_export as canonical_preview
    from backend.knowledge_hub.continuous_sync.sync_engine import ContinuousSyncEngine as canonical_engine

    assert readiness.import_export is canonical_import
    assert readiness.preview_export is canonical_preview
    assert readiness.ContinuousSyncEngine is canonical_engine
    source = (Path(readiness.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assert "parse_export" not in defined
    assert "collect_reports" not in defined
    assert "scan_reports" not in defined
    assert "KnowledgeStore" not in defined


def test_dry_run_preview_counts_and_no_store_creation(tmp_path):
    corpus = build_synthetic_corpus(tmp_path / "corpus")
    absent = tmp_path / "absent.sqlite3"
    preview = preview_export(corpus.export_a, "chatgpt_account_a", store_path=absent)
    assert preview.status == "OK"
    assert preview.new_record_count == 2
    assert preview.duplicate_count == 0
    assert preview.updated_record_count == 0
    assert preview.estimated_database_growth_bytes > 0
    assert preview.in_scope_count == 3
    assert preview.out_of_scope_count == 1
    assert preview.secret_flag_count == 1
    assert absent.exists() is False
    assert "alphamarker" not in json.dumps(preview.to_dict())

    _run(tmp_path, corpus)
    duplicate = preview_export(corpus.export_a, "chatgpt_account_a", store_path=tmp_path / "store.sqlite3")
    assert duplicate.duplicate_count == 2
    assert duplicate.new_record_count == 0

    updated = _zip(
        tmp_path / "updated.zip",
        [_conversation("conv-shared", [
            ("m1", "user", "TradingAI alphamarker edited"),
            ("m2", "assistant", "Knowledge hub alphamarker edited"),
        ])],
    )
    changed = preview_export(updated, "chatgpt_account_a", store_path=tmp_path / "store.sqlite3")
    assert changed.updated_record_count == 2
    assert changed.new_record_count == 0


def test_performance_synthetic_stress(tmp_path):
    export = build_synthetic_stress_export(
        tmp_path / "stress.zip",
        conversation_count=80,
        messages_per_conversation=8,
    )
    tracemalloc.start()
    started = time.perf_counter()
    result = run_import_readiness(
        tmp_path / "stress.sqlite3",
        chatgpt_exports={"chatgpt_account_a": export},
        indexed_at=INDEXED,
        search_probes=(SearchProbe("stress", "stressmarker"),),
    )
    elapsed = time.perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert result.integrity == "OK"
    assert result.counts["total"] == 640
    assert result.counts["by_account"] == {"chatgpt_account_a": 640}
    assert result.search[0]["status"] == "OK"
    assert result.search[0]["total_count"] == 640
    assert elapsed < 60.0
    assert result.duration_seconds < 60.0
    assert peak < 256 * 1024 * 1024

    reader, failure = open_reader(tmp_path / "stress.sqlite3")
    assert failure is None and reader is not None
    search_started = time.perf_counter()
    page = reader.search("stressmarker", request=OPERATOR)
    search_elapsed = time.perf_counter() - search_started
    reader.close()
    assert page.status == "OK" and page.total_count == 640
    assert search_elapsed < 5.0
