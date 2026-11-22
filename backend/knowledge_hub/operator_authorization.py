"""Operator-login authorization for Knowledge Hub maintenance operations.

This module adds ``AUTHORIZATION_MODE=EXISTING_OPERATOR_LOGIN`` on top of the
existing TradingAI Operator authentication (pbkdf2 login, signed session
cookie, CSRF double-submit). The legacy operator-held HMAC path in
:mod:`backend.knowledge_hub.production_ingest` is kept intact and is not
weakened or removed; this is a separate, explicit mode.

Operator login alone never imports. An authenticated, CSRF-validated operator
must first request a preview, then explicitly approve the exact request, and
finally import using the returned single-use ``approval_id``. Approvals are
bound to the operator session, the pinned manifest hash, the target Store
identity, the exact record allowlist, and an expiry. Replay is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Mapping

from . import production_ingest as ingest


AUTHORIZATION_MODE = "EXISTING_OPERATOR_LOGIN"
OPERATOR_APPROVAL_SCHEMA_VERSION = "tradingai-g12-operator-approval/v1"
OPERATOR_APPROVAL_LEDGER_SCHEMA_VERSION = (
    "tradingai-g12-operator-approval-ledger/v1"
)
APPROVAL_STATUS_PENDING = "PENDING"
APPROVAL_STATUS_CONSUMED = "CONSUMED"
APPROVAL_STATUS_REVOKED = "REVOKED"
DEFAULT_APPROVAL_TTL_SECONDS = 900
MIN_APPROVAL_TTL_SECONDS = 60


class OperatorApprovalError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise OperatorApprovalError("APPROVAL_TIME_INVALID")
    return moment.astimezone(timezone.utc).isoformat()


def _parse(value: str, code: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise OperatorApprovalError(code) from None
    if moment.tzinfo is None:
        raise OperatorApprovalError(code)
    return moment.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _session_binding(session_id: str) -> str:
    """Hash the server session id so the ledger never stores the raw value."""
    return hashlib.sha256(
        ("tradingai-operator-session:" + str(session_id)).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ApprovalRequest:
    schema_version: str
    authorization_mode: str
    request_id: str
    operator_identity: str
    session_id: str
    environment: str
    target_store: str
    target_store_state: str
    target_store_sha256: str | None
    manifest_sha256: str
    approved_record_ids: tuple[str, ...]
    approved_content_hashes: tuple[str, ...]
    approved_store_record_ids: tuple[str, ...]
    approved_operation: str
    created_at: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_mode": self.authorization_mode,
            "request_id": self.request_id,
            "operator_identity": self.operator_identity,
            "environment": self.environment,
            "target_store": self.target_store,
            "target_store_state": self.target_store_state,
            "target_store_sha256": self.target_store_sha256,
            "manifest_sha256": self.manifest_sha256,
            "approved_record_ids": list(self.approved_record_ids),
            "approved_content_hashes": list(self.approved_content_hashes),
            "approved_store_record_ids": list(self.approved_store_record_ids),
            "approved_operation": self.approved_operation,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


def _request_id(fields: Mapping[str, Any]) -> str:
    body = {
        "environment": fields["environment"],
        "target_store": fields["target_store"],
        "target_store_state": fields["target_store_state"],
        "target_store_sha256": fields["target_store_sha256"],
        "manifest_sha256": fields["manifest_sha256"],
        "approved_record_ids": list(fields["approved_record_ids"]),
        "approved_content_hashes": list(fields["approved_content_hashes"]),
        "approved_store_record_ids": list(fields["approved_store_record_ids"]),
        "approved_operation": fields["approved_operation"],
    }
    return hashlib.sha256(_canonical(body)).hexdigest()


def build_approval_request(
    *,
    guard: ingest.TargetGuard,
    manifest: ingest.CandidateManifest,
    operator_identity: str,
    session_id: str,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_APPROVAL_TTL_SECONDS,
) -> ApprovalRequest:
    """Read-only preview. It approves nothing and writes nothing."""

    if not operator_identity or not session_id:
        raise OperatorApprovalError("OPERATOR_SESSION_REQUIRED")
    if ttl_seconds < MIN_APPROVAL_TTL_SECONDS:
        raise OperatorApprovalError("APPROVAL_TTL_INVALID")
    moment = now or _now_utc()
    identity = guard.identity
    fields = {
        "environment": guard.environment,
        "target_store": identity.resolved_path,
        "target_store_state": (
            ingest.STORE_STATE_PRESENT if identity.exists else ingest.STORE_STATE_ABSENT
        ),
        "target_store_sha256": identity.sha256 if identity.exists else None,
        "manifest_sha256": manifest.sha256,
        "approved_record_ids": tuple(manifest.record_ids),
        "approved_content_hashes": tuple(manifest.content_hashes),
        "approved_store_record_ids": tuple(manifest.store_record_ids),
        "approved_operation": ingest.G12_OPERATION,
    }
    return ApprovalRequest(
        schema_version=OPERATOR_APPROVAL_SCHEMA_VERSION,
        authorization_mode=AUTHORIZATION_MODE,
        request_id=_request_id(fields),
        operator_identity=operator_identity,
        session_id=session_id,
        environment=fields["environment"],
        target_store=fields["target_store"],
        target_store_state=fields["target_store_state"],
        target_store_sha256=fields["target_store_sha256"],
        manifest_sha256=fields["manifest_sha256"],
        approved_record_ids=fields["approved_record_ids"],
        approved_content_hashes=fields["approved_content_hashes"],
        approved_store_record_ids=fields["approved_store_record_ids"],
        approved_operation=fields["approved_operation"],
        created_at=_iso(moment),
        expires_at=_iso(moment + timedelta(seconds=ttl_seconds)),
    )


@dataclass(frozen=True)
class ApprovalRecord:
    schema_version: str
    authorization_mode: str
    approval_id: str
    request_id: str
    operator_identity: str
    session_binding: str
    environment: str
    target_store: str
    target_store_state: str
    target_store_sha256: str | None
    manifest_sha256: str
    approved_record_ids: tuple[str, ...]
    approved_content_hashes: tuple[str, ...]
    approved_store_record_ids: tuple[str, ...]
    approved_operation: str
    approval_time: str
    expires_at: str
    status: str
    single_use: bool
    authorized: bool
    consumed_at: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApprovalRecord":
        return cls(
            schema_version=str(payload["schema_version"]),
            authorization_mode=str(payload["authorization_mode"]),
            approval_id=str(payload["approval_id"]),
            request_id=str(payload["request_id"]),
            operator_identity=str(payload["operator_identity"]),
            session_binding=str(payload["session_binding"]),
            environment=str(payload["environment"]),
            target_store=str(payload["target_store"]),
            target_store_state=str(payload["target_store_state"]),
            target_store_sha256=payload.get("target_store_sha256"),
            manifest_sha256=str(payload["manifest_sha256"]),
            approved_record_ids=tuple(payload["approved_record_ids"]),
            approved_content_hashes=tuple(payload["approved_content_hashes"]),
            approved_store_record_ids=tuple(payload["approved_store_record_ids"]),
            approved_operation=str(payload["approved_operation"]),
            approval_time=str(payload["approval_time"]),
            expires_at=str(payload["expires_at"]),
            status=str(payload["status"]),
            single_use=bool(payload["single_use"]),
            authorized=bool(payload["authorized"]),
            consumed_at=payload.get("consumed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_mode": self.authorization_mode,
            "approval_id": self.approval_id,
            "request_id": self.request_id,
            "operator_identity": self.operator_identity,
            "session_binding": self.session_binding,
            "environment": self.environment,
            "target_store": self.target_store,
            "target_store_state": self.target_store_state,
            "target_store_sha256": self.target_store_sha256,
            "manifest_sha256": self.manifest_sha256,
            "approved_record_ids": list(self.approved_record_ids),
            "approved_content_hashes": list(self.approved_content_hashes),
            "approved_store_record_ids": list(self.approved_store_record_ids),
            "approved_operation": self.approved_operation,
            "approval_time": self.approval_time,
            "expires_at": self.expires_at,
            "status": self.status,
            "single_use": self.single_use,
            "authorized": self.authorized,
            "consumed_at": self.consumed_at,
        }


class ApprovalLedger:
    """File-backed, single-use approval ledger with atomic transitions."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._thread_lock = threading.RLock()

    class _Lock:
        def __init__(self, owner: "ApprovalLedger") -> None:
            self._owner = owner
            self._handle = None

        def __enter__(self):
            self._owner._path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self._owner._path.with_suffix(
                self._owner._path.suffix + ".lock"
            )
            self._handle = open(lock_path, "a+", encoding="utf-8")
            self._owner._thread_lock.acquire()
            try:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            return self

        def __exit__(self, *_exc):
            try:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
            finally:
                self._owner._thread_lock.release()
                self._handle.close()

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {
                "schema_version": OPERATOR_APPROVAL_LEDGER_SCHEMA_VERSION,
                "approvals": {},
            }
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise OperatorApprovalError("APPROVAL_LEDGER_INVALID") from None
        if not isinstance(payload, dict) or not isinstance(
            payload.get("approvals"), dict
        ):
            raise OperatorApprovalError("APPROVAL_LEDGER_INVALID")
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        temp = self._path.with_suffix(self._path.suffix + f".{os.getpid()}.tmp")
        temp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, self._path)

    def create(
        self,
        request: ApprovalRequest,
        *,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        moment = now or _now_utc()
        if moment > _parse(request.expires_at, "APPROVAL_EXPIRY_INVALID"):
            raise OperatorApprovalError("APPROVAL_REQUEST_EXPIRED")
        record = ApprovalRecord(
            schema_version=OPERATOR_APPROVAL_SCHEMA_VERSION,
            authorization_mode=AUTHORIZATION_MODE,
            approval_id=secrets.token_hex(16),
            request_id=request.request_id,
            operator_identity=request.operator_identity,
            session_binding=_session_binding(request.session_id),
            environment=request.environment,
            target_store=request.target_store,
            target_store_state=request.target_store_state,
            target_store_sha256=request.target_store_sha256,
            manifest_sha256=request.manifest_sha256,
            approved_record_ids=request.approved_record_ids,
            approved_content_hashes=request.approved_content_hashes,
            approved_store_record_ids=request.approved_store_record_ids,
            approved_operation=request.approved_operation,
            approval_time=_iso(moment),
            expires_at=request.expires_at,
            status=APPROVAL_STATUS_PENDING,
            single_use=True,
            authorized=True,
        )
        with self._Lock(self):
            payload = self._read()
            payload["approvals"][record.approval_id] = record.to_dict()
            self._write(payload)
        return record

    def get(self, approval_id: str) -> ApprovalRecord:
        with self._Lock(self):
            payload = self._read()
            raw = payload["approvals"].get(approval_id)
        if raw is None:
            raise OperatorApprovalError("APPROVAL_NOT_FOUND")
        return ApprovalRecord.from_dict(raw)

    def consume(
        self, approval_id: str, *, now: datetime | None = None
    ) -> ApprovalRecord:
        moment = now or _now_utc()
        with self._Lock(self):
            payload = self._read()
            raw = payload["approvals"].get(approval_id)
            if raw is None:
                raise OperatorApprovalError("APPROVAL_NOT_FOUND")
            record = ApprovalRecord.from_dict(raw)
            if record.status == APPROVAL_STATUS_CONSUMED:
                raise OperatorApprovalError("APPROVAL_REPLAY_REJECTED")
            if record.status != APPROVAL_STATUS_PENDING:
                raise OperatorApprovalError("APPROVAL_NOT_PENDING")
            if moment > _parse(record.expires_at, "APPROVAL_EXPIRY_INVALID"):
                raise OperatorApprovalError("APPROVAL_EXPIRED")
            updated = ApprovalRecord(
                **{
                    **record.to_dict(),
                    "approved_record_ids": record.approved_record_ids,
                    "approved_content_hashes": record.approved_content_hashes,
                    "approved_store_record_ids": record.approved_store_record_ids,
                    "status": APPROVAL_STATUS_CONSUMED,
                    "consumed_at": _iso(moment),
                }
            )
            payload["approvals"][approval_id] = updated.to_dict()
            self._write(payload)
        return updated

    def revoke(self, approval_id: str) -> ApprovalRecord:
        with self._Lock(self):
            payload = self._read()
            raw = payload["approvals"].get(approval_id)
            if raw is None:
                raise OperatorApprovalError("APPROVAL_NOT_FOUND")
            record = ApprovalRecord.from_dict(raw)
            payload["approvals"][approval_id] = {
                **record.to_dict(),
                "status": APPROVAL_STATUS_REVOKED,
            }
            self._write(payload)
        return ApprovalRecord.from_dict(payload["approvals"][approval_id])

    def pending_count(self) -> int:
        with self._Lock(self):
            payload = self._read()
        return sum(
            1
            for item in payload["approvals"].values()
            if item.get("status") == APPROVAL_STATUS_PENDING
        )


def verify_approval_binding(
    record: ApprovalRecord,
    *,
    operator_identity: str,
    session_id: str,
    guard: ingest.TargetGuard,
    manifest: ingest.CandidateManifest,
    now: datetime | None = None,
) -> None:
    """Fail closed unless the approval matches the live operator and target."""

    moment = now or _now_utc()
    if record.schema_version != OPERATOR_APPROVAL_SCHEMA_VERSION:
        raise OperatorApprovalError("APPROVAL_SCHEMA_MISMATCH")
    if record.authorization_mode != AUTHORIZATION_MODE:
        raise OperatorApprovalError("APPROVAL_MODE_MISMATCH")
    if record.authorized is not True:
        raise OperatorApprovalError("APPROVAL_NOT_GRANTED")
    if not record.single_use:
        raise OperatorApprovalError("APPROVAL_NOT_SINGLE_USE")
    if record.status == APPROVAL_STATUS_CONSUMED:
        raise OperatorApprovalError("APPROVAL_REPLAY_REJECTED")
    if record.status != APPROVAL_STATUS_PENDING:
        raise OperatorApprovalError("APPROVAL_NOT_PENDING")
    if record.operator_identity != operator_identity:
        raise OperatorApprovalError("APPROVAL_OPERATOR_MISMATCH")
    if record.session_binding != _session_binding(session_id):
        raise OperatorApprovalError("APPROVAL_SESSION_MISMATCH")
    if record.environment != guard.environment:
        raise OperatorApprovalError("APPROVAL_ENVIRONMENT_MISMATCH")
    if record.approved_operation != ingest.G12_OPERATION:
        raise OperatorApprovalError("APPROVAL_OPERATION_MISMATCH")
    if record.target_store != guard.identity.resolved_path:
        raise OperatorApprovalError("APPROVAL_TARGET_MISMATCH")
    expected_state = (
        ingest.STORE_STATE_PRESENT
        if guard.identity.exists
        else ingest.STORE_STATE_ABSENT
    )
    if record.target_store_state != expected_state:
        raise OperatorApprovalError("APPROVAL_STORE_STATE_MISMATCH")
    if (
        guard.identity.exists
        and record.target_store_sha256 != guard.identity.sha256
    ):
        raise OperatorApprovalError("APPROVAL_STORE_HASH_MISMATCH")
    if record.manifest_sha256 != manifest.sha256:
        raise OperatorApprovalError("APPROVAL_MANIFEST_HASH_MISMATCH")
    if set(record.approved_record_ids) != set(manifest.record_ids):
        raise OperatorApprovalError("APPROVAL_RECORD_SCOPE_MISMATCH")
    if set(record.approved_content_hashes) != set(manifest.content_hashes):
        raise OperatorApprovalError("APPROVAL_CONTENT_SCOPE_MISMATCH")
    if set(record.approved_store_record_ids) != set(manifest.store_record_ids):
        raise OperatorApprovalError("APPROVAL_STORE_RECORD_SCOPE_MISMATCH")
    if moment < _parse(record.approval_time, "APPROVAL_TIME_INVALID"):
        raise OperatorApprovalError("APPROVAL_NOT_YET_VALID")
    if moment > _parse(record.expires_at, "APPROVAL_EXPIRY_INVALID"):
        raise OperatorApprovalError("APPROVAL_EXPIRED")


def build_production_authorization(
    record: ApprovalRecord,
) -> ingest.ProductionAuthorization:
    return ingest.ProductionAuthorization(
        schema_version=ingest.AUTHORIZATION_SCHEMA_VERSION,
        task_id="TRADINGAI-WORK-BC-G12-OPERATOR-LOGIN-AUTH-MIGRATION-V2",
        workstream=ingest.WORKSTREAM,
        environment=record.environment,
        target_store=record.target_store,
        target_store_state=record.target_store_state,
        target_store_sha256=record.target_store_sha256,
        manifest_sha256=record.manifest_sha256,
        approved_record_ids=record.approved_record_ids,
        approved_content_hashes=record.approved_content_hashes,
        approved_store_record_ids=record.approved_store_record_ids,
        approved_operation=record.approved_operation,
        approval_id=record.approval_id,
        approval_time=record.approval_time,
        expires_at=record.expires_at,
        authorized=True,
    )


def run_operator_authorized_import(
    *,
    ledger: ApprovalLedger,
    approval_id: str,
    operator_identity: str,
    session_id: str,
    guard: ingest.TargetGuard,
    manifest: ingest.CandidateManifest,
    indexed_at: str,
    apply: bool = True,
    backup_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    now: datetime | None = None,
) -> ingest.ImportResult:
    """Verify the operator approval, consume it once, then import."""

    record = ledger.get(approval_id)
    verify_approval_binding(
        record,
        operator_identity=operator_identity,
        session_id=session_id,
        guard=guard,
        manifest=manifest,
        now=now,
    )
    if apply:
        record = ledger.consume(approval_id, now=now)
    authorization = build_production_authorization(record)
    return ingest.run_authorized_import(
        guard,
        authorization,
        manifest,
        indexed_at=indexed_at,
        apply=apply,
        backup_path=backup_path,
        audit_path=audit_path,
        now=now,
    )
