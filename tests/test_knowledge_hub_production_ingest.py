"""Offline acceptance for the explicitly authorized Production ingestion path.

Every write in this module targets an isolated temporary Store. The Production
Store is only ever inspected read-only, or intentionally rejected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from backend.knowledge_hub import production_ingest as ingest
from backend.knowledge_hub.import_readiness import (
    PRODUCTION_STORE_PATH,
    ReadinessError,
    assert_temporary_store,
)
from backend.knowledge_hub.knowledge_store import (
    KnowledgeStore,
    StoreError,
    StoreItem,
    StoreLimits,
    version_id,
)
from backend.knowledge_hub.partial_import import _build_item, discover_records
from backend.knowledge_hub.reader import ReaderLimits, RequestContext, open_reader


AT = datetime.fromisoformat("2026-11-21T00:00:00+00:00")
EXPIRES = AT + timedelta(hours=24)
REAL_MANIFEST = Path("/tmp/work_bc_audit/BC_G12_IMPORT_CANDIDATE_MANIFEST.json")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_payload(records, *, target=None):
    return {
        "schema_version": ingest.CANDIDATE_MANIFEST_SCHEMA_VERSION,
        "task_id": "TRADINGAI-WORK-BC-G12-TEST",
        "original_task_id": "TRADINGAI-WORK-BC-G12-TEST",
        "g12_status": "PENDING_OPERATOR_AUTHORIZATION",
        "production_import_performed": False,
        "source_of_evidence": "isolated test fixture",
        "target_for_review": str(target or PRODUCTION_STORE_PATH),
        "record_count": len(records),
        "records": records,
    }


def _candidate_entry(record_id: str, path: Path):
    data = path.read_bytes()
    return {
        "RECORD_ID": record_id,
        "STORE_RECORD_ID": "",
        "SOURCE_IDENTIFIER": str(path.resolve()),
        "CONTENT_HASH": hashlib.sha256(data).hexdigest(),
        "SOURCE_TYPE": "DEVELOPMENT_REPORT",
        "TRUTH_KIND": "AGENT_REPORTED",
        "AUTHORITY_SCOPE": "NONE",
        "ACCESS_SCOPE": "OPERATOR",
        "TRUST_CLASSIFICATION": "UNTRUSTED_KNOWLEDGE",
        "REDACTION_STATUS": "NOT_REQUIRED",
        "PROVENANCE_STATUS": "CONFIRMED",
        "IMPORT_ELIGIBILITY": "ELIGIBLE_CANDIDATE_PENDING_G12",
    }


def _finalize_store_ids(entries):
    paths = [Path(item["SOURCE_IDENTIFIER"]) for item in entries]
    roots = tuple(sorted({str(path.parent.resolve()) for path in paths}))
    discovered, blocked = discover_records(paths, source_roots=roots)
    assert not blocked
    by_hash = {record.content_hash: record for record in discovered}
    for entry in entries:
        record = by_hash[entry["CONTENT_HASH"]]
        item = _build_item(
            record,
            content=record.content,
            content_hash=record.content_hash,
            workstream=record.workstream,
            decision_record_id=entry["RECORD_ID"],
            redacted=False,
            indexed_at=AT.isoformat(),
        )
        entry["STORE_RECORD_ID"] = version_id(item, item.content_hash)
    return entries


def _write_manifest(tmp_path: Path, payload) -> tuple[Path, str]:
    path = tmp_path / "candidate_manifest.json"
    raw = json.dumps(payload, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _write_authorization(tmp_path: Path, payload) -> Path:
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _authorization_payload(
    manifest,
    store: Path,
    *,
    state: str,
    sha: str | None,
    manifest_sha: str,
    **overrides,
):
    payload = {
        "schema_version": ingest.AUTHORIZATION_SCHEMA_VERSION,
        "task_id": "TRADINGAI-WORK-BC-G12-TEST",
        "workstream": "BC",
        "environment": ingest.ISOLATED_ENVIRONMENT,
        "target_store": str(store.resolve()),
        "target_store_state": state,
        "target_store_sha256": sha,
        "manifest_sha256": manifest_sha,
        "approved_record_ids": list(manifest.record_ids),
        "approved_content_hashes": list(manifest.content_hashes),
        "approved_store_record_ids": list(manifest.store_record_ids),
        "approved_operation": ingest.G12_OPERATION,
        "approval_id": "approval-g12-test-1",
        "approval_time": AT.isoformat(),
        "expires_at": EXPIRES.isoformat(),
        "authorized": True,
    }
    payload.update(overrides)
    return payload


def _fixture(tmp_path: Path):
    root = tmp_path / "sources"
    root.mkdir()
    texts = (
        "TASK_ID: SYNTH-A\nWORKSTREAM: BC\nVERDICT: PASS\nWORKTREE: work-a\n"
        "BRANCH: branch-a\nsynthalphamarker\n",
        "TASK_ID: SYNTH-B\nWORKSTREAM: BC\nVERDICT: PASS\nWORKTREE: work-b\n"
        "BRANCH: branch-b\nsynthbetamarker\n",
        "TASK_ID: SYNTH-C\nWORKSTREAM: BC\nVERDICT: PASS\nWORKTREE: work-c\n"
        "BRANCH: branch-c\nsynthgammamarker\n",
    )
    paths = []
    for index, text in enumerate(texts, start=1):
        path = root / f"report_{index}.md"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    entries = _finalize_store_ids(
        [_candidate_entry(f"xwsrc_synth{index}", path) for index, path in enumerate(paths, 1)]
    )
    manifest_path, manifest_sha = _write_manifest(tmp_path, _manifest_payload(entries))
    manifest = ingest.load_candidate_manifest(manifest_path)
    store = tmp_path / "isolated_store.sqlite3"
    return {
        "root": root,
        "paths": paths,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha": manifest_sha,
        "store": store,
    }


def _auth(fixture, *, state="ABSENT", sha=None, manifest_sha=None, **overrides):
    return ingest.parse_authorization(
        _authorization_payload(
            fixture["manifest"],
            fixture["store"],
            state=state,
            sha=sha,
            manifest_sha=fixture["manifest_sha"] if manifest_sha is None else manifest_sha,
            **overrides,
        )
    )


def _run(fixture, auth, *, apply=True, audit_path=None):
    guard = ingest.isolated_target_guard(fixture["store"])
    return ingest.run_authorized_import(
        guard,
        auth,
        fixture["manifest"],
        indexed_at=AT.isoformat(),
        apply=apply,
        audit_path=audit_path,
        now=AT,
    )


def _rows(store: Path):
    knowledge = KnowledgeStore.open(store, StoreLimits(max_results=500))
    try:
        return knowledge.list_records(limit=500)
    finally:
        knowledge.close()


def _count(store: Path) -> int:
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT count(*) FROM records").fetchone()[0])
    finally:
        connection.close()


def test_isolated_authorized_import_preserves_trust_and_search(tmp_path):
    fixture = _fixture(tmp_path)
    audit_path = tmp_path / "audit.json"
    result = _run(fixture, _auth(fixture), audit_path=audit_path)
    assert result.status == ingest.STATUS_COMPLETE
    assert result.applied is True
    assert result.inserted == 3
    assert result.skipped == 0
    assert result.record_count_after == 3
    assert result.fts_count_after == 3
    assert result.integrity_after == "OK"
    assert result.environment == ingest.ISOLATED_ENVIRONMENT
    assert result.backup is None

    rows = _rows(fixture["store"])
    assert len(rows) == 3
    assert {row["source_type"] for row in rows} == {"DEVELOPMENT_REPORT"}
    assert {row["truth_kind"] for row in rows} == {"AGENT_REPORTED"}
    assert {row["authority_scope"] for row in rows} == {"NONE"}
    for row in rows:
        metadata = row["metadata"]
        assert metadata["access_scope"] == "OPERATOR"
        assert metadata["trust"] == "UNTRUSTED_KNOWLEDGE"
        assert metadata["runtime_truth"] == "NOT_ASSERTED"
        assert metadata["historical_authority"] == "UNTRUSTED_HISTORICAL"
        assert metadata["record_approval_record_id"].startswith("xwsrc_")
    assert [row["record_id"] for row in rows] == sorted(
        fixture["manifest"].store_record_ids
    )

    reader, failure = open_reader(fixture["store"], ReaderLimits(max_results=10))
    assert reader is not None, failure
    try:
        response = reader.search(
            "synthalphamarker",
            request=RequestContext(caller_scope="OPERATOR"),
        )
    finally:
        reader.close()
    assert response.status == "OK"
    assert response.total_count == 1

    for role in ("ADVISOR", "SUPERVISOR"):
        probe = ingest.query_isolated_read(
            fixture["store"], "synthalphamarker", role=role
        )
        assert probe["knowledge_status"] == "OK"
        assert probe["authority"] == "NONE"
        assert probe["trading_control"] == "FORBIDDEN"
        assert probe["returned_count"] == 1

    assert audit_path.is_file()
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_payload["status"] == ingest.STATUS_COMPLETE
    assert "content" not in json.dumps(
        [event.get("content") for event in audit_payload["audit"]]
    )


def test_idempotent_rerun_skips_all_records(tmp_path):
    fixture = _fixture(tmp_path)
    first = _run(fixture, _auth(fixture))
    assert first.status == ingest.STATUS_COMPLETE
    second = _run(
        fixture,
        _auth(fixture, state="PRESENT", sha=first.store_sha256_after),
    )
    assert second.status == ingest.STATUS_IDEMPOTENT
    assert second.inserted == 0
    assert second.skipped == 3
    assert second.record_count_after == first.record_count_after == 3
    assert _count(fixture["store"]) == 3


def test_missing_authorization_fails_closed(tmp_path):
    fixture = _fixture(tmp_path)
    result = _run(fixture, None)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_REQUIRED",)
    assert not fixture["store"].exists()


def _production_signed_payload(fixture, key: bytes, **overrides):
    payload = _authorization_payload(
        fixture["manifest"],
        fixture["store"],
        state="ABSENT",
        sha=None,
        manifest_sha=fixture["manifest_sha"],
        environment=ingest.PRODUCTION_ENVIRONMENT,
        **overrides,
    )
    payload["approval_signature_method"] = ingest.APPROVAL_SIGNATURE_METHOD
    payload["approval_signature"] = ingest.sign_authorization_payload(payload, key)
    return payload


def test_authorization_signature_roundtrip_and_tamper():
    key = b"k" * ingest.MIN_APPROVAL_KEY_BYTES
    payload = {
        "manifest_sha256": "a" * 64,
        "approval_signature_method": ingest.APPROVAL_SIGNATURE_METHOD,
    }
    payload["approval_signature"] = ingest.sign_authorization_payload(payload, key)
    ingest.verify_authorization_signature(payload, key)

    tampered = dict(payload)
    tampered["manifest_sha256"] = "b" * 64
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.verify_authorization_signature(tampered, key)
    assert exc.value.code == "APPROVAL_SIGNATURE_MISMATCH"

    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.verify_authorization_signature(payload, b"z" * ingest.MIN_APPROVAL_KEY_BYTES)
    assert exc.value.code == "APPROVAL_SIGNATURE_MISMATCH"

    unsigned = dict(payload)
    unsigned.pop("approval_signature_method")
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.verify_authorization_signature(unsigned, key)
    assert exc.value.code == "APPROVAL_SIGNATURE_METHOD_REJECTED"


def test_production_authorization_requires_operator_signature(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    key = b"k" * ingest.MIN_APPROVAL_KEY_BYTES
    monkeypatch.delenv(ingest.APPROVAL_KEY_ENV, raising=False)
    monkeypatch.delenv(ingest.APPROVAL_KEY_FILE_ENV, raising=False)

    unsigned_path = _write_authorization(
        tmp_path,
        _authorization_payload(
            fixture["manifest"],
            fixture["store"],
            state="ABSENT",
            sha=None,
            manifest_sha=fixture["manifest_sha"],
            environment=ingest.PRODUCTION_ENVIRONMENT,
        ),
    )
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.load_authorization(unsigned_path)
    assert exc.value.code == "APPROVAL_SIGNATURE_KEY_REQUIRED"

    monkeypatch.setenv(ingest.APPROVAL_KEY_ENV, key.decode("utf-8"))
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.load_authorization(unsigned_path)
    assert exc.value.code == "APPROVAL_SIGNATURE_METHOD_REJECTED"

    signed_payload = _production_signed_payload(fixture, key)
    signed_path = _write_authorization(tmp_path, signed_payload)
    authorization = ingest.load_authorization(signed_path)
    assert authorization.environment == ingest.PRODUCTION_ENVIRONMENT

    tampered_payload = dict(signed_payload)
    tampered_payload["approval_id"] = "tampered-approval"
    tampered_path = _write_authorization(tmp_path, tampered_payload)
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.load_authorization(tampered_path)
    assert exc.value.code == "APPROVAL_SIGNATURE_MISMATCH"


def test_operator_key_file_must_not_be_group_or_world_readable(tmp_path, monkeypatch):
    key = b"k" * ingest.MIN_APPROVAL_KEY_BYTES
    key_file = tmp_path / "g12_approval.key"
    key_file.write_bytes(key)
    key_file.chmod(0o644)
    monkeypatch.delenv(ingest.APPROVAL_KEY_ENV, raising=False)
    monkeypatch.setenv(ingest.APPROVAL_KEY_FILE_ENV, str(key_file))
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.load_approval_key()
    assert exc.value.code == "APPROVAL_SIGNATURE_KEY_FILE_PERMISSIONS_REJECTED"

    key_file.chmod(0o600)
    assert ingest.load_approval_key() == key


def test_isolated_authorization_does_not_require_signature(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    monkeypatch.delenv(ingest.APPROVAL_KEY_ENV, raising=False)
    monkeypatch.delenv(ingest.APPROVAL_KEY_FILE_ENV, raising=False)
    auth_path = _write_authorization(
        tmp_path,
        _authorization_payload(
            fixture["manifest"],
            fixture["store"],
            state="ABSENT",
            sha=None,
            manifest_sha=fixture["manifest_sha"],
        ),
    )
    authorization = ingest.load_authorization(auth_path)
    assert authorization.environment == ingest.ISOLATED_ENVIRONMENT


def test_exact_allowlist_is_enforced(tmp_path):
    fixture = _fixture(tmp_path)
    subset = _auth(
        fixture,
        approved_record_ids=[fixture["manifest"].record_ids[0]],
        approved_content_hashes=[fixture["manifest"].content_hashes[0]],
        approved_store_record_ids=[fixture["manifest"].store_record_ids[0]],
    )
    result = _run(fixture, subset)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_RECORD_SCOPE_MISMATCH",)
    assert not fixture["store"].exists()


def test_manifest_hash_mismatch_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    auth = _auth(fixture, manifest_sha="0" * 64)
    result = _run(fixture, auth)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("MANIFEST_HASH_MISMATCH",)
    assert not fixture["store"].exists()


def test_changed_source_content_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    fixture["paths"][0].write_text(
        fixture["paths"][0].read_text(encoding="utf-8") + "changed after approval\n",
        encoding="utf-8",
    )
    result = _run(fixture, _auth(fixture))
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors[0] in {
        "DISCOVERED_SOURCE_SET_MISMATCH",
        "SOURCE_CONTENT_HASH_MISMATCH",
        "SOURCE_HASH_MISMATCH",
    }
    assert not fixture["store"].exists()


def test_symlinked_source_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    original = fixture["paths"][0]
    target = tmp_path / "real_source.md"
    original.rename(target)
    original.symlink_to(target)
    result = _run(fixture, _auth(fixture))
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors[0] in {"SOURCE_BLOCKED:SYMLINK_REJECTED"}
    assert not fixture["store"].exists()


def test_wrong_target_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    other = ingest.parse_authorization(
        _authorization_payload(
            fixture["manifest"],
            tmp_path / "other_store.sqlite3",
            state="ABSENT",
            sha=None,
            manifest_sha=fixture["manifest_sha"],
        )
    )
    result = _run(fixture, other)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_TARGET_MISMATCH",)
    assert not fixture["store"].exists()


def test_expired_and_future_authorization_are_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    expired = _auth(
        fixture,
        approval_time=(AT - timedelta(hours=2)).isoformat(),
        expires_at=(AT - timedelta(hours=1)).isoformat(),
    )
    result = _run(fixture, expired)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_EXPIRED",)

    future = _auth(
        fixture,
        approval_time=(AT + timedelta(hours=1)).isoformat(),
        expires_at=(AT + timedelta(hours=2)).isoformat(),
    )
    result = _run(fixture, future)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_NOT_YET_VALID",)
    assert not fixture["store"].exists()


def test_wrong_operation_and_workstream_are_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    wrong_operation = _auth(fixture, approved_operation="G9_READ_ONLY")
    result = _run(fixture, wrong_operation)
    assert result.errors == ("AUTHORIZATION_OPERATION_MISMATCH",)

    wrong_workstream = _auth(fixture, workstream="AA")
    result = _run(fixture, wrong_workstream)
    assert result.errors == ("AUTHORIZATION_WORKSTREAM_MISMATCH",)
    assert not fixture["store"].exists()


def test_transaction_atomicity_prevents_partial_write(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    KnowledgeStore.create(fixture["store"]).close()
    baseline = KnowledgeStore.open(fixture["store"])
    try:
        baseline.upsert(
            StoreItem(
                source_type="DEVELOPMENT_REPORT",
                source_identifier=str((tmp_path / "baseline.md").resolve()),
                record_type="DEVELOPMENT_REPORT",
                title="baseline.md",
                content="baseline marker\n",
                collected_at=AT.isoformat(),
                verification_state="COLLECTED",
                truth_kind="AGENT_REPORTED",
                relative_path="baseline.md",
            ),
            indexed_at=AT.isoformat(),
            scan_scope="baseline",
        )
    finally:
        baseline.close()
    sha = _hash(fixture["store"])
    auth = _auth(fixture, state="PRESENT", sha=sha)

    real_upsert = KnowledgeStore.upsert
    calls = {"count": 0}

    def failing_upsert(self, item, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise StoreError("INJECTED_TRANSACTION_FAILURE")
        return real_upsert(self, item, **kwargs)

    monkeypatch.setattr(KnowledgeStore, "upsert", failing_upsert)
    result = _run(fixture, auth)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("INJECTED_TRANSACTION_FAILURE",)
    assert result.inserted == 0
    assert _count(fixture["store"]) == 1
    rows = _rows(fixture["store"])
    assert rows[0]["title"] == "baseline.md"


def test_stale_target_sha_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    KnowledgeStore.create(fixture["store"]).close()
    auth = _auth(fixture, state="PRESENT", sha="0" * 64)
    result = _run(fixture, auth)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_STORE_HASH_MISMATCH",)


def test_corrupt_and_wrong_schema_targets_are_rejected(tmp_path):
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a database")
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.inspect_target(corrupt)
    assert exc.value.code == "TARGET_NOT_DATABASE"

    wrong = tmp_path / "wrong_schema.sqlite3"
    connection = sqlite3.connect(wrong)
    try:
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.inspect_target(wrong)
    assert exc.value.code == "TARGET_SCHEMA_MISMATCH"


def test_unexpected_permissions_are_rejected(tmp_path):
    parent = tmp_path / "protected"
    parent.mkdir(mode=0o700)
    allowed = parent / "store.sqlite3"
    allowed.write_bytes(b"x")
    allowed.chmod(0o600)
    ingest.validate_file_protection(allowed)
    allowed.chmod(0o644)
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.validate_file_protection(allowed)
    assert exc.value.code == "TARGET_PERMISSIONS_REJECTED"


def test_duplicate_manifest_record_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    first = fixture["manifest"].records[0]
    entry = {
        "RECORD_ID": first.record_id,
        "STORE_RECORD_ID": first.store_record_id,
        "SOURCE_IDENTIFIER": first.source_identifier,
        "CONTENT_HASH": first.content_hash,
        "SOURCE_TYPE": "DEVELOPMENT_REPORT",
        "TRUTH_KIND": "AGENT_REPORTED",
        "AUTHORITY_SCOPE": "NONE",
        "ACCESS_SCOPE": "OPERATOR",
        "TRUST_CLASSIFICATION": "UNTRUSTED_KNOWLEDGE",
        "PROVENANCE_STATUS": "CONFIRMED",
        "IMPORT_ELIGIBILITY": "ELIGIBLE_CANDIDATE_PENDING_G12",
    }
    payload = _manifest_payload([entry, dict(entry)])
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.parse_candidate_manifest(payload, sha256="a" * 64)
    assert exc.value.code == "MANIFEST_DUPLICATE_RECORD_ID"


def test_production_store_guard_is_preserved_and_production_target_inspected():
    with pytest.raises(ReadinessError) as exc:
        assert_temporary_store(PRODUCTION_STORE_PATH)
    assert exc.value.code == "PRODUCTION_STORE_REJECTED"

    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.isolated_target_guard(PRODUCTION_STORE_PATH)
    assert exc.value.code == "PRODUCTION_STORE_REJECTED"

    before = _hash(PRODUCTION_STORE_PATH)
    guard = ingest.production_target_guard()
    assert guard.environment == ingest.PRODUCTION_ENVIRONMENT
    assert Path(guard.identity.resolved_path) == PRODUCTION_STORE_PATH.resolve()
    assert guard.identity.schema_version == 1
    assert guard.identity.integrity == "OK"
    assert guard.identity.exists is True
    assert _hash(PRODUCTION_STORE_PATH) == before


def test_backup_is_production_only(tmp_path):
    fixture = _fixture(tmp_path)
    guard = ingest.isolated_target_guard(fixture["store"])
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.create_pre_import_backup(guard, tmp_path / "backup.sqlite3")
    assert exc.value.code == "BACKUP_PRODUCTION_ONLY"


def test_production_authorization_cannot_target_isolated_guard(tmp_path):
    fixture = _fixture(tmp_path)
    production_auth = ingest.parse_authorization(
        _authorization_payload(
            fixture["manifest"],
            fixture["store"],
            state="ABSENT",
            sha=None,
            manifest_sha=fixture["manifest_sha"],
            environment=ingest.PRODUCTION_ENVIRONMENT,
        )
    )
    result = _run(fixture, production_auth)
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("AUTHORIZATION_ENVIRONMENT_MISMATCH",)
    assert not fixture["store"].exists()


def test_preview_never_creates_or_writes_store(tmp_path):
    fixture = _fixture(tmp_path)
    result = _run(fixture, _auth(fixture), apply=False)
    assert result.status == ingest.STATUS_PREVIEW
    assert result.inserted == 0
    assert not fixture["store"].exists()


@pytest.mark.skipif(
    not REAL_MANIFEST.is_file(), reason="real G12 candidate manifest is absent"
)
def test_real_g12_candidate_manifest_offline(tmp_path):
    manifest = ingest.load_candidate_manifest(REAL_MANIFEST)
    missing = [item.source_identifier for item in manifest.records if not Path(item.source_identifier).is_file()]
    if missing:
        pytest.skip("candidate source files are absent")
    store = tmp_path / "g12_isolated.sqlite3"
    payload = _authorization_payload(
        manifest,
        store,
        state="ABSENT",
        sha=None,
        manifest_sha=manifest.sha256,
        environment=ingest.ISOLATED_ENVIRONMENT,
        task_id="TRADINGAI-WORK-BC-G12-SAFE-IMPORT-PATH-1",
    )
    auth = ingest.parse_authorization(payload)
    guard = ingest.isolated_target_guard(store)
    result = ingest.run_authorized_import(
        guard,
        auth,
        manifest,
        indexed_at=AT.isoformat(),
        apply=True,
        audit_path=tmp_path / "g12_audit.json",
        now=AT,
    )
    assert result.status == ingest.STATUS_COMPLETE
    assert result.inserted == 3
    rows = _rows(store)
    assert {row["record_id"] for row in rows} == set(manifest.store_record_ids)
    assert {row["content_hash"] for row in rows} == set(manifest.content_hashes)
    assert {row["authority_scope"] for row in rows} == {"NONE"}
    assert {row["truth_kind"] for row in rows} == {"AGENT_REPORTED"}
    assert {row["metadata"]["record_approval_record_id"] for row in rows} == set(
        manifest.record_ids
    )


def test_unexpected_store_record_id_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    entries = []
    for candidate in fixture["manifest"].records:
        entries.append(
            {
                "RECORD_ID": candidate.record_id,
                "STORE_RECORD_ID": candidate.store_record_id,
                "SOURCE_IDENTIFIER": candidate.source_identifier,
                "CONTENT_HASH": candidate.content_hash,
                "SOURCE_TYPE": "DEVELOPMENT_REPORT",
                "TRUTH_KIND": "AGENT_REPORTED",
                "AUTHORITY_SCOPE": "NONE",
                "ACCESS_SCOPE": "OPERATOR",
                "TRUST_CLASSIFICATION": "UNTRUSTED_KNOWLEDGE",
                "PROVENANCE_STATUS": "CONFIRMED",
                "IMPORT_ELIGIBILITY": "ELIGIBLE_CANDIDATE_PENDING_G12",
            }
        )
    entries[0]["STORE_RECORD_ID"] = "f" * 64
    manifest_path, manifest_sha = _write_manifest(
        tmp_path, _manifest_payload(entries)
    )
    manifest = ingest.load_candidate_manifest(manifest_path)
    store = tmp_path / "wrong_id_store.sqlite3"
    auth = ingest.parse_authorization(
        _authorization_payload(
            manifest,
            store,
            state="ABSENT",
            sha=None,
            manifest_sha=manifest_sha,
        )
    )
    guard = ingest.isolated_target_guard(store)
    result = ingest.run_authorized_import(
        guard,
        auth,
        manifest,
        indexed_at=AT.isoformat(),
        apply=True,
        now=AT,
    )
    assert result.status == ingest.STATUS_BLOCKED
    assert result.errors == ("STORE_RECORD_ID_MISMATCH",)
    assert not store.exists()


def test_symlinked_store_is_rejected(tmp_path):
    target = tmp_path / "real.sqlite3"
    target.write_bytes(b"")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(target)
    with pytest.raises(ingest.ProductionIngestError) as exc:
        ingest.isolated_target_guard(link)
    assert exc.value.code == "STORE_SYMLINK_REJECTED"


def test_failure_audit_evidence_is_written(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    KnowledgeStore.create(fixture["store"]).close()
    auth = _auth(fixture, state="PRESENT", sha=_hash(fixture["store"]))

    def failing_upsert(self, item, **kwargs):
        raise StoreError("INJECTED_TRANSACTION_FAILURE")

    monkeypatch.setattr(KnowledgeStore, "upsert", failing_upsert)
    audit_path = tmp_path / "failure_audit.json"
    result = _run(fixture, auth, audit_path=audit_path)
    assert result.status == ingest.STATUS_BLOCKED
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["status"] == ingest.STATUS_BLOCKED
    assert payload["errors"] == ["INJECTED_TRANSACTION_FAILURE"]
    assert _count(fixture["store"]) == 0


def test_backup_integrity_on_isolated_fixture(tmp_path):
    fixture = _fixture(tmp_path)
    assert _run(fixture, _auth(fixture)).status == ingest.STATUS_COMPLETE
    identity = ingest.inspect_target(
        fixture["store"], environment=ingest.PRODUCTION_ENVIRONMENT
    )
    guard = ingest.TargetGuard(identity=identity, require_protection=True)
    backup = ingest.create_pre_import_backup(guard, tmp_path / "backup.sqlite3")
    assert backup.integrity == "OK"
    assert backup.record_count == 3
    assert backup.source_sha256 == identity.sha256
    assert Path(backup.path).is_file()
