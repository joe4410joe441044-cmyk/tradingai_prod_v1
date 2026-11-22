"""Explicitly authorized Production Knowledge Store ingestion.

This module is a distinct maintenance path. It does not widen the offline
``assert_temporary_store`` guard, does not add an ``allow_production`` switch,
and does not write to the Production Store by itself. A mutation requires all
of the following to agree:

* an immutable operator authorization artifact;
* an immutable candidate manifest whose SHA256 is named by that authorization;
* an exact record allowlist (record IDs and content hashes);
* the expected target Store path, SHA256, schema version, and pre-import state;
* verified source provenance and content hashes;
* a bounded single transaction and post-commit verification.

The caller must supply authorization. This module never creates it, never
infers it from a manifest, and never treats an isolated-test ledger as
Production permission.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import hmac
import json
import os
import sqlite3
import time
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .import_readiness import (
    DEFAULT_ALLOWED_STORE_ROOT,
    PRODUCTION_RUNTIME_ROOT,
    PRODUCTION_STORE_PATH,
    ReadinessError,
    assert_temporary_store,
)
from .knowledge_store import (
    KnowledgeStore,
    StoreError,
    StoreItem,
    logical_key,
    version_id,
)
from .partial_import import _build_item, discover_records
from .reader import ReaderLimits, RequestContext, open_reader


PRODUCTION_INGEST_SCHEMA_VERSION = "tradingai-production-ingest/v1"
AUTHORIZATION_SCHEMA_VERSION = "tradingai-g12-production-authorization/v1"
CANDIDATE_MANIFEST_SCHEMA_VERSION = "tradingai-g12-import-candidate-manifest/v1"

APPROVAL_SIGNATURE_METHOD = "HMAC-SHA256"
APPROVAL_SIGNATURE_FIELDS = frozenset(
    {"approval_signature", "approval_signature_method"}
)
APPROVAL_KEY_ENV = "TRADINGAI_G12_APPROVAL_HMAC_KEY"
APPROVAL_KEY_FILE_ENV = "TRADINGAI_G12_APPROVAL_HMAC_KEY_FILE"
MIN_APPROVAL_KEY_BYTES = 32

PRODUCTION_ENVIRONMENT = "PRODUCTION"
ISOLATED_ENVIRONMENT = "ISOLATED_TEST"
G12_OPERATION = "G12_PRODUCTION_IMPORT"
WORKSTREAM = "BC"
SCAN_SCOPE = "g12-production-ingest"

STORE_STATE_PRESENT = "PRESENT"
STORE_STATE_ABSENT = "ABSENT"

STATUS_PREVIEW = "PREVIEW"
STATUS_COMPLETE = "COMPLETE"
STATUS_IDEMPOTENT = "IDEMPOTENT"
STATUS_BLOCKED = "BLOCKED"

OUTCOME_INSERTED = "INSERTED"
OUTCOME_SKIPPED = "SKIPPED"
OUTCOME_BLOCKED = "BLOCKED"

REQUIRED_SOURCE_TYPE = "DEVELOPMENT_REPORT"
REQUIRED_TRUTH_KIND = "AGENT_REPORTED"
REQUIRED_AUTHORITY_SCOPE = "NONE"
REQUIRED_ACCESS_SCOPE = "OPERATOR"
REQUIRED_TRUST = "UNTRUSTED_KNOWLEDGE"
REQUIRED_HISTORICAL_AUTHORITY = "UNTRUSTED_HISTORICAL"
REQUIRED_RUNTIME_TRUTH = "NOT_ASSERTED"
REQUIRED_PROVENANCE = "CONFIRMED"
ALLOWED_ELIGIBILITY = frozenset(
    {"ELIGIBLE_CANDIDATE_PENDING_G12", "APPROVED_FOR_G12_IMPORT"}
)

OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id=SCAN_SCOPE)


class ProductionIngestError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionIngestError(code)
    return value.strip()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def _resolved_text(path: str | Path) -> str:
    try:
        return str(Path(path).resolve(strict=False))
    except (OSError, RuntimeError):
        raise ProductionIngestError("PATH_REJECTED") from None


def _parse_time(value: str, code: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProductionIngestError(code) from None
    if moment.tzinfo is None:
        raise ProductionIngestError(code)
    return moment.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path, *, not_found: str, invalid: str) -> tuple[Path, bytes, Any]:
    source = Path(path)
    if source.is_symlink():
        raise ProductionIngestError("ARTIFACT_SYMLINK_REJECTED")
    if not source.is_file():
        raise ProductionIngestError(not_found)
    raw = source.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProductionIngestError(invalid) from None
    return source, raw, payload


def _sidecar_paths(path: Path) -> tuple[Path, ...]:
    return (
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def canonical_authorization_bytes(payload: Mapping[str, Any]) -> bytes:
    """Canonical bytes signed by the operator. Signature fields are excluded."""

    if not isinstance(payload, Mapping):
        raise ProductionIngestError("AUTHORIZATION_INVALID")
    body = {
        str(key): value
        for key, value in payload.items()
        if key not in APPROVAL_SIGNATURE_FIELDS
    }
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sign_authorization_payload(payload: Mapping[str, Any], key: bytes | str) -> str:
    """Operator-side helper: return the HMAC-SHA256 signature for an artifact.

    The operator holds the key. An agent must never be given the key, which is
    what makes a self-declared ``authorized: true`` JSON insufficient.
    """

    if isinstance(key, str):
        key = key.encode("utf-8")
    if not isinstance(key, (bytes, bytearray)) or len(key) < MIN_APPROVAL_KEY_BYTES:
        raise ProductionIngestError("APPROVAL_SIGNATURE_KEY_INVALID")
    return hmac.new(
        bytes(key), canonical_authorization_bytes(payload), hashlib.sha256
    ).hexdigest()


def load_approval_key(environ: Mapping[str, str] | None = None) -> bytes:
    """Load the operator-held approval key. Never stored in the worktree."""

    env = os.environ if environ is None else environ
    raw = env.get(APPROVAL_KEY_ENV)
    if raw is not None:
        key = str(raw).encode("utf-8")
        if len(key) < MIN_APPROVAL_KEY_BYTES:
            raise ProductionIngestError("APPROVAL_SIGNATURE_KEY_INVALID")
        return key
    location = env.get(APPROVAL_KEY_FILE_ENV)
    if not isinstance(location, str) or not location.strip():
        raise ProductionIngestError("APPROVAL_SIGNATURE_KEY_REQUIRED")
    path = Path(location)
    if path.is_symlink() or not path.is_file():
        raise ProductionIngestError("APPROVAL_SIGNATURE_KEY_FILE_REJECTED")
    if int(path.stat().st_mode) & 0o077:
        raise ProductionIngestError("APPROVAL_SIGNATURE_KEY_FILE_PERMISSIONS_REJECTED")
    key = path.read_bytes().strip()
    if len(key) < MIN_APPROVAL_KEY_BYTES:
        raise ProductionIngestError("APPROVAL_SIGNATURE_KEY_INVALID")
    return key


def verify_authorization_signature(
    payload: Mapping[str, Any], key: bytes | str
) -> None:
    """Fail closed unless the artifact carries a valid operator HMAC."""

    if not isinstance(payload, Mapping):
        raise ProductionIngestError("AUTHORIZATION_INVALID")
    if payload.get("approval_signature_method") != APPROVAL_SIGNATURE_METHOD:
        raise ProductionIngestError("APPROVAL_SIGNATURE_METHOD_REJECTED")
    signature = payload.get("approval_signature")
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in signature)
    ):
        raise ProductionIngestError("APPROVAL_SIGNATURE_INVALID")
    expected = sign_authorization_payload(payload, key)
    if not hmac.compare_digest(expected, signature.lower()):
        raise ProductionIngestError("APPROVAL_SIGNATURE_MISMATCH")


@dataclass(frozen=True)
class TargetIdentity:
    path: str
    resolved_path: str
    environment: str
    exists: bool
    is_symlink: bool
    sha256: str | None = None
    device: int | None = None
    inode: int | None = None
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None
    schema_version: int | None = None
    record_count: int | None = None
    fts_count: int | None = None
    integrity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "resolved_path": self.resolved_path,
            "environment": self.environment,
            "exists": self.exists,
            "is_symlink": self.is_symlink,
            "sha256": self.sha256,
            "device": self.device,
            "inode": self.inode,
            "uid": self.uid,
            "gid": self.gid,
            "mode": self.mode,
            "schema_version": self.schema_version,
            "record_count": self.record_count,
            "fts_count": self.fts_count,
            "integrity": self.integrity,
        }


def inspect_target(path: str | Path, *, environment: str = ISOLATED_ENVIRONMENT) -> TargetIdentity:
    """Read-only target inspection. Never creates, migrates, or writes."""

    requested = Path(path)
    is_symlink = requested.is_symlink()
    try:
        resolved = requested.resolve(strict=False)
    except (OSError, RuntimeError):
        raise ProductionIngestError("TARGET_PATH_REJECTED") from None
    if not resolved.exists():
        return TargetIdentity(
            path=str(requested),
            resolved_path=str(resolved),
            environment=environment,
            exists=False,
            is_symlink=is_symlink,
        )
    if is_symlink:
        raise ProductionIngestError("TARGET_SYMLINK_REJECTED")
    if not resolved.is_file():
        raise ProductionIngestError("TARGET_NOT_REGULAR_FILE")
    try:
        stat = resolved.stat()
    except OSError:
        raise ProductionIngestError("TARGET_STAT_FAILED") from None
    uri = "file:" + quote(resolved.as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        raise ProductionIngestError("TARGET_NOT_DATABASE") from None
    connection.row_factory = sqlite3.Row
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise ProductionIngestError("TARGET_INTEGRITY_FAILED")
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if schema_version != 1:
            raise ProductionIngestError("TARGET_SCHEMA_MISMATCH")
        record_count = int(connection.execute("SELECT count(*) FROM records").fetchone()[0])
        fts_count = int(connection.execute("SELECT count(*) FROM records_fts").fetchone()[0])
    except sqlite3.Error:
        raise ProductionIngestError("TARGET_NOT_DATABASE") from None
    finally:
        connection.close()
    return TargetIdentity(
        path=str(requested),
        resolved_path=str(resolved),
        environment=environment,
        exists=True,
        is_symlink=False,
        sha256=_sha256(resolved),
        device=int(stat.st_dev),
        inode=int(stat.st_ino),
        uid=int(stat.st_uid),
        gid=int(stat.st_gid),
        mode=int(stat.st_mode),
        schema_version=schema_version,
        record_count=record_count,
        fts_count=fts_count,
        integrity="OK",
    )


def validate_file_protection(
    path: str | Path,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> None:
    """Reject symlinks, non-regular files, and group/world-accessible paths."""

    requested = Path(path)
    if requested.is_symlink():
        raise ProductionIngestError("TARGET_SYMLINK_REJECTED")
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ProductionIngestError("TARGET_NOT_FOUND") from None
    if not resolved.is_file():
        raise ProductionIngestError("TARGET_NOT_REGULAR_FILE")
    stat = resolved.stat()
    owner = os.geteuid() if expected_uid is None else expected_uid
    group = os.getegid() if expected_gid is None else expected_gid
    if int(stat.st_uid) != int(owner):
        raise ProductionIngestError("TARGET_OWNER_REJECTED")
    if int(stat.st_gid) != int(group):
        raise ProductionIngestError("TARGET_GROUP_REJECTED")
    if int(stat.st_mode) & 0o077:
        raise ProductionIngestError("TARGET_PERMISSIONS_REJECTED")
    try:
        parent = resolved.parent.stat()
    except OSError:
        raise ProductionIngestError("TARGET_PARENT_STAT_FAILED") from None
    if int(parent.st_mode) & 0o077:
        raise ProductionIngestError("TARGET_PARENT_PERMISSIONS_REJECTED")


@dataclass(frozen=True)
class TargetGuard:
    identity: TargetIdentity
    require_protection: bool = False

    @property
    def environment(self) -> str:
        return self.identity.environment

    def to_dict(self) -> dict[str, Any]:
        return self.identity.to_dict()


def production_target_guard() -> TargetGuard:
    """Bind to the one canonical Production Store path. No overrides."""

    canonical = PRODUCTION_STORE_PATH.resolve(strict=False)
    identity = inspect_target(PRODUCTION_STORE_PATH, environment=PRODUCTION_ENVIRONMENT)
    if identity.is_symlink:
        raise ProductionIngestError("TARGET_SYMLINK_REJECTED")
    if Path(identity.resolved_path) != canonical:
        raise ProductionIngestError("PRODUCTION_TARGET_PATH_MISMATCH")
    if not identity.exists:
        raise ProductionIngestError("PRODUCTION_TARGET_NOT_FOUND")
    validate_file_protection(PRODUCTION_STORE_PATH)
    for sidecar in _sidecar_paths(Path(identity.resolved_path)):
        if sidecar.exists():
            raise ProductionIngestError("PRODUCTION_TARGET_SIDECAR_PRESENT")
    return TargetGuard(identity=identity, require_protection=True)


def isolated_target_guard(
    path: str | Path,
    *,
    allowed_root: str | Path = DEFAULT_ALLOWED_STORE_ROOT,
) -> TargetGuard:
    """Bind to an isolated test target. The Production Store is rejected."""

    try:
        requested = assert_temporary_store(path, allowed_root=allowed_root)
    except ReadinessError as exc:
        raise ProductionIngestError(exc.code) from None
    runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    resolved = requested.resolve(strict=False)
    if resolved == runtime_root or resolved.is_relative_to(runtime_root):
        raise ProductionIngestError("PRODUCTION_RUNTIME_ROOT_REJECTED")
    if resolved == PRODUCTION_STORE_PATH.resolve(strict=False):
        raise ProductionIngestError("PRODUCTION_STORE_REJECTED")
    identity = inspect_target(requested, environment=ISOLATED_ENVIRONMENT)
    return TargetGuard(identity=identity, require_protection=False)


@dataclass(frozen=True)
class ProductionAuthorization:
    schema_version: str
    task_id: str
    workstream: str
    environment: str
    target_store: str
    target_store_state: str
    target_store_sha256: str | None
    manifest_sha256: str
    approved_record_ids: tuple[str, ...]
    approved_content_hashes: tuple[str, ...]
    approved_store_record_ids: tuple[str, ...]
    approved_operation: str
    approval_id: str
    approval_time: str
    expires_at: str
    authorized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "workstream": self.workstream,
            "environment": self.environment,
            "target_store": self.target_store,
            "target_store_state": self.target_store_state,
            "target_store_sha256": self.target_store_sha256,
            "manifest_sha256": self.manifest_sha256,
            "approved_record_ids": list(self.approved_record_ids),
            "approved_content_hashes": list(self.approved_content_hashes),
            "approved_store_record_ids": list(self.approved_store_record_ids),
            "approved_operation": self.approved_operation,
            "approval_id": self.approval_id,
            "approval_time": self.approval_time,
            "expires_at": self.expires_at,
            "authorized": self.authorized,
        }


def _unique_sorted(values: Any, code: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise ProductionIngestError(code)
    cleaned = tuple(_require_text(item, code) for item in values)
    if len(set(cleaned)) != len(cleaned):
        raise ProductionIngestError("AUTHORIZATION_DUPLICATE_SCOPE_ENTRY")
    return tuple(sorted(cleaned))


def parse_authorization(payload: Mapping[str, Any]) -> ProductionAuthorization:
    if not isinstance(payload, Mapping):
        raise ProductionIngestError("AUTHORIZATION_INVALID")
    if payload.get("schema_version") != AUTHORIZATION_SCHEMA_VERSION:
        raise ProductionIngestError("AUTHORIZATION_SCHEMA_MISMATCH")
    if payload.get("authorized") is not True:
        raise ProductionIngestError("AUTHORIZATION_NOT_GRANTED")
    environment = str(payload.get("environment", "")).strip().upper()
    if environment not in {PRODUCTION_ENVIRONMENT, ISOLATED_ENVIRONMENT}:
        raise ProductionIngestError("AUTHORIZATION_ENVIRONMENT_INVALID")
    state = str(payload.get("target_store_state", "")).strip().upper()
    if state not in {STORE_STATE_PRESENT, STORE_STATE_ABSENT}:
        raise ProductionIngestError("AUTHORIZATION_TARGET_STATE_INVALID")
    target_hash = payload.get("target_store_sha256")
    if state == STORE_STATE_PRESENT:
        if not _is_sha256(target_hash):
            raise ProductionIngestError("AUTHORIZATION_TARGET_HASH_INVALID")
        target_hash = str(target_hash).lower()
    else:
        target_hash = None
    manifest_hash = payload.get("manifest_sha256")
    if not _is_sha256(manifest_hash):
        raise ProductionIngestError("AUTHORIZATION_MANIFEST_HASH_INVALID")
    approved_ids = _unique_sorted(
        payload.get("approved_record_ids"), "AUTHORIZATION_RECORD_IDS_INVALID"
    )
    approved_hashes = _unique_sorted(
        payload.get("approved_content_hashes"), "AUTHORIZATION_CONTENT_HASHES_INVALID"
    )
    if any(not _is_sha256(item) for item in approved_hashes):
        raise ProductionIngestError("AUTHORIZATION_CONTENT_HASH_INVALID")
    raw_store_ids = payload.get("approved_store_record_ids", [])
    approved_store_ids = (
        _unique_sorted(raw_store_ids, "AUTHORIZATION_STORE_RECORD_IDS_INVALID")
        if raw_store_ids
        else ()
    )
    approval_time = _require_text(payload.get("approval_time"), "AUTHORIZATION_TIME_REQUIRED")
    expires_at = _require_text(payload.get("expires_at"), "AUTHORIZATION_EXPIRY_REQUIRED")
    if _parse_time(expires_at, "AUTHORIZATION_EXPIRY_INVALID") <= _parse_time(
        approval_time, "AUTHORIZATION_TIME_INVALID"
    ):
        raise ProductionIngestError("AUTHORIZATION_EXPIRY_INVALID")
    return ProductionAuthorization(
        schema_version=AUTHORIZATION_SCHEMA_VERSION,
        task_id=_require_text(payload.get("task_id"), "AUTHORIZATION_TASK_REQUIRED"),
        workstream=_require_text(payload.get("workstream"), "AUTHORIZATION_WORKSTREAM_REQUIRED"),
        environment=environment,
        target_store=_require_text(
            payload.get("target_store"), "AUTHORIZATION_TARGET_REQUIRED"
        ),
        target_store_state=state,
        target_store_sha256=target_hash,
        manifest_sha256=str(manifest_hash).lower(),
        approved_record_ids=approved_ids,
        approved_content_hashes=tuple(item.lower() for item in approved_hashes),
        approved_store_record_ids=approved_store_ids,
        approved_operation=_require_text(
            payload.get("approved_operation"), "AUTHORIZATION_OPERATION_REQUIRED"
        ),
        approval_id=_require_text(payload.get("approval_id"), "AUTHORIZATION_ID_REQUIRED"),
        approval_time=approval_time,
        expires_at=expires_at,
        authorized=True,
    )


def load_authorization(
    path: str | Path, *, environ: Mapping[str, str] | None = None
) -> ProductionAuthorization:
    _, _, payload = _read_json(
        path,
        not_found="AUTHORIZATION_NOT_FOUND",
        invalid="AUTHORIZATION_INVALID",
    )
    authorization = parse_authorization(payload)
    if authorization.environment == PRODUCTION_ENVIRONMENT:
        verify_authorization_signature(payload, load_approval_key(environ))
    return authorization


@dataclass(frozen=True)
class CandidateRecord:
    record_id: str
    store_record_id: str
    source_identifier: str
    content_hash: str
    source_type: str
    truth_kind: str
    authority_scope: str
    access_scope: str
    trust_classification: str
    provenance_status: str
    import_eligibility: str


@dataclass(frozen=True)
class CandidateManifest:
    schema_version: str
    task_id: str
    original_task_id: str
    g12_status: str
    production_import_performed: bool
    source_of_evidence: str
    target_for_review: str
    record_count: int
    records: tuple[CandidateRecord, ...]
    sha256: str = ""

    @property
    def record_ids(self) -> tuple[str, ...]:
        return tuple(item.record_id for item in self.records)

    @property
    def content_hashes(self) -> tuple[str, ...]:
        return tuple(item.content_hash for item in self.records)

    @property
    def store_record_ids(self) -> tuple[str, ...]:
        return tuple(item.store_record_id for item in self.records)


def parse_candidate_manifest(payload: Mapping[str, Any], *, sha256: str = "") -> CandidateManifest:
    if not isinstance(payload, Mapping):
        raise ProductionIngestError("MANIFEST_INVALID")
    if payload.get("schema_version") != CANDIDATE_MANIFEST_SCHEMA_VERSION:
        raise ProductionIngestError("MANIFEST_SCHEMA_MISMATCH")
    if payload.get("production_import_performed") is not False:
        raise ProductionIngestError("MANIFEST_NOT_A_CANDIDATE")
    if _resolved_text(payload.get("target_for_review", "")) != _resolved_text(
        PRODUCTION_STORE_PATH
    ):
        raise ProductionIngestError("MANIFEST_TARGET_MISMATCH")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise ProductionIngestError("MANIFEST_EMPTY")
    declared_count = payload.get("record_count")
    if not isinstance(declared_count, int) or declared_count != len(raw_records):
        raise ProductionIngestError("MANIFEST_RECORD_COUNT_MISMATCH")
    records: list[CandidateRecord] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ProductionIngestError("MANIFEST_RECORD_INVALID")
        record = CandidateRecord(
            record_id=_require_text(raw.get("RECORD_ID"), "MANIFEST_RECORD_ID_REQUIRED"),
            store_record_id=_require_text(
                raw.get("STORE_RECORD_ID"), "MANIFEST_STORE_RECORD_ID_REQUIRED"
            ),
            source_identifier=_require_text(
                raw.get("SOURCE_IDENTIFIER"), "MANIFEST_SOURCE_REQUIRED"
            ),
            content_hash=str(raw.get("CONTENT_HASH", "")).lower(),
            source_type=str(raw.get("SOURCE_TYPE", "")),
            truth_kind=str(raw.get("TRUTH_KIND", "")),
            authority_scope=str(raw.get("AUTHORITY_SCOPE", "")),
            access_scope=str(raw.get("ACCESS_SCOPE", "")),
            trust_classification=str(raw.get("TRUST_CLASSIFICATION", "")),
            provenance_status=str(raw.get("PROVENANCE_STATUS", "")),
            import_eligibility=str(raw.get("IMPORT_ELIGIBILITY", "")),
        )
        if not _is_sha256(record.content_hash):
            raise ProductionIngestError("MANIFEST_CONTENT_HASH_INVALID")
        if record.source_type != REQUIRED_SOURCE_TYPE:
            raise ProductionIngestError("MANIFEST_SOURCE_TYPE_REJECTED")
        if record.truth_kind != REQUIRED_TRUTH_KIND:
            raise ProductionIngestError("MANIFEST_TRUTH_KIND_REJECTED")
        if record.authority_scope != REQUIRED_AUTHORITY_SCOPE:
            raise ProductionIngestError("MANIFEST_AUTHORITY_REJECTED")
        if record.access_scope != REQUIRED_ACCESS_SCOPE:
            raise ProductionIngestError("MANIFEST_ACCESS_SCOPE_REJECTED")
        if record.trust_classification != REQUIRED_TRUST:
            raise ProductionIngestError("MANIFEST_TRUST_REJECTED")
        if record.provenance_status != REQUIRED_PROVENANCE:
            raise ProductionIngestError("MANIFEST_PROVENANCE_REJECTED")
        if record.import_eligibility not in ALLOWED_ELIGIBILITY:
            raise ProductionIngestError("MANIFEST_ELIGIBILITY_REJECTED")
        if not Path(record.source_identifier).is_absolute():
            raise ProductionIngestError("MANIFEST_SOURCE_NOT_ABSOLUTE")
        records.append(record)
    if len({item.record_id for item in records}) != len(records):
        raise ProductionIngestError("MANIFEST_DUPLICATE_RECORD_ID")
    if len({item.store_record_id for item in records}) != len(records):
        raise ProductionIngestError("MANIFEST_DUPLICATE_STORE_RECORD_ID")
    if len({item.content_hash for item in records}) != len(records):
        raise ProductionIngestError("MANIFEST_DUPLICATE_CONTENT_HASH")
    return CandidateManifest(
        schema_version=CANDIDATE_MANIFEST_SCHEMA_VERSION,
        task_id=str(payload.get("task_id", "")),
        original_task_id=str(payload.get("original_task_id", "")),
        g12_status=str(payload.get("g12_status", "")),
        production_import_performed=False,
        source_of_evidence=str(payload.get("source_of_evidence", "")),
        target_for_review=str(payload.get("target_for_review", "")),
        record_count=len(records),
        records=tuple(records),
        sha256=sha256,
    )


def load_candidate_manifest(path: str | Path) -> CandidateManifest:
    _, raw, payload = _read_json(
        path,
        not_found="MANIFEST_NOT_FOUND",
        invalid="MANIFEST_INVALID",
    )
    return parse_candidate_manifest(payload, sha256=hashlib.sha256(raw).hexdigest())


def validate_authorization(
    authorization: ProductionAuthorization | None,
    *,
    guard: TargetGuard,
    manifest: CandidateManifest,
    now: datetime | None = None,
) -> ProductionAuthorization:
    if authorization is None:
        raise ProductionIngestError("AUTHORIZATION_REQUIRED")
    if authorization.schema_version != AUTHORIZATION_SCHEMA_VERSION:
        raise ProductionIngestError("AUTHORIZATION_SCHEMA_MISMATCH")
    if authorization.authorized is not True:
        raise ProductionIngestError("AUTHORIZATION_NOT_GRANTED")
    if authorization.environment != guard.environment:
        raise ProductionIngestError("AUTHORIZATION_ENVIRONMENT_MISMATCH")
    if authorization.workstream != WORKSTREAM:
        raise ProductionIngestError("AUTHORIZATION_WORKSTREAM_MISMATCH")
    if authorization.approved_operation != G12_OPERATION:
        raise ProductionIngestError("AUTHORIZATION_OPERATION_MISMATCH")
    if _resolved_text(authorization.target_store) != _resolved_text(guard.identity.resolved_path):
        raise ProductionIngestError("AUTHORIZATION_TARGET_MISMATCH")
    if authorization.manifest_sha256 != manifest.sha256:
        raise ProductionIngestError("MANIFEST_HASH_MISMATCH")
    if guard.environment == PRODUCTION_ENVIRONMENT:
        if authorization.target_store_state != STORE_STATE_PRESENT:
            raise ProductionIngestError("AUTHORIZATION_STORE_STATE_MISMATCH")
        if not guard.identity.exists:
            raise ProductionIngestError("PRODUCTION_TARGET_NOT_FOUND")
        if authorization.target_store_sha256 != guard.identity.sha256:
            raise ProductionIngestError("AUTHORIZATION_STORE_HASH_MISMATCH")
    else:
        if authorization.target_store_state == STORE_STATE_PRESENT:
            if not guard.identity.exists or authorization.target_store_sha256 != guard.identity.sha256:
                raise ProductionIngestError("AUTHORIZATION_STORE_HASH_MISMATCH")
        else:
            if guard.identity.exists:
                raise ProductionIngestError("AUTHORIZATION_STORE_STATE_MISMATCH")
    if set(authorization.approved_record_ids) != set(manifest.record_ids):
        raise ProductionIngestError("AUTHORIZATION_RECORD_SCOPE_MISMATCH")
    if set(authorization.approved_content_hashes) != set(manifest.content_hashes):
        raise ProductionIngestError("AUTHORIZATION_CONTENT_SCOPE_MISMATCH")
    if authorization.approved_store_record_ids and (
        set(authorization.approved_store_record_ids) != set(manifest.store_record_ids)
    ):
        raise ProductionIngestError("AUTHORIZATION_STORE_RECORD_SCOPE_MISMATCH")
    moment = now or datetime.now(timezone.utc)
    if moment < _parse_time(authorization.approval_time, "AUTHORIZATION_TIME_INVALID"):
        raise ProductionIngestError("AUTHORIZATION_NOT_YET_VALID")
    if moment > _parse_time(authorization.expires_at, "AUTHORIZATION_EXPIRY_INVALID"):
        raise ProductionIngestError("AUTHORIZATION_EXPIRED")
    return authorization


@dataclass(frozen=True)
class PlannedRecord:
    candidate: CandidateRecord
    item: StoreItem
    record_id: str
    logical_key: str
    content_hash: str
    source_file: str
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.candidate.record_id,
            "store_record_id": self.record_id,
            "content_hash": self.content_hash,
            "source_identifier": self.candidate.source_identifier,
            "verification_state": self.outcome,
        }


@dataclass(frozen=True)
class ImportPlan:
    target: TargetIdentity
    authorization_id: str
    manifest_sha256: str
    records: tuple[PlannedRecord, ...]
    record_count_before: int | None
    to_insert: int
    to_skip: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_dict(),
            "authorization_id": self.authorization_id,
            "manifest_sha256": self.manifest_sha256,
            "record_count_before": self.record_count_before,
            "to_insert": self.to_insert,
            "to_skip": self.to_skip,
            "records": [item.to_dict() for item in self.records],
        }


def _source_roots(manifest: CandidateManifest) -> tuple[str, ...]:
    roots = {str(Path(item.source_identifier).resolve(strict=False).parent) for item in manifest.records}
    if not roots:
        raise ProductionIngestError("SOURCE_ROOT_REQUIRED")
    for root in roots:
        resolved = Path(root).resolve(strict=False)
        runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
        if resolved == runtime_root or resolved.is_relative_to(runtime_root):
            raise ProductionIngestError("PRODUCTION_SOURCE_REJECTED")
    return tuple(sorted(roots))


def _existing_records(
    identity: TargetIdentity,
    *,
    record_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    if not identity.exists or not record_ids:
        return {}
    uri = "file:" + quote(Path(identity.resolved_path).as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        raise ProductionIngestError("TARGET_NOT_DATABASE") from None
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in record_ids)
        rows = connection.execute(
            f"SELECT * FROM records WHERE record_id IN ({placeholders})",
            tuple(record_ids),
        ).fetchall()
        return {str(row["record_id"]): dict(row) for row in rows}
    except sqlite3.Error:
        raise ProductionIngestError("TARGET_NOT_DATABASE") from None
    finally:
        connection.close()


def build_import_plan(
    guard: TargetGuard,
    authorization: ProductionAuthorization | None,
    manifest: CandidateManifest,
    *,
    indexed_at: str,
    now: datetime | None = None,
) -> ImportPlan:
    if not indexed_at or not isinstance(indexed_at, str):
        raise ProductionIngestError("TIMESTAMP_REQUIRED")
    validate_authorization(authorization, guard=guard, manifest=manifest, now=now)
    assert authorization is not None
    source_paths = tuple(item.source_identifier for item in manifest.records)
    roots = _source_roots(manifest)
    discovered, blocked = discover_records(source_paths, source_roots=roots)
    if blocked:
        raise ProductionIngestError(f"SOURCE_BLOCKED:{blocked[0].code}")
    by_hash = {record.content_hash: record for record in discovered}
    if set(by_hash) != set(manifest.content_hashes):
        raise ProductionIngestError("DISCOVERED_SOURCE_SET_MISMATCH")
    existing_by_id = _existing_records(
        guard.identity,
        record_ids=manifest.store_record_ids,
    )
    planned: list[PlannedRecord] = []
    to_insert = 0
    to_skip = 0
    for candidate in manifest.records:
        record = by_hash.get(candidate.content_hash)
        if record is None:
            raise ProductionIngestError("SOURCE_CONTENT_HASH_MISMATCH")
        if _resolved_text(record.source_file) != _resolved_text(candidate.source_identifier):
            raise ProductionIngestError("SOURCE_PROVENANCE_MISMATCH")
        if hashlib.sha256(Path(record.source_file).read_bytes()).hexdigest() != candidate.content_hash:
            raise ProductionIngestError("SOURCE_HASH_MISMATCH")
        item = _build_item(
            record,
            content=record.content,
            content_hash=record.content_hash,
            workstream=record.workstream,
            decision_record_id=candidate.record_id,
            redacted=False,
            indexed_at=indexed_at,
        )
        if item.source_type != REQUIRED_SOURCE_TYPE:
            raise ProductionIngestError("SOURCE_TYPE_REJECTED")
        if item.truth_kind != REQUIRED_TRUTH_KIND:
            raise ProductionIngestError("TRUTH_KIND_REJECTED")
        metadata = dict(item.metadata or {})
        if metadata.get("access_scope") != REQUIRED_ACCESS_SCOPE:
            raise ProductionIngestError("ACCESS_SCOPE_REJECTED")
        if metadata.get("trust") != REQUIRED_TRUST:
            raise ProductionIngestError("TRUST_REJECTED")
        if metadata.get("runtime_truth") != REQUIRED_RUNTIME_TRUTH:
            raise ProductionIngestError("RUNTIME_TRUTH_REJECTED")
        if metadata.get("historical_authority") != REQUIRED_HISTORICAL_AUTHORITY:
            raise ProductionIngestError("HISTORICAL_AUTHORITY_REJECTED")
        key = logical_key(item)
        record_id = version_id(item, item.content_hash)
        if record_id != candidate.store_record_id:
            raise ProductionIngestError("STORE_RECORD_ID_MISMATCH")
        existing = existing_by_id.get(record_id)
        if existing is not None:
            if str(existing["content_hash"]) != candidate.content_hash:
                raise ProductionIngestError("RECORD_CONTENT_CHANGED_CONFLICT")
            to_skip += 1
            outcome = OUTCOME_SKIPPED
        else:
            to_insert += 1
            outcome = OUTCOME_INSERTED
        planned.append(
            PlannedRecord(
                candidate=candidate,
                item=item,
                record_id=record_id,
                logical_key=key,
                content_hash=item.content_hash,
                source_file=record.source_file,
                outcome=outcome,
            )
        )
    return ImportPlan(
        target=guard.identity,
        authorization_id=authorization.approval_id,
        manifest_sha256=manifest.sha256,
        records=tuple(planned),
        record_count_before=guard.identity.record_count,
        to_insert=to_insert,
        to_skip=to_skip,
    )


@dataclass(frozen=True)
class BackupEvidence:
    path: str
    source_sha256: str
    backup_sha256: str
    bytes: int
    integrity: str
    record_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_sha256": self.source_sha256,
            "backup_sha256": self.backup_sha256,
            "bytes": self.bytes,
            "integrity": self.integrity,
            "record_count": self.record_count,
        }


def create_pre_import_backup(guard: TargetGuard, backup_path: str | Path) -> BackupEvidence:
    if guard.environment != PRODUCTION_ENVIRONMENT:
        raise ProductionIngestError("BACKUP_PRODUCTION_ONLY")
    if not guard.identity.exists or not guard.identity.sha256:
        raise ProductionIngestError("PRODUCTION_TARGET_NOT_FOUND")
    destination = Path(backup_path)
    if destination.is_symlink():
        raise ProductionIngestError("BACKUP_SYMLINK_REJECTED")
    resolved = destination.resolve(strict=False)
    runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    if resolved == runtime_root or resolved.is_relative_to(runtime_root):
        raise ProductionIngestError("BACKUP_IN_PRODUCTION_RUNTIME_ROOT")
    if resolved.exists():
        raise ProductionIngestError("BACKUP_ALREADY_EXISTS")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    source_uri = (
        "file:" + quote(Path(guard.identity.resolved_path).as_posix(), safe="/:") + "?mode=ro"
    )
    try:
        source = sqlite3.connect(source_uri, uri=True)
        target = sqlite3.connect(resolved)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
    except sqlite3.Error:
        raise ProductionIngestError("BACKUP_FAILED") from None
    backup = inspect_target(resolved, environment=PRODUCTION_ENVIRONMENT)
    if backup.integrity != "OK" or backup.schema_version != guard.identity.schema_version:
        raise ProductionIngestError("BACKUP_VERIFICATION_FAILED")
    if backup.record_count != guard.identity.record_count:
        raise ProductionIngestError("BACKUP_RECORD_COUNT_MISMATCH")
    return BackupEvidence(
        path=str(resolved),
        source_sha256=guard.identity.sha256,
        backup_sha256=backup.sha256 or "",
        bytes=resolved.stat().st_size,
        integrity=backup.integrity,
        record_count=int(backup.record_count or 0),
    )


def _assert_guard_current(guard: TargetGuard) -> None:
    current = inspect_target(guard.identity.resolved_path, environment=guard.environment)
    if guard.identity.exists:
        if not current.exists:
            raise ProductionIngestError("TARGET_CHANGED_BEFORE_WRITE")
        if (
            current.sha256 != guard.identity.sha256
            or current.device != guard.identity.device
            or current.inode != guard.identity.inode
            or current.schema_version != guard.identity.schema_version
            or current.record_count != guard.identity.record_count
        ):
            raise ProductionIngestError("TARGET_CHANGED_BEFORE_WRITE")
    elif current.exists:
        raise ProductionIngestError("TARGET_APPEARED_BEFORE_WRITE")


@dataclass(frozen=True)
class RecordResult:
    record_id: str
    store_record_id: str
    content_hash: str
    source_identifier: str
    outcome: str
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "store_record_id": self.store_record_id,
            "content_hash": self.content_hash,
            "source_identifier": self.source_identifier,
            "outcome": self.outcome,
            "code": self.code,
        }


@dataclass(frozen=True)
class ImportResult:
    schema_version: str
    status: str
    environment: str
    applied: bool
    authorization_id: str | None
    manifest_sha256: str | None
    target_path: str | None
    store_sha256_before: str | None
    store_sha256_after: str | None
    record_count_before: int | None
    record_count_after: int | None
    fts_count_after: int | None
    integrity_after: str | None
    plan: dict[str, Any]
    records: tuple[RecordResult, ...]
    inserted: int
    skipped: int
    blocked: int
    backup: BackupEvidence | None
    audit: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "environment": self.environment,
            "applied": self.applied,
            "authorization_id": self.authorization_id,
            "manifest_sha256": self.manifest_sha256,
            "target_path": self.target_path,
            "store_sha256_before": self.store_sha256_before,
            "store_sha256_after": self.store_sha256_after,
            "record_count_before": self.record_count_before,
            "record_count_after": self.record_count_after,
            "fts_count_after": self.fts_count_after,
            "integrity_after": self.integrity_after,
            "plan": dict(self.plan),
            "records": [item.to_dict() for item in self.records],
            "inserted": self.inserted,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "backup": None if self.backup is None else self.backup.to_dict(),
            "audit": [dict(event) for event in self.audit],
            "errors": list(self.errors),
            "duration_seconds": self.duration_seconds,
        }


def _blocked_result(
    *,
    environment: str,
    error: str,
    started: float,
    authorization_id: str | None = None,
    manifest_sha256: str | None = None,
    target: TargetIdentity | None = None,
    audit: Sequence[Mapping[str, Any]] = (),
    backup: BackupEvidence | None = None,
) -> ImportResult:
    events = [dict(event) for event in audit]
    events.append({"event": "BLOCKED", "code": error})
    return ImportResult(
        schema_version=PRODUCTION_INGEST_SCHEMA_VERSION,
        status=STATUS_BLOCKED,
        environment=environment,
        applied=False,
        authorization_id=authorization_id,
        manifest_sha256=manifest_sha256,
        target_path=None if target is None else target.resolved_path,
        store_sha256_before=None if target is None else target.sha256,
        store_sha256_after=None,
        record_count_before=None if target is None else target.record_count,
        record_count_after=None,
        fts_count_after=None,
        integrity_after=None,
        plan={},
        records=(),
        inserted=0,
        skipped=0,
        blocked=0,
        backup=backup,
        audit=tuple(events),
        errors=(error,),
        duration_seconds=round(time.monotonic() - started, 6),
    )


def run_authorized_import(
    guard: TargetGuard,
    authorization: ProductionAuthorization | None,
    manifest: CandidateManifest,
    *,
    indexed_at: str,
    apply: bool = False,
    backup_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    max_transaction_seconds: float = 30.0,
    now: datetime | None = None,
) -> ImportResult:
    """Validate everything, then optionally import in one bounded transaction.

    ``apply=False`` never opens a writable database. Production writes require a
    valid PRODUCTION authorization bound to the current Store SHA256, plus an
    explicit backup path and audit path.
    """

    started = time.monotonic()
    environment = guard.environment
    audit: list[dict[str, Any]] = [
        {"event": "GUARD_READY", "target": guard.identity.to_dict()}
    ]

    def blocked(
        code: str,
        *,
        target: TargetIdentity | None = None,
        backup: BackupEvidence | None = None,
    ) -> ImportResult:
        result = _blocked_result(
            environment=environment,
            error=code,
            started=started,
            authorization_id=None if authorization is None else authorization.approval_id,
            manifest_sha256=manifest.sha256 or None,
            target=target if target is not None else guard.identity,
            audit=audit,
            backup=backup,
        )
        if audit_path is not None:
            try:
                write_audit_evidence(audit_path, result.to_dict())
            except ProductionIngestError:
                pass
        return result

    try:
        plan = build_import_plan(
            guard,
            authorization,
            manifest,
            indexed_at=indexed_at,
            now=now,
        )
    except ProductionIngestError as exc:
        return blocked(exc.code)
    assert authorization is not None
    audit.append(
        {
            "event": "AUTHORIZATION_VALIDATED",
            "authorization_id": authorization.approval_id,
            "environment": authorization.environment,
            "manifest_sha256": manifest.sha256,
            "approved_record_ids": list(authorization.approved_record_ids),
            "approved_content_hashes": list(authorization.approved_content_hashes),
        }
    )
    audit.append({"event": "PLAN_READY", "to_insert": plan.to_insert, "to_skip": plan.to_skip})
    if not apply:
        return ImportResult(
            schema_version=PRODUCTION_INGEST_SCHEMA_VERSION,
            status=STATUS_PREVIEW,
            environment=environment,
            applied=False,
            authorization_id=authorization.approval_id,
            manifest_sha256=manifest.sha256,
            target_path=guard.identity.resolved_path,
            store_sha256_before=guard.identity.sha256,
            store_sha256_after=None,
            record_count_before=guard.identity.record_count,
            record_count_after=None,
            fts_count_after=None,
            integrity_after=None,
            plan=plan.to_dict(),
            records=tuple(
                RecordResult(
                    record_id=item.candidate.record_id,
                    store_record_id=item.record_id,
                    content_hash=item.content_hash,
                    source_identifier=item.candidate.source_identifier,
                    outcome=item.outcome,
                    code="PLANNED",
                )
                for item in plan.records
            ),
            inserted=0,
            skipped=0,
            blocked=0,
            backup=None,
            audit=tuple(audit),
            errors=(),
            duration_seconds=round(time.monotonic() - started, 6),
        )

    backup: BackupEvidence | None = None
    if environment == PRODUCTION_ENVIRONMENT:
        if backup_path is None:
            return blocked("BACKUP_REQUIRED")
        if audit_path is None:
            return blocked("AUDIT_PATH_REQUIRED")
        try:
            write_audit_evidence(
                audit_path,
                {
                    "schema_version": PRODUCTION_INGEST_SCHEMA_VERSION,
                    "event": "AUDIT_OPENED",
                    "authorization_id": authorization.approval_id,
                    "manifest_sha256": manifest.sha256,
                    "target": guard.identity.to_dict(),
                },
            )
        except ProductionIngestError as exc:
            return blocked(exc.code)
        try:
            backup = create_pre_import_backup(guard, backup_path)
        except ProductionIngestError as exc:
            return blocked(exc.code)
        audit.append({"event": "BACKUP_CREATED", **backup.to_dict()})

    records: list[RecordResult] = []
    inserted = skipped = 0
    store: KnowledgeStore | None = None
    try:
        _assert_guard_current(guard)
        audit.append({"event": "TRANSACTION_BEGIN", "target_sha256": guard.identity.sha256})
        if guard.identity.exists:
            store = KnowledgeStore.open(guard.identity.resolved_path)
        else:
            store = KnowledgeStore.create(guard.identity.resolved_path)
        transaction_started = time.monotonic()

        def action() -> None:
            nonlocal inserted, skipped
            for planned in plan.records:
                if time.monotonic() - transaction_started > max_transaction_seconds:
                    raise ProductionIngestError("TRANSACTION_TIMEOUT")
                existing = store.get_record(planned.record_id)
                if existing is not None:
                    if str(existing["content_hash"]) != planned.content_hash:
                        raise ProductionIngestError("RECORD_CONTENT_CHANGED_CONFLICT")
                    skipped += 1
                    records.append(
                        RecordResult(
                            record_id=planned.candidate.record_id,
                            store_record_id=planned.record_id,
                            content_hash=planned.content_hash,
                            source_identifier=planned.candidate.source_identifier,
                            outcome=OUTCOME_SKIPPED,
                            code="IDEMPOTENT_EXISTING",
                        )
                    )
                    continue
                conflicts = store.records_for_logical_key(planned.logical_key)
                if any(
                    str(row["record_id"]) != planned.record_id and str(row["presence"]) == "CURRENT"
                    for row in conflicts
                ):
                    raise ProductionIngestError("RECORD_LOGICAL_KEY_CONFLICT")
                state = store.upsert(
                    planned.item,
                    indexed_at=indexed_at,
                    scan_scope=SCAN_SCOPE,
                )
                if state == "SKIPPED":
                    skipped += 1
                    outcome = OUTCOME_SKIPPED
                else:
                    inserted += 1
                    outcome = OUTCOME_INSERTED
                records.append(
                    RecordResult(
                        record_id=planned.candidate.record_id,
                        store_record_id=planned.record_id,
                        content_hash=planned.content_hash,
                        source_identifier=planned.candidate.source_identifier,
                        outcome=outcome,
                        code=state,
                    )
                )

        store.in_transaction(action)
        audit.append(
            {
                "event": "TRANSACTION_COMMIT",
                "inserted": inserted,
                "skipped": skipped,
            }
        )
        store.integrity_check()
    except (ProductionIngestError, StoreError, sqlite3.Error, OSError) as exc:
        code = getattr(exc, "code", "TRANSACTION_FAILED")
        return blocked(code, backup=backup)
    finally:
        if store is not None:
            store.close()

    try:
        after = inspect_target(guard.identity.resolved_path, environment=environment)
    except ProductionIngestError as exc:
        return blocked(exc.code, backup=backup)
    expected_count = int(guard.identity.record_count or 0) + inserted
    if after.record_count != expected_count:
        return blocked("POST_IMPORT_RECORD_COUNT_MISMATCH", target=after, backup=backup)
    if after.fts_count != after.record_count:
        return blocked("POST_IMPORT_FTS_MISMATCH", target=after, backup=backup)
    audit.append(
        {
            "event": "POST_VERIFY",
            "record_count": after.record_count,
            "fts_count": after.fts_count,
            "integrity": after.integrity,
            "store_sha256": after.sha256,
        }
    )
    status = STATUS_IDEMPOTENT if inserted == 0 else STATUS_COMPLETE
    result = ImportResult(
        schema_version=PRODUCTION_INGEST_SCHEMA_VERSION,
        status=status,
        environment=environment,
        applied=True,
        authorization_id=authorization.approval_id,
        manifest_sha256=manifest.sha256,
        target_path=after.resolved_path,
        store_sha256_before=guard.identity.sha256,
        store_sha256_after=after.sha256,
        record_count_before=guard.identity.record_count,
        record_count_after=after.record_count,
        fts_count_after=after.fts_count,
        integrity_after=after.integrity,
        plan=plan.to_dict(),
        records=tuple(records),
        inserted=inserted,
        skipped=skipped,
        blocked=0,
        backup=backup,
        audit=tuple(audit),
        errors=(),
        duration_seconds=round(time.monotonic() - started, 6),
    )
    if audit_path is not None:
        try:
            write_audit_evidence(audit_path, result.to_dict())
        except ProductionIngestError as exc:
            result = replace(
                result,
                errors=(exc.code,),
                audit=result.audit
                + ({"event": "AUDIT_WRITE_FAILED", "code": exc.code},),
            )
    return result


def write_audit_evidence(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path)
    if destination.is_symlink():
        raise ProductionIngestError("AUDIT_SYMLINK_REJECTED")
    resolved = destination.resolve(strict=False)
    runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    if resolved == runtime_root or resolved.is_relative_to(runtime_root):
        raise ProductionIngestError("AUDIT_IN_PRODUCTION_RUNTIME_ROOT")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        raise ProductionIngestError("AUDIT_WRITE_FAILED") from None
    return resolved


def query_isolated_read(
    store_path: str | Path,
    text: str,
    *,
    role: str,
) -> dict[str, Any]:
    """Read-only Advisor/Supervisor probe used by isolated acceptance."""

    from .knowledge_access import query_advisor_knowledge, query_supervisor_knowledge

    query = query_advisor_knowledge if role == "ADVISOR" else query_supervisor_knowledge
    result = query(text, store_path=str(store_path), request=OPERATOR)
    return {
        "role": role,
        "knowledge_status": result.get("knowledge_status"),
        "authority": result.get("authority"),
        "trading_control": result.get("trading_control"),
        "returned_count": (result.get("knowledge") or {}).get("returned_count", 0),
    }


def run_g12_production_import(
    *,
    authorization_path: str | Path,
    manifest_path: str | Path,
    indexed_at: str,
    apply: bool = False,
    backup_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    now: datetime | None = None,
) -> ImportResult:
    """The only Production entrypoint. Binds to the canonical Store only.

    This task does not call it with ``apply=True``. A future operator must
    supply a real authorization artifact and explicit backup/audit paths.
    """

    started = time.monotonic()
    try:
        guard = production_target_guard()
        authorization = load_authorization(authorization_path)
        manifest = load_candidate_manifest(manifest_path)
    except ProductionIngestError as exc:
        return _blocked_result(
            environment=PRODUCTION_ENVIRONMENT,
            error=exc.code,
            started=started,
        )
    if authorization.environment != PRODUCTION_ENVIRONMENT:
        return _blocked_result(
            environment=PRODUCTION_ENVIRONMENT,
            error="AUTHORIZATION_ENVIRONMENT_MISMATCH",
            started=started,
            authorization_id=authorization.approval_id,
            manifest_sha256=manifest.sha256,
            target=guard.identity,
        )
    return run_authorized_import(
        guard,
        authorization,
        manifest,
        indexed_at=indexed_at,
        apply=apply,
        backup_path=backup_path,
        audit_path=audit_path,
        now=now,
    )


__all__ = [
    "APPROVAL_KEY_ENV",
    "APPROVAL_KEY_FILE_ENV",
    "APPROVAL_SIGNATURE_METHOD",
    "AUTHORIZATION_SCHEMA_VERSION",
    "BackupEvidence",
    "CANDIDATE_MANIFEST_SCHEMA_VERSION",
    "CandidateManifest",
    "CandidateRecord",
    "ImportPlan",
    "ImportResult",
    "ISOLATED_ENVIRONMENT",
    "OUTCOME_BLOCKED",
    "OUTCOME_INSERTED",
    "OUTCOME_SKIPPED",
    "PRODUCTION_ENVIRONMENT",
    "PRODUCTION_INGEST_SCHEMA_VERSION",
    "ProductionAuthorization",
    "ProductionIngestError",
    "RecordResult",
    "STATUS_BLOCKED",
    "STATUS_COMPLETE",
    "STATUS_IDEMPOTENT",
    "STATUS_PREVIEW",
    "TargetGuard",
    "TargetIdentity",
    "build_import_plan",
    "canonical_authorization_bytes",
    "create_pre_import_backup",
    "inspect_target",
    "isolated_target_guard",
    "load_approval_key",
    "load_authorization",
    "load_candidate_manifest",
    "parse_authorization",
    "parse_candidate_manifest",
    "production_target_guard",
    "query_isolated_read",
    "run_authorized_import",
    "run_g12_production_import",
    "sign_authorization_payload",
    "validate_authorization",
    "validate_file_protection",
    "verify_authorization_signature",
    "write_audit_evidence",
]
