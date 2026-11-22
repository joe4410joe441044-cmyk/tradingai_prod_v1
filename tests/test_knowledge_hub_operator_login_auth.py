"""Isolated acceptance for the Operator-login authorization migration.

Every write targets an isolated temporary Store or a temporary ledger/audit
directory. The Production Store is never written or mutated here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.api import create_operator_auth_router
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.csrf import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    OperatorCsrfProtection,
)
from backend.auth.operator_auth import OperatorAuthenticator, hash_operator_credential
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.knowledge_hub import production_ingest as ingest
from backend.knowledge_hub.import_readiness import PRODUCTION_STORE_PATH
from backend.knowledge_hub.knowledge_store import KnowledgeStore, StoreLimits, version_id
from backend.knowledge_hub.operator_authorization import ApprovalLedger
from backend.knowledge_hub.operator_ops import (
    KnowledgeHubOpsConfig,
    create_knowledge_hub_ops_router,
)
from backend.knowledge_hub.partial_import import _build_item, discover_records
from backend.knowledge_hub.reader import ReaderLimits, RequestContext, open_reader


SESSION_SECRET = "c" * 32
TEST_CREDENTIAL = "operator-login-migration-credential"
TEST_CREDENTIAL_HASH = hash_operator_credential(TEST_CREDENTIAL)
AT = datetime.fromisoformat("2026-11-22T00:00:00+00:00")

CSRF_PATHS = frozenset(
    {
        "/api/knowledge-hub/g12/approve",
        "/api/knowledge-hub/g12/import",
        "/api/knowledge-hub/sources",
    }
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_payload(records, *, target=None):
    return {
        "schema_version": ingest.CANDIDATE_MANIFEST_SCHEMA_VERSION,
        "task_id": "TRADINGAI-WORK-BC-OPERATOR-LOGIN-TEST",
        "original_task_id": "TRADINGAI-WORK-BC-OPERATOR-LOGIN-TEST",
        "g12_status": "PENDING_OPERATOR_AUTHORIZATION",
        "production_import_performed": False,
        "source_of_evidence": "isolated operator-login test fixture",
        "target_for_review": str(target or PRODUCTION_STORE_PATH),
        "record_count": len(records),
        "records": records,
    }


def _candidate_entry(record_id: str, path: Path):
    return {
        "RECORD_ID": record_id,
        "STORE_RECORD_ID": "",
        "SOURCE_IDENTIFIER": str(path.resolve()),
        "CONTENT_HASH": _hash(path),
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


def _fixture(tmp_path: Path):
    root = tmp_path / "sources"
    root.mkdir()
    texts = (
        "TASK_ID: LOGIN-A\nWORKSTREAM: BC\nVERDICT: PASS\n"
        "operatorloginmarker alpha\n",
        "TASK_ID: LOGIN-B\nWORKSTREAM: BC\nVERDICT: PASS\n"
        "operatorloginmarker beta\n",
        "TASK_ID: LOGIN-C\nWORKSTREAM: BC\nVERDICT: PASS\n"
        "operatorloginmarker gamma\n",
    )
    paths = []
    for index, text in enumerate(texts, start=1):
        path = root / f"report_{index}.md"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    entries = _finalize_store_ids(
        [
            _candidate_entry(f"xwsrc_login{index}", path)
            for index, path in enumerate(paths, start=1)
        ]
    )
    manifest_path, manifest_sha = _write_manifest(
        tmp_path, _manifest_payload(entries)
    )
    return {
        "root": root,
        "paths": paths,
        "entries": entries,
        "manifest_path": manifest_path,
        "manifest_sha": manifest_sha,
        "store": tmp_path / "isolated_store.sqlite3",
    }


class Harness:
    def __init__(
        self,
        fixture,
        tmp_path: Path,
        *,
        execution_enabled: bool = True,
        source_write_enabled: bool = True,
        expected_manifest_sha256: str | None = None,
        ttl_seconds: int = 300,
    ):
        self.fixture = fixture
        self.tmp_path = tmp_path
        self.now = [AT]
        self.audit_dir = tmp_path / "audit"
        self.backup_dir = tmp_path / "backup"
        self.ledger_path = tmp_path / "operator_approvals.json"
        self.ledger = ApprovalLedger(self.ledger_path)

        self.ops_config = KnowledgeHubOpsConfig(
            enabled=True,
            environment=ingest.ISOLATED_ENVIRONMENT,
            manifest_path=str(fixture["manifest_path"]),
            expected_manifest_sha256=expected_manifest_sha256,
            isolated_store_path=str(fixture["store"]),
            ledger_path=str(self.ledger_path),
            audit_dir=str(self.audit_dir),
            backup_dir=str(self.backup_dir),
            execution_enabled=execution_enabled,
            source_write_enabled=source_write_enabled,
            approval_ttl_seconds=ttl_seconds,
        )

        app = FastAPI()
        self.auth_config = OperatorAuthConfig(
            credential_hash=TEST_CREDENTIAL_HASH,
            session_secret=SESSION_SECRET,
            session_ttl_seconds=3600,
            secure_cookie=False,
            cookie_path="/",
            cookie_samesite="lax",
            auth_rate_limit=100,
            auth_rate_window_seconds=60,
        )
        self.manager = OperatorSessionManager(
            self.auth_config.session_secret,
            self.auth_config.session_ttl_seconds,
        )
        authenticator = OperatorAuthenticator(self.auth_config.credential_hash)
        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=self.manager,
            config=self.auth_config,
        )
        app.add_middleware(
            OperatorCsrfProtection,
            csrf_required_paths=CSRF_PATHS,
        )
        app.include_router(
            create_operator_auth_router(
                authenticator, self.manager, self.auth_config
            )
        )
        store_path = fixture["store"]
        app.include_router(
            create_knowledge_hub_ops_router(
                self.ops_config,
                ledger=self.ledger,
                guard_factory=lambda: ingest.isolated_target_guard(store_path),
                clock=lambda: self.now[0],
            )
        )
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)

    def login(self):
        response = self.client.post(
            "/api/auth/login", json={"credential": TEST_CREDENTIAL}
        )
        assert response.status_code == 200, response.text
        csrf = response.headers[CSRF_TOKEN_HEADER]
        return csrf

    def preview(self, csrf=None):
        return self.client.get("/api/knowledge-hub/g12/approval-request")

    def approve(self, csrf: str, *, request_id: str | None = None, **overrides):
        preview = self.preview().json()
        body = {
            "requestId": preview["request_id"],
            "manifestSha256": self.fixture["manifest_sha"],
            "approvedRecordIds": list(preview["approved_record_ids"]),
            "confirm": True,
        }
        if request_id is not None:
            body["requestId"] = request_id
        body.update(overrides)
        return self.client.post(
            "/api/knowledge-hub/g12/approve",
            json=body,
            headers={CSRF_TOKEN_HEADER: csrf},
        )

    def do_import(self, csrf: str, approval_id: str):
        return self.client.post(
            "/api/knowledge-hub/g12/import",
            json={"approvalId": approval_id},
            headers={CSRF_TOKEN_HEADER: csrf},
        )

    def approve_and_import(self, csrf: str):
        approved = self.approve(csrf)
        assert approved.status_code == 200, approved.text
        approval_id = approved.json()["approval_id"]
        return self.do_import(csrf, approval_id)


def _rows(store: Path):
    knowledge = KnowledgeStore.open(store, StoreLimits(max_results=100))
    try:
        return knowledge.list_records(limit=100)
    finally:
        knowledge.close()


def _audit_files(directory: Path):
    if not directory.exists():
        return []
    return sorted(directory.glob("KNOWLEDGE_OPS_*.json"))


def test_unauthenticated_and_forged_session_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    response = TestClient(harness.app, raise_server_exceptions=False).get(
        "/api/knowledge-hub/g12/approval-request"
    )
    assert response.status_code == 401
    forged = harness.client.get(
        "/api/knowledge-hub/g12/approval-request",
        cookies={COOKIE_NAME: "forged.invalidsignature"},
    )
    assert forged.status_code == 401


def test_csrf_required_for_mutation(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()
    preview = harness.preview().json()
    body = {
        "requestId": preview["request_id"],
        "manifestSha256": fixture["manifest_sha"],
        "approvedRecordIds": list(preview["approved_record_ids"]),
        "confirm": True,
    }
    missing = harness.client.post("/api/knowledge-hub/g12/approve", json=body)
    assert missing.status_code == 403
    wrong = harness.client.post(
        "/api/knowledge-hub/g12/approve",
        json=body,
        headers={CSRF_TOKEN_HEADER: "deadbeef" * 8},
    )
    assert wrong.status_code == 403


def test_preview_is_not_authorization_and_import_requires_approval(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()
    preview = harness.preview()
    assert preview.status_code == 200
    body = preview.json()
    assert body["status"] == "PREVIEW_ONLY"
    assert body["requires_explicit_approval"] is True
    assert set(body["approved_record_ids"]) == set(
        entry["RECORD_ID"] for entry in fixture["entries"]
    )
    assert harness.ledger.pending_count() == 0

    missing = harness.do_import(csrf, "0" * 32)
    assert missing.status_code == 409
    assert missing.json()["code"] == "APPROVAL_NOT_FOUND"
    assert not fixture["store"].exists()


def test_approval_requires_explicit_confirmation_and_exact_scope(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()

    unconfirmed = harness.approve(csrf, confirm=False)
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["code"] == "EXPLICIT_CONFIRMATION_REQUIRED"

    wrong_scope = harness.approve(
        csrf, approvedRecordIds=[fixture["entries"][0]["RECORD_ID"]]
    )
    assert wrong_scope.status_code == 409
    assert wrong_scope.json()["code"] == "APPROVAL_RECORD_SCOPE_MISMATCH"

    wrong_request = harness.approve(csrf, request_id="f" * 64)
    assert wrong_request.status_code == 409
    assert wrong_request.json()["code"] == "APPROVAL_REQUEST_ID_MISMATCH"


def test_valid_operator_approval_imports_exactly_three(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()
    response = harness.approve_and_import(csrf)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "COMPLETE"
    assert result["inserted"] == 3
    assert result["record_count_before"] in (None, 0)
    assert result["record_count_after"] == 3
    assert result["fts_count_after"] == 3
    assert result["integrity_after"] == "OK"
    assert result["applied"] is True

    rows = _rows(fixture["store"])
    assert len(rows) == 3
    assert {row["record_id"] for row in rows} == {
        entry["STORE_RECORD_ID"] for entry in fixture["entries"]
    }
    assert {row["content_hash"] for row in rows} == {
        entry["CONTENT_HASH"] for entry in fixture["entries"]
    }
    assert {row["authority_scope"] for row in rows} == {"NONE"}
    assert {row["truth_kind"] for row in rows} == {"AGENT_REPORTED"}

    from backend.knowledge_hub import production_ingest

    for role in ("ADVISOR", "SUPERVISOR"):
        probe = production_ingest.query_isolated_read(
            fixture["store"], "operatorloginmarker", role=role
        )
        assert probe["knowledge_status"] == "OK"
        assert probe["returned_count"] == 3
        assert probe["authority"] == "NONE"
        assert probe["trading_control"] == "FORBIDDEN"

    audits = _audit_files(harness.audit_dir)
    assert audits
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in audits]
    assert any(item.get("event") == "G12_APPROVED" for item in payloads)
    assert any(
        item.get("status") == "COMPLETE"
        and item.get("authorization_id") == result["authorization_id"]
        for item in payloads
    )


def test_replay_rejected_and_new_approval_is_idempotent(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()

    approved = harness.approve(csrf)
    assert approved.status_code == 200
    approval_id = approved.json()["approval_id"]
    first = harness.do_import(csrf, approval_id)
    assert first.status_code == 200

    replay = harness.do_import(csrf, approval_id)
    assert replay.status_code == 409
    assert replay.json()["code"] == "APPROVAL_REPLAY_REJECTED"

    again = harness.approve_and_import(csrf)
    assert again.status_code == 200
    body = again.json()
    assert body["status"] == "IDEMPOTENT"
    assert body["inserted"] == 0
    assert body["record_count_after"] == 3
    assert len(_rows(fixture["store"])) == 3


def test_expired_approval_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path, ttl_seconds=120)
    csrf = harness.login()
    approved = harness.approve(csrf)
    assert approved.status_code == 200
    approval_id = approved.json()["approval_id"]

    harness.now[0] = AT + timedelta(seconds=121)
    expired = harness.do_import(csrf, approval_id)
    assert expired.status_code == 409
    assert expired.json()["code"] == "APPROVAL_EXPIRED"
    assert not fixture["store"].exists()


def test_manifest_and_content_mismatch_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(
        fixture, tmp_path, expected_manifest_sha256=fixture["manifest_sha"]
    )
    csrf = harness.login()
    approved = harness.approve(csrf)
    assert approved.status_code == 200
    approval_id = approved.json()["approval_id"]

    tampered = json.loads(fixture["manifest_path"].read_text(encoding="utf-8"))
    tampered["task_id"] = "TAMPERED-AFTER-APPROVAL"
    fixture["manifest_path"].write_text(json.dumps(tampered), encoding="utf-8")
    mismatch = harness.do_import(csrf, approval_id)
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "MANIFEST_SHA256_PINNED_MISMATCH"
    assert not fixture["store"].exists()


def test_content_hash_change_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()
    approved = harness.approve(csrf)
    assert approved.status_code == 200
    approval_id = approved.json()["approval_id"]

    fixture["paths"][0].write_text(
        fixture["paths"][0].read_text(encoding="utf-8") + "changed\n",
        encoding="utf-8",
    )
    blocked = harness.do_import(csrf, approval_id)
    assert blocked.status_code == 409
    assert blocked.json()["status"] == "BLOCKED"
    assert blocked.json()["inserted"] == 0
    if fixture["store"].exists():
        assert len(_rows(fixture["store"])) == 0


def test_store_state_change_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()
    approved = harness.approve(csrf)
    assert approved.status_code == 200
    approval_id = approved.json()["approval_id"]

    KnowledgeStore.create(fixture["store"]).close()
    mismatch = harness.do_import(csrf, approval_id)
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "APPROVAL_STORE_STATE_MISMATCH"


def test_execution_disabled_never_imports(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path, execution_enabled=False)
    csrf = harness.login()
    approved = harness.approve(csrf)
    assert approved.status_code == 200
    disabled = harness.do_import(csrf, approved.json()["approval_id"])
    assert disabled.status_code == 409
    assert disabled.json()["code"] == "EXECUTION_DISABLED"
    assert not fixture["store"].exists()


def test_source_registration_auth_csrf_hash_duplicate_revision(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path)
    csrf = harness.login()
    payload = {
        "sourceType": "OPERATOR_REPORT",
        "sourceIdentifier": "operator/report/alpha.md",
        "title": "Alpha operator report",
        "content": "operatorloginmarker alpha content",
        "contentHash": hashlib.sha256(
            b"operatorloginmarker alpha content"
        ).hexdigest(),
        "truthKind": "AGENT_REPORTED",
    }
    created = harness.client.post(
        "/api/knowledge-hub/sources",
        json=payload,
        headers={CSRF_TOKEN_HEADER: csrf},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "INSERTED"
    assert body["duplicate"] is False

    duplicate = harness.client.post(
        "/api/knowledge-hub/sources",
        json=payload,
        headers={CSRF_TOKEN_HEADER: csrf},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    revised_payload = {
        **payload,
        "content": "operatorloginmarker alpha revised",
        "contentHash": hashlib.sha256(
            b"operatorloginmarker alpha revised"
        ).hexdigest(),
    }
    revised = harness.client.post(
        "/api/knowledge-hub/sources",
        json=revised_payload,
        headers={CSRF_TOKEN_HEADER: csrf},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["status"] == "SUPERSEDED"
    assert body["record_id"] in revised.json()["revision_of"]

    bad_hash = harness.client.post(
        "/api/knowledge-hub/sources",
        json={**payload, "contentHash": "0" * 64},
        headers={CSRF_TOKEN_HEADER: csrf},
    )
    assert bad_hash.status_code == 400
    assert bad_hash.json()["code"] == "CONTENT_HASH_MISMATCH"

    rows = _rows(fixture["store"])
    current = [row for row in rows if row["presence"] == "CURRENT"]
    assert len(current) == 1
    assert current[0]["content"] == "operatorloginmarker alpha revised"
    assert any(item["event"] == "SOURCE_WRITE" for item in (
        json.loads(path.read_text(encoding="utf-8"))
        for path in _audit_files(harness.audit_dir)
    ))


def test_source_write_disabled_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    harness = Harness(fixture, tmp_path, source_write_enabled=False)
    csrf = harness.login()
    payload = {
        "sourceType": "OPERATOR_REPORT",
        "sourceIdentifier": "operator/report/beta.md",
        "title": "Beta operator report",
        "content": "operatorloginmarker beta content",
    }
    response = harness.client.post(
        "/api/knowledge-hub/sources",
        json=payload,
        headers={CSRF_TOKEN_HEADER: csrf},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_WRITE_DISABLED"
