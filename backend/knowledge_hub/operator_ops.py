"""Operator-authenticated Knowledge Hub maintenance API.

All mutating routes require the existing TradingAI Operator session and the
CSRF double-submit token, then an explicit request body. Import never runs just
because an operator is logged in: a separate preview + approve step produces a
single-use approval id that the import route consumes.

Configuration is environment-driven and disabled by default so that merely
registering this router changes no Production behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import secrets
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.dependencies import (
    require_csrf,
    require_operator_session_context,
)
from . import production_ingest as ingest
from .knowledge_store import KnowledgeStore, StoreItem, logical_key, version_id
from .operator_authorization import (
    ApprovalLedger,
    OperatorApprovalError,
    build_approval_request,
    run_operator_authorized_import,
)


PRODUCTION_ENVIRONMENT = ingest.PRODUCTION_ENVIRONMENT
ISOLATED_ENVIRONMENT = ingest.ISOLATED_ENVIRONMENT
DEFAULT_MANIFEST_PATH = "/tmp/work_bc_audit/BC_G12_IMPORT_CANDIDATE_MANIFEST.json"
DEFAULT_LEDGER_PATH = "/tmp/work_bc_audit/BC_G12_OPERATOR_APPROVALS.json"
DEFAULT_WORK_DIR = "/tmp/work_bc_audit"
ROUTER_PREFIX = "/api/knowledge-hub"


@dataclass(frozen=True)
class KnowledgeHubOpsConfig:
    enabled: bool = False
    environment: str = PRODUCTION_ENVIRONMENT
    manifest_path: str = DEFAULT_MANIFEST_PATH
    expected_manifest_sha256: str | None = None
    isolated_store_path: str | None = None
    ledger_path: str = DEFAULT_LEDGER_PATH
    audit_dir: str = DEFAULT_WORK_DIR
    backup_dir: str = DEFAULT_WORK_DIR
    execution_enabled: bool = False
    source_write_enabled: bool = False
    approval_ttl_seconds: int = 900


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def load_knowledge_hub_ops_config() -> KnowledgeHubOpsConfig:
    environment = os.environ.get(
        "TRADINGAI_KNOWLEDGE_OPS_ENVIRONMENT", PRODUCTION_ENVIRONMENT
    ).strip().upper()
    if environment not in {PRODUCTION_ENVIRONMENT, ISOLATED_ENVIRONMENT}:
        environment = PRODUCTION_ENVIRONMENT
    ttl_raw = os.environ.get("TRADINGAI_KNOWLEDGE_OPS_APPROVAL_TTL_SECONDS", "900")
    try:
        ttl = int(ttl_raw)
    except ValueError:
        ttl = 900
    expected = os.environ.get("TRADINGAI_G12_MANIFEST_SHA256")
    return KnowledgeHubOpsConfig(
        enabled=_env_bool("TRADINGAI_KNOWLEDGE_OPS_ENABLED", False),
        environment=environment,
        manifest_path=os.environ.get(
            "TRADINGAI_G12_MANIFEST_PATH", DEFAULT_MANIFEST_PATH
        ),
        expected_manifest_sha256=expected.strip().lower() if expected else None,
        isolated_store_path=os.environ.get("TRADINGAI_KNOWLEDGE_OPS_STORE"),
        ledger_path=os.environ.get(
            "TRADINGAI_KNOWLEDGE_OPS_LEDGER", DEFAULT_LEDGER_PATH
        ),
        audit_dir=os.environ.get(
            "TRADINGAI_KNOWLEDGE_OPS_AUDIT_DIR", DEFAULT_WORK_DIR
        ),
        backup_dir=os.environ.get(
            "TRADINGAI_KNOWLEDGE_OPS_BACKUP_DIR", DEFAULT_WORK_DIR
        ),
        execution_enabled=_env_bool(
            "TRADINGAI_KNOWLEDGE_OPS_EXECUTION_ENABLED", False
        ),
        source_write_enabled=_env_bool(
            "TRADINGAI_KNOWLEDGE_OPS_SOURCE_WRITE_ENABLED", False
        ),
        approval_ttl_seconds=ttl,
    )


class G12ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=16, max_length=128)
    manifestSha256: str = Field(min_length=64, max_length=64)
    approvedRecordIds: list[str]
    confirm: bool = False


class G12ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approvalId: str = Field(min_length=16, max_length=128)


class SourceRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sourceType: str = Field(min_length=1, max_length=64)
    sourceIdentifier: str = Field(min_length=1, max_length=2048)
    recordType: str = Field(default="OPERATOR_SOURCE", min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    truthKind: str = "UNKNOWN"
    workstream: str | None = None
    collectedAt: str | None = None
    contentHash: str | None = None
    decisionRecordId: str | None = None


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "REJECTED", "code": code})


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _audit_path(config: KnowledgeHubOpsConfig, event: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    token = secrets.token_hex(4)
    return Path(config.audit_dir) / f"KNOWLEDGE_OPS_{event}_{stamp}_{token}.json"


def _write_audit(config: KnowledgeHubOpsConfig, event: str, payload: dict[str, Any]) -> None:
    try:
        ingest.write_audit_evidence(
            _audit_path(config, event),
            {
                "schema_version": "tradingai-knowledge-ops-audit/v1",
                "event": event,
                "recorded_at": _iso(datetime.now(timezone.utc)),
                **payload,
            },
        )
    except ingest.ProductionIngestError:
        pass


def create_knowledge_hub_ops_router(
    config: KnowledgeHubOpsConfig | None = None,
    *,
    ledger: ApprovalLedger | None = None,
    guard_factory: Callable[[], ingest.TargetGuard] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    config = config or load_knowledge_hub_ops_config()
    ledger = ledger or ApprovalLedger(config.ledger_path)
    now_fn = clock or (lambda: datetime.now(timezone.utc))

    def guard() -> ingest.TargetGuard:
        if guard_factory is not None:
            return guard_factory()
        if config.environment == ISOLATED_ENVIRONMENT:
            if not config.isolated_store_path:
                raise OperatorApprovalError("OPS_STORE_NOT_CONFIGURED")
            return ingest.isolated_target_guard(config.isolated_store_path)
        return ingest.production_target_guard()

    def manifest() -> ingest.CandidateManifest:
        loaded = ingest.load_candidate_manifest(config.manifest_path)
        if (
            config.expected_manifest_sha256
            and loaded.sha256 != config.expected_manifest_sha256
        ):
            raise OperatorApprovalError("MANIFEST_SHA256_PINNED_MISMATCH")
        return loaded

    router = APIRouter(prefix=ROUTER_PREFIX, tags=["knowledge-hub-ops"])

    @router.get("/g12/approval-request")
    def approval_request(
        request: Request,
        session: dict[str, Any] = Depends(require_operator_session_context),
    ):
        try:
            current_manifest = manifest()
            current_guard = guard()
            preview = build_approval_request(
                guard=current_guard,
                manifest=current_manifest,
                operator_identity=session["identity"],
                session_id=session["session_id"],
                now=now_fn(),
                ttl_seconds=config.approval_ttl_seconds,
            )
        except (OperatorApprovalError, ingest.ProductionIngestError) as exc:
            return _error(409, getattr(exc, "code", "APPROVAL_PREVIEW_FAILED"))
        return {
            "status": "PREVIEW_ONLY",
            "requires_explicit_approval": True,
            **preview.to_dict(),
        }

    @router.post("/g12/approve")
    def approve_g12(
        body: G12ApproveRequest,
        session: dict[str, Any] = Depends(require_operator_session_context),
        _csrf: None = Depends(require_csrf),
    ):
        if body.confirm is not True:
            return _error(400, "EXPLICIT_CONFIRMATION_REQUIRED")
        try:
            current_manifest = manifest()
            current_guard = guard()
            preview = build_approval_request(
                guard=current_guard,
                manifest=current_manifest,
                operator_identity=session["identity"],
                session_id=session["session_id"],
                now=now_fn(),
                ttl_seconds=config.approval_ttl_seconds,
            )
            if body.requestId != preview.request_id:
                return _error(409, "APPROVAL_REQUEST_ID_MISMATCH")
            if body.manifestSha256 != current_manifest.sha256:
                return _error(409, "APPROVAL_MANIFEST_HASH_MISMATCH")
            if set(body.approvedRecordIds) != set(current_manifest.record_ids):
                return _error(409, "APPROVAL_RECORD_SCOPE_MISMATCH")
            approval = ledger.create(preview, now=now_fn())
        except (OperatorApprovalError, ingest.ProductionIngestError) as exc:
            return _error(409, getattr(exc, "code", "APPROVAL_FAILED"))
        _write_audit(
            config,
            "G12_APPROVED",
            {
                "operator_identity": session["identity"],
                "approval_id": approval.approval_id,
                "manifest_sha256": approval.manifest_sha256,
                "target_store": approval.target_store,
                "target_store_sha256": approval.target_store_sha256,
                "approved_record_ids": list(approval.approved_record_ids),
            },
        )
        return {
            "status": "APPROVED_NOT_EXECUTED",
            "authorization_mode": approval.authorization_mode,
            "approval_id": approval.approval_id,
            "request_id": approval.request_id,
            "manifest_sha256": approval.manifest_sha256,
            "expires_at": approval.expires_at,
            "single_use": True,
        }

    @router.post("/g12/import")
    def import_g12(
        body: G12ImportRequest,
        session: dict[str, Any] = Depends(require_operator_session_context),
        _csrf: None = Depends(require_csrf),
    ):
        if not config.execution_enabled:
            return _error(409, "EXECUTION_DISABLED")
        try:
            current_manifest = manifest()
            current_guard = guard()
            backup_path = None
            if current_guard.environment == PRODUCTION_ENVIRONMENT:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup_path = (
                    Path(config.backup_dir)
                    / f"BC_G12_OPERATOR_LOGIN_PREIMPORT_BACKUP_{stamp}.sqlite3"
                )
            audit_path = _audit_path(config, "G12_IMPORT")
            result = run_operator_authorized_import(
                ledger=ledger,
                approval_id=body.approvalId,
                operator_identity=session["identity"],
                session_id=session["session_id"],
                guard=current_guard,
                manifest=current_manifest,
                indexed_at=_iso(now_fn()),
                apply=True,
                backup_path=backup_path,
                audit_path=audit_path,
                now=now_fn(),
            )
        except (OperatorApprovalError, ingest.ProductionIngestError) as exc:
            return _error(409, getattr(exc, "code", "IMPORT_FAILED"))
        status_code = 200 if result.status in {
            ingest.STATUS_COMPLETE,
            ingest.STATUS_IDEMPOTENT,
        } else 409
        return JSONResponse(status_code=status_code, content=result.to_dict())

    @router.get("/g12/status")
    def g12_status(
        session: dict[str, Any] = Depends(require_operator_session_context),
    ):
        try:
            current_manifest = manifest()
            current_guard = guard()
        except (OperatorApprovalError, ingest.ProductionIngestError) as exc:
            return _error(409, getattr(exc, "code", "STATUS_UNAVAILABLE"))
        identity = current_guard.identity
        return {
            "status": "READY_FOR_OPERATOR_APPROVAL" if config.execution_enabled else "PREVIEW",
            "operator_identity": session["identity"],
            "authorization_mode": "EXISTING_OPERATOR_LOGIN",
            "environment": current_guard.environment,
            "manifest_sha256": current_manifest.sha256,
            "record_ids": list(current_manifest.record_ids),
            "target_store": identity.resolved_path,
            "target_store_state": (
                ingest.STORE_STATE_PRESENT if identity.exists else ingest.STORE_STATE_ABSENT
            ),
            "target_store_sha256": identity.sha256,
            "record_count": identity.record_count,
            "fts_count": identity.fts_count,
            "integrity": identity.integrity,
            "execution_enabled": config.execution_enabled,
            "pending_approvals": ledger.pending_count(),
        }

    def _store_path(current_guard: ingest.TargetGuard) -> Path:
        if current_guard.environment == ISOLATED_ENVIRONMENT:
            if not config.isolated_store_path:
                raise OperatorApprovalError("OPS_STORE_NOT_CONFIGURED")
            return Path(config.isolated_store_path)
        return Path(current_guard.identity.resolved_path)

    def _register(
        body: SourceRegistrationRequest,
        *,
        operator_identity: str,
        expected_record_id: str | None = None,
    ) -> JSONResponse:
        if not config.source_write_enabled:
            return _error(409, "SOURCE_WRITE_DISABLED")
        digest = hashlib.sha256(body.content.encode("utf-8")).hexdigest()
        if body.contentHash is not None and body.contentHash.lower() != digest:
            return _error(400, "CONTENT_HASH_MISMATCH")
        try:
            current_guard = guard()
        except (OperatorApprovalError, ingest.ProductionIngestError) as exc:
            return _error(409, getattr(exc, "code", "OPS_STORE_UNAVAILABLE"))
        store_path = _store_path(current_guard)
        collected_at = body.collectedAt or _iso(now_fn())
        item = StoreItem(
            source_type=body.sourceType,
            source_identifier=body.sourceIdentifier,
            record_type=body.recordType,
            title=body.title[:300],
            content=body.content,
            collected_at=collected_at,
            verification_state="OPERATOR_SUBMITTED",
            truth_kind=body.truthKind,
            content_hash=digest,
            workstream=body.workstream,
            metadata={
                "access_scope": "OPERATOR",
                "trust": "UNTRUSTED_KNOWLEDGE",
                "runtime_truth": "NOT_ASSERTED",
                "historical_authority": "UNTRUSTED_HISTORICAL",
                "submitted_by": operator_identity,
                "decision_record_id": body.decisionRecordId or "",
                "authorization_mode": "EXISTING_OPERATOR_LOGIN",
            },
        )
        record_id = version_id(item, digest)
        try:
            if store_path.exists():
                store = KnowledgeStore.open(store_path)
            else:
                store = KnowledgeStore.create(store_path)
        except Exception as exc:  # StoreError / sqlite3.Error / OSError
            return _error(409, getattr(exc, "code", "STORE_OPEN_FAILED"))
        try:
            if expected_record_id is not None:
                existing = store.get_record(expected_record_id)
                if existing is None:
                    return _error(404, "SOURCE_NOT_FOUND")
                if existing["source_identifier"] != body.sourceIdentifier:
                    return _error(409, "SOURCE_IDENTIFIER_MISMATCH")
            key = logical_key(item)
            current = [
                row
                for row in store.records_for_logical_key(key)
                if row.get("presence") == "CURRENT"
            ]
            duplicate = any(row["content_hash"] == digest for row in current)
            state = store.upsert(
                item,
                indexed_at=_iso(now_fn()),
                scan_scope="operator-login-registration",
            )
            store.integrity_check()
            stored = store.get_record(record_id)
        except Exception as exc:  # StoreError / sqlite3.Error / OSError
            return _error(409, getattr(exc, "code", "SOURCE_WRITE_FAILED"))
        finally:
            store.close()
        supersedes = [
            row["record_id"]
            for row in current
            if row["record_id"] != record_id
        ]
        result = {
            "status": "DUPLICATE" if duplicate else state,
            "record_id": record_id,
            "content_hash": digest,
            "duplicate": duplicate,
            "revision_of": supersedes,
            "source_identifier": body.sourceIdentifier,
            "authorization_mode": "EXISTING_OPERATOR_LOGIN",
            "stored": stored is not None,
        }
        _write_audit(
            config,
            "SOURCE_WRITE",
            {
                "operator_identity": operator_identity,
                "record_id": record_id,
                "source_identifier": body.sourceIdentifier,
                "content_hash": digest,
                "outcome": result["status"],
                "duplicate": duplicate,
                "store_environment": current_guard.environment,
            },
        )
        return JSONResponse(status_code=200, content=result)

    @router.post("/sources")
    def register_source(
        body: SourceRegistrationRequest,
        session: dict[str, Any] = Depends(require_operator_session_context),
        _csrf: None = Depends(require_csrf),
    ):
        return _register(body, operator_identity=session["identity"])

    @router.put("/sources/{record_id}")
    def update_source(
        record_id: str,
        body: SourceRegistrationRequest,
        session: dict[str, Any] = Depends(require_operator_session_context),
        _csrf: None = Depends(require_csrf),
    ):
        return _register(
            body,
            operator_identity=session["identity"],
            expected_record_id=record_id,
        )

    return router
