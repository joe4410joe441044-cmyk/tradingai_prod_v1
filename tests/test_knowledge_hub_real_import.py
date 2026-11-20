"""BC-11B approval-gated real export acceptance tests.

Every export is synthetic and every database is a temporary SQLite file. No
test reads a real ChatGPT export, opens the production knowledge store, starts
the backend, calls a network, or writes runtime state.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest

from backend.knowledge_hub import real_import
from backend.knowledge_hub.chatgpt_sync import Approval, preview_export_sync, validate_approval
from backend.knowledge_hub.chatgpt_sync.sync_engine import sync_export as canonical_sync_export
from backend.knowledge_hub.chatgpt_sync.sync_preview import (
    preview_export_sync as canonical_preview_export_sync,
)
from backend.knowledge_hub.import_readiness import (
    PRODUCTION_STORE_PATH,
    SearchProbe,
    assert_temporary_store,
    build_synthetic_corpus,
)
from backend.knowledge_hub.knowledge_store import KnowledgeStore
from backend.knowledge_hub.reader import ReaderFilters, RequestContext, open_reader
from backend.knowledge_hub.real_import import (
    ACCEPTANCE_BLOCKED,
    ACCEPTANCE_NOT_RUN,
    ACCEPTANCE_PASS,
    ACCEPTANCE_PREVIEW_ONLY,
    APPROVAL_SCHEMA_VERSION,
    RealImportError,
    empty_result,
    load_approval_manifest,
    parse_approval_manifest,
    run_real_import,
    validate_export_source,
)

INDEXED = "2026-11-05T00:00:00+00:00"
OBSERVED = "2026-11-05T00:00:00+00:00"
OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc11b-test")
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "bc11b_real_export_import.py"


def _corpus(tmp_path: Path):
    return build_synthetic_corpus(tmp_path / "corpus")


def _exports(corpus):
    return {
        "chatgpt_account_a": corpus.export_a,
        "chatgpt_account_b": corpus.export_b,
    }


def _run(tmp_path: Path, corpus, *, apply=False, manifest=None, store=None, probes=()):
    return run_real_import(
        store or (tmp_path / "store.sqlite3"),
        chatgpt_exports=_exports(corpus),
        approval_manifest=manifest,
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=apply,
        search_probes=probes,
    )


def _manifest_payload(preview, store: Path, *, overrides=None) -> dict:
    overrides = overrides or {}
    approvals = []
    for account in preview.accounts:
        entry = {
            "account_alias": account.account_alias,
            "export_content_hash": account.export_content_hash,
            "store_path": str(store),
            "approved_at": OBSERVED,
            "approved_by": "OPERATOR",
        }
        entry.update(overrides.get(account.account_alias, {}))
        approvals.append(entry)
    return {"schema_version": APPROVAL_SCHEMA_VERSION, "approvals": approvals}


def _write_manifest(preview, store: Path, path: Path, *, overrides=None) -> Path:
    path.write_text(json.dumps(_manifest_payload(preview, store, overrides=overrides)), encoding="utf-8")
    return path


def _valid_payload(**overrides) -> dict:
    entry = {
        "account_alias": "chatgpt_account_a",
        "export_content_hash": "a" * 64,
        "store_path": "/tmp/bc11b-store.sqlite3",
        "approved_at": OBSERVED,
        "approved_by": "OPERATOR",
    }
    entry.update(overrides)
    return {"schema_version": APPROVAL_SCHEMA_VERSION, "approvals": [entry]}


def _chatgpt_rows(path: Path) -> tuple[dict, ...]:
    store = KnowledgeStore.open(path)
    try:
        return tuple(
            row for row in store.list_records(limit=100) if row["source_type"] == "CHATGPT_EXPORT"
        )
    finally:
        store.close()


def test_cli_without_exports_is_no_input(tmp_path):
    result = subprocess.run(
        [sys.executable, str(CLI)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["REAL_IMPORT_EXECUTED"] == "NO"
    assert payload["REAL_EXPORT_ACCEPTANCE"] == "NOT_RUN"
    assert payload["real_import_executed"] is False
    assert payload["real_export_acceptance"] == ACCEPTANCE_NOT_RUN
    assert payload["errors"] == ["REAL_EXPORTS_NOT_PROVIDED"]


def test_cli_synthetic_preview_then_approved_import(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    workdir = tmp_path / "workdir"
    common = [
        "--account-a-export",
        str(corpus.export_a),
        "--account-b-export",
        str(corpus.export_b),
        "--store",
        str(store),
        "--workdir",
        str(workdir),
        "--observed-at",
        OBSERVED,
        "--indexed-at",
        INDEXED,
    ]
    preview = subprocess.run(
        [sys.executable, str(CLI), *common],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["REAL_IMPORT_EXECUTED"] == "NO"
    assert preview_payload["REAL_EXPORT_ACCEPTANCE"] == "PREVIEW_ONLY"
    assert store.exists() is False

    approvals = [
        {
            "account_alias": account["account_alias"],
            "export_content_hash": account["export_content_hash"],
            "store_path": str(store),
            "approved_at": OBSERVED,
            "approved_by": "OPERATOR",
        }
        for account in preview_payload["accounts"]
    ]
    manifest = tmp_path / "approval.json"
    manifest.write_text(
        json.dumps({"schema_version": APPROVAL_SCHEMA_VERSION, "approvals": approvals}),
        encoding="utf-8",
    )
    applied = subprocess.run(
        [sys.executable, str(CLI), *common, "--approval-manifest", str(manifest), "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["REAL_IMPORT_EXECUTED"] == "YES"
    assert applied_payload["REAL_EXPORT_ACCEPTANCE"] == ACCEPTANCE_PASS
    assert applied_payload["store"]["total"] == 4
    assert applied_payload["store"]["by_account"] == {
        "chatgpt_account_a": 2,
        "chatgpt_account_b": 2,
    }
    assert len(_chatgpt_rows(store)) == 4


def test_empty_result_has_no_store_and_not_run():
    result = empty_result()
    payload = result.to_dict()
    assert payload["mode"] == "NO_INPUT"
    assert payload["REAL_IMPORT_EXECUTED"] == "NO"
    assert payload["REAL_EXPORT_ACCEPTANCE"] == "NOT_RUN"
    assert payload["store_name"] is None
    assert payload["accounts"] == []


def test_approval_required_blocks_write_and_store_creation(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    preview = _run(tmp_path, corpus, apply=False, store=store)
    assert preview.real_export_acceptance == ACCEPTANCE_PREVIEW_ONLY
    assert preview.real_import_executed is False
    assert store.exists() is False
    assert all(account.export_content_hash for account in preview.accounts)

    blocked = _run(tmp_path, corpus, apply=True, store=store)
    assert blocked.real_export_acceptance == ACCEPTANCE_BLOCKED
    assert blocked.real_import_executed is False
    assert blocked.errors == ("APPROVAL_REQUIRED", "APPROVAL_REQUIRED")
    assert store.exists() is False


def test_approval_hash_and_store_path_mismatch_block_write(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    preview = _run(tmp_path, corpus, apply=False, store=store)

    wrong_hash = _write_manifest(
        preview,
        store,
        tmp_path / "wrong_hash.json",
        overrides={"chatgpt_account_a": {"export_content_hash": "0" * 64}},
    )
    result = _run(tmp_path, corpus, apply=True, manifest=wrong_hash, store=store)
    assert result.real_export_acceptance == ACCEPTANCE_BLOCKED
    assert result.accounts[0].error == "APPROVAL_MISMATCH"
    assert store.exists() is False

    wrong_store = _write_manifest(
        preview,
        store,
        tmp_path / "wrong_store.json",
        overrides={"chatgpt_account_a": {"store_path": str(tmp_path / "other.sqlite3")}},
    )
    result = _run(tmp_path, corpus, apply=True, manifest=wrong_store, store=store)
    assert result.real_export_acceptance == ACCEPTANCE_BLOCKED
    assert result.accounts[0].error == "APPROVAL_MISMATCH"
    assert store.exists() is False


def test_approval_account_mismatch_is_rejected_by_reused_gate(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    preview = preview_export_sync(
        corpus.export_a,
        "chatgpt_account_a",
        store_path=store,
        observed_at=OBSERVED,
    )
    wrong = Approval(
        account_alias="chatgpt_account_b",
        export_content_hash=preview.export_content_hash,
        store_path=str(store),
        approved_at=OBSERVED,
    )
    with pytest.raises(Exception) as rejected:
        validate_approval(
            wrong,
            preview=preview,
            account_alias="chatgpt_account_a",
            export_content_hash=preview.export_content_hash,
            store_path=store,
        )
    assert rejected.value.code == "APPROVAL_MISMATCH"


def test_export_input_validation_codes(tmp_path):
    missing = validate_export_source(tmp_path / "missing.zip", account_alias="chatgpt_account_a")
    assert missing.code == "EXPORT_NOT_FOUND"

    real = tmp_path / "real.zip"
    with zipfile.ZipFile(real, "w") as archive:
        archive.writestr("conversations.json", json.dumps([]))
    link = tmp_path / "link.zip"
    link.symlink_to(real)
    assert (
        validate_export_source(link, account_alias="chatgpt_account_a").code
        == "EXPORT_SYMLINK_REJECTED"
    )

    directory = tmp_path / "directory.zip"
    directory.mkdir()
    assert (
        validate_export_source(directory, account_alias="chatgpt_account_a").code
        == "EXPORT_NOT_FILE"
    )

    text = tmp_path / "notes.txt"
    text.write_text("not an export", encoding="utf-8")
    assert (
        validate_export_source(text, account_alias="chatgpt_account_a").code
        == "EXPORT_NOT_ZIP"
    )

    empty = tmp_path / "empty.zip"
    empty.write_bytes(b"")
    assert validate_export_source(empty, account_alias="chatgpt_account_a").code == "EXPORT_EMPTY"

    production = validate_export_source(PRODUCTION_STORE_PATH, account_alias="chatgpt_account_a")
    assert production.code == "PRODUCTION_EXPORT_REJECTED"

    same = validate_export_source(real, account_alias="chatgpt_account_a", store_path=real)
    assert same.code == "EXPORT_IS_STORE"

    assert (
        validate_export_source(real, account_alias="user@example.com").code
        == "INVALID_ACCOUNT_ALIAS"
    )
    assert (
        validate_export_source(real, account_alias="chatgpt_account_c").code
        == "ACCOUNT_NAMESPACE_REJECTED"
    )


def test_corrupt_export_is_rejected_before_store(tmp_path):
    corpus = _corpus(tmp_path)
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"not a zip")
    store = tmp_path / "store.sqlite3"
    result = run_real_import(
        store,
        chatgpt_exports={"chatgpt_account_a": corrupt},
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=True,
    )
    assert result.real_export_acceptance == ACCEPTANCE_BLOCKED
    assert result.accounts[0].error == "INVALID_ZIP"
    assert store.exists() is False


def test_isolated_store_guard_rejects_production_symlink_and_outside(tmp_path):
    corpus = _corpus(tmp_path)
    exports = {"chatgpt_account_a": corpus.export_a}

    production = run_real_import(
        PRODUCTION_STORE_PATH,
        chatgpt_exports=exports,
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=False,
    )
    assert production.real_export_acceptance == ACCEPTANCE_BLOCKED
    assert production.errors == ("PRODUCTION_STORE_REJECTED",)
    assert production.accounts == ()

    link = tmp_path / "link.sqlite3"
    link.symlink_to(tmp_path / "real.sqlite3")
    symlinked = run_real_import(
        link,
        chatgpt_exports=exports,
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=False,
    )
    assert symlinked.errors == ("STORE_SYMLINK_REJECTED",)

    outside_root = tmp_path / "allowed"
    outside_root.mkdir()
    outside = run_real_import(
        tmp_path / "outside.sqlite3",
        chatgpt_exports=exports,
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=False,
        allowed_store_root=outside_root,
    )
    assert outside.errors == ("STORE_OUTSIDE_ALLOWED_ROOT",)

    runtime_root = real_import.PRODUCTION_RUNTIME_ROOT
    runtime_store = run_real_import(
        runtime_root / "knowledge_hub" / "bc11b.sqlite3",
        chatgpt_exports=exports,
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=False,
        allowed_store_root=runtime_root,
    )
    assert runtime_store.errors == ("PRODUCTION_RUNTIME_ROOT_REJECTED",)


def test_synthetic_account_a_b_import_separation(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    preview = _run(tmp_path, corpus, apply=False, store=store)
    manifest = _write_manifest(preview, store, tmp_path / "approval.json")
    result = _run(tmp_path, corpus, apply=True, manifest=manifest, store=store)

    assert result.real_export_acceptance == ACCEPTANCE_PASS
    assert result.real_import_executed is True
    assert result.integrity == "OK"
    assert result.store["user_version"] == 1
    assert result.store["total"] == 4
    assert result.store["fts"] == 4
    assert result.store["by_account"] == {
        "chatgpt_account_a": 2,
        "chatgpt_account_b": 2,
    }
    assert result.store["by_source_type"] == {"CHATGPT_EXPORT": 4}
    statuses = {account.account_alias: account.status for account in result.accounts}
    assert statuses == {"chatgpt_account_a": "PARTIAL", "chatgpt_account_b": "OK"}
    assert all(account.imported and account.approved for account in result.accounts)
    assert result.accounts[0].preview["secret_rejected_count"] == 1
    assert result.accounts[0].preview["out_of_scope_count"] == 1

    rows = _chatgpt_rows(store)
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
    assert all(row["authority_scope"] == "NONE" for row in rows)


def test_idempotent_reimport_does_not_duplicate(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    preview = _run(tmp_path, corpus, apply=False, store=store)
    manifest = _write_manifest(preview, store, tmp_path / "approval.json")
    first = _run(tmp_path, corpus, apply=True, manifest=manifest, store=store)
    assert first.store["total"] == 4

    second = _run(tmp_path, corpus, apply=True, manifest=manifest, store=store)
    assert second.real_export_acceptance == ACCEPTANCE_PASS
    assert second.store["total"] == 4
    by_alias = {account.account_alias: account for account in second.accounts}
    assert by_alias["chatgpt_account_b"].import_report["export_state"] == "EXPORT_UNCHANGED"
    for account in second.accounts:
        assert account.import_report["inserted"] == 0
        assert account.import_report["superseded"] == 0
    assert by_alias["chatgpt_account_b"].import_report["skipped"] == 0
    assert len(_chatgpt_rows(store)) == 4


def test_search_store_integrity_and_privacy_safe_report(tmp_path):
    corpus = _corpus(tmp_path)
    store = tmp_path / "store.sqlite3"
    preview = _run(tmp_path, corpus, apply=False, store=store)
    manifest = _write_manifest(preview, store, tmp_path / "approval.json")
    result = _run(
        tmp_path,
        corpus,
        apply=True,
        manifest=manifest,
        store=store,
        probes=(
            SearchProbe("alpha", "alphamarker"),
            SearchProbe("beta", "betamarker"),
            SearchProbe("secret", "sk-synthetic"),
            SearchProbe("missing", "zzzznotfoundmarker"),
        ),
    )
    by_name = {item["name"]: item for item in result.search}
    assert by_name["alpha"]["status"] == "OK"
    assert by_name["alpha"]["total_count"] == 2
    assert by_name["alpha"]["accounts"] == ["chatgpt_account_a"]
    assert by_name["beta"]["status"] == "OK"
    assert by_name["beta"]["total_count"] == 2
    assert by_name["beta"]["accounts"] == ["chatgpt_account_b"]
    assert by_name["secret"]["status"] in {"EMPTY", "OK"}
    assert by_name["secret"]["total_count"] == 0
    assert by_name["missing"]["status"] == "EMPTY"

    rendered = json.dumps(result.to_dict())
    for marker in (
        "alphamarker",
        "betamarker",
        "sk-synthetic",
        "hunter2",
        "Boil water",
        "Pasta recipes",
        "shared conversation",
    ):
        assert marker not in rendered

    reader, failure = open_reader(store)
    assert failure is None and reader is not None
    try:
        alpha = reader.search(
            "alphamarker", request=OPERATOR, filters=ReaderFilters(source_account="chatgpt_account_a")
        )
        beta = reader.search(
            "alphamarker", request=OPERATOR, filters=ReaderFilters(source_account="chatgpt_account_b")
        )
        secret = reader.search("sk-synthetic", request=OPERATOR)
        assert alpha.status == "OK" and alpha.total_count == 2
        assert beta.status in {"EMPTY"}
        assert beta.total_count == 0
        assert secret.total_count == 0
    finally:
        reader.close()

    connection = sqlite3.connect(str(store))
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        assert {"records", "records_fts"} <= tables
    finally:
        connection.close()


def test_approval_manifest_validation(tmp_path):
    with pytest.raises(RealImportError) as missing:
        load_approval_manifest(tmp_path / "missing.json")
    assert missing.value.code == "APPROVAL_MANIFEST_NOT_FOUND"

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(RealImportError) as invalid:
        load_approval_manifest(invalid_json)
    assert invalid.value.code == "APPROVAL_MANIFEST_INVALID"

    symlink = tmp_path / "manifest_link.json"
    symlink.symlink_to(invalid_json)
    with pytest.raises(RealImportError) as linked:
        load_approval_manifest(symlink)
    assert linked.value.code == "APPROVAL_MANIFEST_SYMLINK_REJECTED"

    with pytest.raises(RealImportError) as schema:
        parse_approval_manifest({"schema_version": "wrong", "approvals": []})
    assert schema.value.code == "APPROVAL_MANIFEST_SCHEMA_MISMATCH"

    with pytest.raises(RealImportError) as empty:
        parse_approval_manifest({"schema_version": APPROVAL_SCHEMA_VERSION, "approvals": []})
    assert empty.value.code == "APPROVAL_MANIFEST_EMPTY"

    with pytest.raises(RealImportError) as bad_hash:
        parse_approval_manifest(_valid_payload(export_content_hash="short"))
    assert bad_hash.value.code == "APPROVAL_EXPORT_HASH_INVALID"

    with pytest.raises(RealImportError) as bad_alias:
        parse_approval_manifest(_valid_payload(account_alias="chatgpt_account_c"))
    assert bad_alias.value.code == "ACCOUNT_NAMESPACE_REJECTED"

    payload = _valid_payload()
    payload["approvals"].append(dict(payload["approvals"][0]))
    with pytest.raises(RealImportError) as duplicate:
        parse_approval_manifest(payload)
    assert duplicate.value.code == "APPROVAL_MANIFEST_DUPLICATE_ACCOUNT"

    parsed = parse_approval_manifest(_valid_payload())
    assert parsed.schema_version == APPROVAL_SCHEMA_VERSION
    assert parsed.approvals[0].account_alias == "chatgpt_account_a"


def test_invalid_account_and_export_are_isolated_from_other_account(tmp_path):
    corpus = _corpus(tmp_path)
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"broken")
    store = tmp_path / "store.sqlite3"
    preview = run_real_import(
        store,
        chatgpt_exports={"chatgpt_account_a": corpus.export_a, "chatgpt_account_b": corrupt},
        observed_at=OBSERVED,
        indexed_at=INDEXED,
        apply=False,
    )
    assert preview.accounts[0].status == "PREVIEW"
    assert preview.accounts[1].error == "INVALID_ZIP"

    with pytest.raises(RealImportError) as timestamp:
        run_real_import(
            store,
            chatgpt_exports={"chatgpt_account_a": corpus.export_a},
            observed_at="",
            indexed_at=INDEXED,
            apply=False,
        )
    assert timestamp.value.code == "TIMESTAMP_REQUIRED"


def test_reuses_bc11a_guard_and_bc7_engine_without_reimplementation():
    from backend.knowledge_hub.chatgpt_import.importer import import_export as canonical_import

    assert real_import.preview_export_sync is canonical_preview_export_sync
    assert real_import.sync_export is canonical_sync_export
    assert real_import.assert_temporary_store is assert_temporary_store
    assert real_import.validate_approval is validate_approval
    assert canonical_import is not None

    source = Path(real_import.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    for forbidden in ("parse_export", "import_export", "collect_reports", "scan_reports"):
        assert forbidden not in defined
