"""Approval-gated import of explicit Cursor saved reports.

This module is an orchestrator. It reuses the BC-6 Cursor report collector, the
BC-7 preview/sync engine, the BC-3 store and FTS5 search, and the BC-11A
isolated store guard. It does not implement a second parser, a second store
schema, or a network client.

Reports are read only after an approval manifest explicitly binds the selection
manifest path, every report path, the isolated database path, the retention
policy, and the log redaction policy. An ``approved: true`` flag inside the
selection manifest is a selection declaration, not an authorization.

Imported records stay ``truth_kind=AGENT_REPORTED`` with
``authority_scope=NONE``. A verdict written inside a saved report never becomes
current runtime, account, position, or trading authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .continuous_sync import (
    AGENT_CURSOR_SAVED,
    SOURCE_KIND_REPORT_DIR,
    STATUS_ERROR,
    ContinuousSyncEngine,
    SourceSpec,
    SyncLimits,
)
from .continuous_sync.sync_checkpoint import read_checkpoints
from .import_readiness import (
    DEFAULT_ALLOWED_STORE_ROOT,
    PRODUCTION_RUNTIME_ROOT,
    PRODUCTION_STORE_PATH,
    ReadinessError,
    SearchProbe,
    assert_temporary_store,
)
from .knowledge_store import KnowledgeStore, StoreError
from .reader import ReaderLimits, RequestContext, open_reader
from .security import secret_bytes, secret_filename


CURSOR_IMPORT_SCHEMA_VERSION = "tradingai-cursor-report-import/v1"
CURSOR_APPROVAL_SCHEMA_VERSION = "tradingai-cursor-report-approval/v1"
CURSOR_SOURCE_TYPE = "CURSOR_SAVED_REPORT"
CURSOR_REPORT_SUFFIXES = frozenset({".md", ".txt"})
DEFAULT_RETENTION_POLICY = "RETAIN_UNTIL_OPERATOR_DELETE"
DEFAULT_LOG_REDACTION_POLICY = "SECRET_PATTERNS_V1"
CHECKPOINT_PREFIX = "bc11d::"

STATUS_NOT_PROVIDED = "NOT_PROVIDED"
STATUS_APPROVAL_PENDING = "SOURCES_AVAILABLE_APPROVAL_PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_IMPORT_COMPLETE = "IMPORT_COMPLETE"
STATUS_IMPORT_FAILED = "IMPORT_FAILED"

ACCEPTANCE_NOT_RUN = "NOT_RUN"
ACCEPTANCE_PREVIEW_ONLY = "PREVIEW_ONLY"
ACCEPTANCE_PASS = "PASS"
ACCEPTANCE_BLOCKED = "BLOCKED"

DATA_ORIGIN_SYNTHETIC = "SYNTHETIC"
DATA_ORIGIN_REAL = "REAL"
DATA_ORIGINS = frozenset({DATA_ORIGIN_SYNTHETIC, DATA_ORIGIN_REAL})

OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc11d-cursor-import")


class CursorImportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CursorSource:
    source_id: str
    path: Path
    source_type: str
    selected: bool = True


@dataclass(frozen=True)
class CursorManifest:
    schema_version: str
    sources: tuple[CursorSource, ...]
    manifest_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_path": None if self.manifest_path is None else str(self.manifest_path),
            "sources": [
                {
                    "source_id": source.source_id,
                    "path": str(source.path),
                    "source_type": source.source_type,
                    "selected": source.selected,
                }
                for source in self.sources
            ],
        }


@dataclass(frozen=True)
class ApprovedSource:
    source_id: str
    path: Path


@dataclass(frozen=True)
class CursorApproval:
    schema_version: str
    store_path: str
    retention_policy: str
    log_redaction_policy: str
    approved_at: str
    approved_by: str
    sources: tuple[ApprovedSource, ...]
    manifest_path: Path | None = None
    approval_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_path": None if self.manifest_path is None else str(self.manifest_path),
            "store_path": self.store_path,
            "retention_policy": self.retention_policy,
            "log_redaction_policy": self.log_redaction_policy,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "sources": [
                {"source_id": source.source_id, "path": str(source.path)}
                for source in self.sources
            ],
        }


@dataclass(frozen=True)
class SourceOutcome:
    source_id: str
    file_name: str | None
    status: str
    state: str | None = None
    error: str | None = None
    content_sha256: str | None = None
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "file_name": self.file_name,
            "status": self.status,
            "state": self.state,
            "error": self.error,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class CursorImportResult:
    schema_version: str
    status: str
    approval_state: str
    apply: bool
    data_origin: str
    store_name: str | None
    store_path: str | None
    store_sha256: str | None
    store_bytes: int | None
    integrity: str | None
    fts_available: bool | None
    import_executed: bool
    real_report_import_executed: bool
    real_report_acceptance: str
    manifest_source_count: int
    sources: tuple[SourceOutcome, ...]
    preview: dict[str, Any] | None
    sync_report: dict[str, Any] | None
    removed_sources: tuple[str, ...]
    store_snapshot: dict[str, Any]
    search: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "approval_state": self.approval_state,
            "apply": self.apply,
            "data_origin": self.data_origin,
            "store_name": self.store_name,
            "store_path": self.store_path,
            "store_sha256": self.store_sha256,
            "store_bytes": self.store_bytes,
            "integrity": self.integrity,
            "fts_available": self.fts_available,
            "import_executed": self.import_executed,
            "REAL_REPORT_IMPORT_EXECUTED": "YES" if self.real_report_import_executed else "NO",
            "REAL_REPORT_ACCEPTANCE": self.real_report_acceptance,
            "manifest_source_count": self.manifest_source_count,
            "sources": [source.to_dict() for source in self.sources],
            "preview": None if self.preview is None else dict(self.preview),
            "sync_report": None if self.sync_report is None else dict(self.sync_report),
            "removed_sources": list(self.removed_sources),
            "store_snapshot": dict(self.store_snapshot),
            "search": [dict(item) for item in self.search],
            "errors": list(self.errors),
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class _ValidatedSource:
    source: CursorSource
    resolved: Path
    suffix: str
    size_bytes: int
    content: bytes
    content_sha256: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: str | Path) -> CursorManifest:
    source = Path(path)
    if source.is_symlink():
        raise CursorImportError("MANIFEST_SYMLINK_REJECTED")
    if not source.is_file():
        raise CursorImportError("MANIFEST_NOT_FOUND")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CursorImportError("MANIFEST_INVALID") from None
    manifest = parse_manifest(payload)
    return replace(manifest, manifest_path=source.resolve(strict=True))


def parse_manifest(payload: Mapping[str, Any]) -> CursorManifest:
    if not isinstance(payload, Mapping):
        raise CursorImportError("MANIFEST_INVALID")
    if payload.get("schemaVersion") != CURSOR_IMPORT_SCHEMA_VERSION:
        raise CursorImportError("MANIFEST_SCHEMA_MISMATCH")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise CursorImportError("MANIFEST_EMPTY")
    seen: set[str] = set()
    sources: list[CursorSource] = []
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise CursorImportError("MANIFEST_INVALID")
        source_id = raw.get("sourceId")
        path = raw.get("path")
        source_type = raw.get("sourceType")
        selected = raw.get("approved")
        if not isinstance(source_id, str) or not source_id.strip():
            raise CursorImportError("SOURCE_ID_INVALID")
        if not isinstance(path, str) or not path.strip():
            raise CursorImportError("SOURCE_PATH_REQUIRED")
        if source_type != CURSOR_SOURCE_TYPE:
            raise CursorImportError("SOURCE_TYPE_REJECTED")
        if selected is not True:
            raise CursorImportError("SOURCE_NOT_SELECTED")
        source_id = source_id.strip()
        if source_id in seen:
            raise CursorImportError("DUPLICATE_SOURCE_ID")
        seen.add(source_id)
        sources.append(CursorSource(source_id=source_id, path=Path(path.strip()), source_type=CURSOR_SOURCE_TYPE))
    return CursorManifest(
        schema_version=CURSOR_IMPORT_SCHEMA_VERSION,
        sources=tuple(sources),
    )


def load_approval(path: str | Path) -> CursorApproval:
    source = Path(path)
    if source.is_symlink():
        raise CursorImportError("APPROVAL_SYMLINK_REJECTED")
    if not source.is_file():
        raise CursorImportError("APPROVAL_NOT_FOUND")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CursorImportError("APPROVAL_INVALID") from None
    approval = parse_approval(payload)
    return replace(approval, approval_path=source.resolve(strict=True))


def parse_approval(payload: Mapping[str, Any]) -> CursorApproval:
    if not isinstance(payload, Mapping):
        raise CursorImportError("APPROVAL_INVALID")
    if payload.get("schema_version") != CURSOR_APPROVAL_SCHEMA_VERSION:
        raise CursorImportError("APPROVAL_SCHEMA_MISMATCH")
    store_path = payload.get("store_path")
    retention = payload.get("retention_policy")
    redaction = payload.get("log_redaction_policy")
    approved_at = payload.get("approved_at")
    approved_by = payload.get("approved_by", "OPERATOR")
    manifest_path = payload.get("manifest_path")
    if not isinstance(store_path, str) or not store_path.strip():
        raise CursorImportError("APPROVAL_STORE_REQUIRED")
    if not isinstance(retention, str) or not retention.strip():
        raise CursorImportError("APPROVAL_RETENTION_POLICY_REQUIRED")
    if not isinstance(redaction, str) or not redaction.strip():
        raise CursorImportError("APPROVAL_REDACTION_POLICY_REQUIRED")
    if not isinstance(approved_at, str) or not approved_at.strip():
        raise CursorImportError("APPROVAL_TIMESTAMP_REQUIRED")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise CursorImportError("APPROVAL_OPERATOR_REQUIRED")
    if manifest_path is not None and not isinstance(manifest_path, str):
        raise CursorImportError("APPROVAL_INVALID")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise CursorImportError("APPROVAL_EMPTY")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    sources: list[ApprovedSource] = []
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise CursorImportError("APPROVAL_INVALID")
        source_id = raw.get("source_id", raw.get("sourceId"))
        path = raw.get("path")
        if not isinstance(source_id, str) or not source_id.strip():
            raise CursorImportError("APPROVAL_SOURCE_ID_INVALID")
        if not isinstance(path, str) or not path.strip():
            raise CursorImportError("APPROVAL_SOURCE_PATH_REQUIRED")
        source_id = source_id.strip()
        resolved_key = _resolved_key(Path(path.strip()))
        if source_id in seen_ids:
            raise CursorImportError("APPROVAL_DUPLICATE_SOURCE_ID")
        if resolved_key is not None and resolved_key in seen_paths:
            raise CursorImportError("APPROVAL_DUPLICATE_SOURCE_PATH")
        seen_ids.add(source_id)
        if resolved_key is not None:
            seen_paths.add(resolved_key)
        sources.append(ApprovedSource(source_id=source_id, path=Path(path.strip())))
    return CursorApproval(
        schema_version=CURSOR_APPROVAL_SCHEMA_VERSION,
        store_path=store_path.strip(),
        retention_policy=retention.strip(),
        log_redaction_policy=redaction.strip(),
        approved_at=approved_at.strip(),
        approved_by=approved_by.strip(),
        sources=tuple(sources),
        manifest_path=None if not manifest_path else Path(manifest_path),
    )


def _resolved_key(path: Path) -> str | None:
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError):
        return None


def _same_path(left: str | Path | None, right: str | Path | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    left_key = _resolved_key(Path(left))
    right_key = _resolved_key(Path(right))
    return left_key is not None and left_key == right_key


def validate_approval(
    approval: CursorApproval,
    *,
    manifest: CursorManifest,
    store_path: str | Path,
) -> None:
    if not _same_path(approval.manifest_path, manifest.manifest_path):
        raise CursorImportError("APPROVAL_MANIFEST_MISMATCH")
    if not _same_path(approval.store_path, store_path):
        raise CursorImportError("APPROVAL_STORE_MISMATCH")
    if not approval.retention_policy or not approval.log_redaction_policy:
        raise CursorImportError("APPROVAL_POLICY_MISSING")
    manifest_sources = {source.source_id: source for source in manifest.sources}
    approval_sources = {source.source_id: source for source in approval.sources}
    if set(manifest_sources) != set(approval_sources):
        raise CursorImportError("APPROVAL_SOURCE_SET_MISMATCH")
    for source_id, source in manifest_sources.items():
        if not _same_path(source.path, approval_sources[source_id].path):
            raise CursorImportError("APPROVAL_PATH_MISMATCH")


def _coerce_manifest(manifest: CursorManifest | Mapping[str, Any] | str | Path) -> CursorManifest:
    if isinstance(manifest, CursorManifest):
        return manifest
    if isinstance(manifest, (str, Path)):
        return load_manifest(manifest)
    if isinstance(manifest, Mapping):
        return parse_manifest(manifest)
    raise CursorImportError("MANIFEST_INVALID")


def _coerce_approval(approval: CursorApproval | Mapping[str, Any] | str | Path) -> CursorApproval:
    if isinstance(approval, CursorApproval):
        return approval
    if isinstance(approval, (str, Path)):
        return load_approval(approval)
    if isinstance(approval, Mapping):
        return parse_approval(approval)
    raise CursorImportError("APPROVAL_INVALID")


def _symlink_component(path: Path) -> bool:
    current = path
    while True:
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def validate_source_path(
    source: CursorSource,
    *,
    limits: SyncLimits | None = None,
) -> tuple[_ValidatedSource | None, str | None]:
    settings = limits or SyncLimits()
    requested = source.path
    if not requested.is_absolute():
        return None, "ABSOLUTE_PATH_REQUIRED"
    if ".." in requested.parts:
        return None, "PATH_TRAVERSAL"
    if secret_filename(requested.name):
        return None, "SECRET_EXCLUDED"
    if _symlink_component(requested):
        return None, "SYMLINK_REJECTED"
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError:
        return None, "SOURCE_NOT_FOUND"
    except (OSError, RuntimeError):
        return None, "SOURCE_PATH_REJECTED"
    production = PRODUCTION_STORE_PATH.resolve(strict=False)
    runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    if resolved == production or resolved == runtime_root or resolved.is_relative_to(runtime_root):
        return None, "PRODUCTION_SOURCE_REJECTED"
    if not resolved.is_file():
        return None, "SOURCE_NOT_FILE"
    suffix = resolved.suffix.lower()
    if suffix not in CURSOR_REPORT_SUFFIXES:
        return None, "UNSUPPORTED_FILE_TYPE"
    try:
        size = resolved.stat().st_size
    except OSError:
        return None, "SOURCE_STAT_FAILED"
    if size == 0:
        return None, "EMPTY_FILE"
    if size > settings.max_report_file_bytes:
        return None, "FILE_TOO_LARGE"
    if not os.access(resolved, os.R_OK):
        return None, "PERMISSION_DENIED"
    try:
        content = resolved.read_bytes()
    except PermissionError:
        return None, "PERMISSION_DENIED"
    except OSError:
        return None, "SOURCE_READ_FAILED"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return None, "INVALID_ENCODING"
    if secret_bytes(content):
        return None, "SECRET_EXCLUDED"
    return (
        _ValidatedSource(
            source=source,
            resolved=resolved,
            suffix=suffix,
            size_bytes=size,
            content=content,
            content_sha256=_sha256_bytes(content),
        ),
        None,
    )


def _staged_name(source_id: str, suffix: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", source_id).strip("._-") or "report"
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:8]
    return f"{safe[:48]}-{digest}{suffix}"


def _checkpoint_id(source_id: str) -> str:
    return f"{CHECKPOINT_PREFIX}{source_id}"


def _original_id(checkpoint_id: str) -> str:
    return checkpoint_id[len(CHECKPOINT_PREFIX) :]


def _stage(
    validated: Sequence[_ValidatedSource],
    staging_root: Path,
) -> tuple[tuple[SourceSpec, ...], dict[str, _ValidatedSource], dict[str, str]]:
    specs: list[SourceSpec] = []
    by_checkpoint: dict[str, _ValidatedSource] = {}
    names: dict[str, str] = {}
    for index, item in enumerate(validated):
        directory = staging_root / f"source_{index:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        name = _staged_name(item.source.source_id, item.suffix)
        (directory / name).write_bytes(item.content)
        checkpoint_id = _checkpoint_id(item.source.source_id)
        specs.append(
            SourceSpec(
                path=directory,
                kind=SOURCE_KIND_REPORT_DIR,
                identifier=checkpoint_id,
                agent=AGENT_CURSOR_SAVED,
            )
        )
        by_checkpoint[checkpoint_id] = item
        names[item.source.source_id] = name
    return tuple(specs), by_checkpoint, names


def _effective_limits(limits: SyncLimits | None, staging_root: Path) -> SyncLimits:
    base = limits or SyncLimits()
    return replace(
        base,
        max_report_files=1,
        allowed_report_roots=(staging_root,),
    )


def _assert_not_production_inode(target: Path) -> None:
    if not target.exists() or not PRODUCTION_STORE_PATH.exists():
        return
    try:
        target_stat = target.stat()
        production_stat = PRODUCTION_STORE_PATH.stat()
    except OSError:
        return
    if (target_stat.st_dev, target_stat.st_ino) == (production_stat.st_dev, production_stat.st_ino):
        raise CursorImportError("PRODUCTION_STORE_REJECTED")


def _removed_sources(store_path: Path, current: set[str]) -> tuple[str, ...]:
    known = read_checkpoints(store_path)
    previous = {
        checkpoint_id
        for (kind, checkpoint_id) in known
        if kind == SOURCE_KIND_REPORT_DIR and checkpoint_id.startswith(CHECKPOINT_PREFIX)
    }
    return tuple(sorted(_original_id(item) for item in previous - current))


def _store_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    uri = "file:" + quote(path.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return {}
    connection.row_factory = sqlite3.Row
    try:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        total = int(connection.execute("SELECT count(*) FROM records").fetchone()[0])
        fts = int(connection.execute("SELECT count(*) FROM records_fts").fetchone()[0])
        by_source = {
            row["source_type"]: int(row["count"])
            for row in connection.execute(
                "SELECT source_type, count(*) AS count FROM records GROUP BY source_type"
            )
        }
        by_presence = {
            row["presence"]: int(row["count"])
            for row in connection.execute(
                "SELECT presence, count(*) AS count FROM records GROUP BY presence"
            )
        }
        by_truth = {
            row["truth_kind"]: int(row["count"])
            for row in connection.execute(
                "SELECT truth_kind, count(*) AS count FROM records GROUP BY truth_kind"
            )
        }
        by_authority = {
            row["authority_scope"]: int(row["count"])
            for row in connection.execute(
                "SELECT authority_scope, count(*) AS count FROM records GROUP BY authority_scope"
            )
        }
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return {
        "user_version": user_version,
        "integrity": "OK" if integrity == "ok" else str(integrity),
        "total": total,
        "fts": fts,
        "by_source_type": by_source,
        "by_presence": by_presence,
        "by_truth_kind": by_truth,
        "by_authority": by_authority,
    }


def _fts_available(path: Path) -> bool:
    if not path.is_file():
        return False
    uri = "file:" + quote(path.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return False
    try:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records_fts'"
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def _run_search(path: Path, probes: Sequence[SearchProbe]) -> list[dict[str, Any]]:
    if not probes:
        return []
    reader, failure = open_reader(path, ReaderLimits(max_results=20))
    if reader is None:
        return [{"name": "OPEN", "status": failure or "NOT_AVAILABLE"}]
    results: list[dict[str, Any]] = []
    try:
        for probe in probes:
            response = reader.search(probe.text, request=OPERATOR, filters=probe.filters)
            results.append(
                {
                    "name": probe.name,
                    "query": probe.text,
                    "status": response.status,
                    "error_code": response.error_code,
                    "total_count": response.total_count,
                    "returned_count": response.returned_count,
                    "source_types": sorted({hit.source_type for hit in response.results}),
                    "truth_kinds": sorted({hit.truth_kind for hit in response.results}),
                    "authority_scopes": sorted({hit.authority_scope for hit in response.results}),
                    "presences": sorted({hit.presence for hit in response.results}),
                    "source_identifiers": sorted({hit.source_identifier for hit in response.results}),
                    "record_ids": sorted({hit.record_id for hit in response.results}),
                }
            )
    finally:
        reader.close()
    return results


def empty_result() -> CursorImportResult:
    return CursorImportResult(
        schema_version=CURSOR_IMPORT_SCHEMA_VERSION,
        status=STATUS_NOT_PROVIDED,
        approval_state=STATUS_NOT_PROVIDED,
        apply=False,
        data_origin=DATA_ORIGIN_SYNTHETIC,
        store_name=None,
        store_path=None,
        store_sha256=None,
        store_bytes=None,
        integrity=None,
        fts_available=None,
        import_executed=False,
        real_report_import_executed=False,
        real_report_acceptance=ACCEPTANCE_NOT_RUN,
        manifest_source_count=0,
        sources=(),
        preview=None,
        sync_report=None,
        removed_sources=(),
        store_snapshot={},
        search=(),
        errors=("MANIFEST_NOT_PROVIDED",),
        duration_seconds=0.0,
    )


def _failed(
    error: str,
    *,
    started: float,
    apply: bool,
    data_origin: str,
    manifest: CursorManifest | None = None,
    approval_state: str = STATUS_IMPORT_FAILED,
    sources: tuple[SourceOutcome, ...] = (),
    errors: tuple[str, ...] | None = None,
) -> CursorImportResult:
    return CursorImportResult(
        schema_version=CURSOR_IMPORT_SCHEMA_VERSION,
        status=STATUS_IMPORT_FAILED,
        approval_state=approval_state,
        apply=bool(apply),
        data_origin=data_origin,
        store_name=None,
        store_path=None,
        store_sha256=None,
        store_bytes=None,
        integrity=None,
        fts_available=None,
        import_executed=False,
        real_report_import_executed=False,
        real_report_acceptance=ACCEPTANCE_BLOCKED if data_origin == DATA_ORIGIN_REAL else ACCEPTANCE_NOT_RUN,
        manifest_source_count=0 if manifest is None else len(manifest.sources),
        sources=sources,
        preview=None,
        sync_report=None,
        removed_sources=(),
        store_snapshot={},
        search=(),
        errors=errors if errors is not None else (error,),
        duration_seconds=round(time.monotonic() - started, 6),
    )


def run_cursor_report_import(
    store_path: str | Path,
    *,
    manifest: CursorManifest | Mapping[str, Any] | str | Path | None = None,
    approval: CursorApproval | Mapping[str, Any] | str | Path | None = None,
    indexed_at: str,
    apply: bool = False,
    data_origin: str = DATA_ORIGIN_SYNTHETIC,
    search_probes: Sequence[SearchProbe] = (),
    limits: SyncLimits | None = None,
    allowed_store_root: str | Path = DEFAULT_ALLOWED_STORE_ROOT,
) -> CursorImportResult:
    started = time.monotonic()
    if data_origin not in DATA_ORIGINS:
        raise CursorImportError("DATA_ORIGIN_INVALID")
    if manifest is None:
        return empty_result()
    if not indexed_at or not isinstance(indexed_at, str):
        return _failed("TIMESTAMP_REQUIRED", started=started, apply=apply, data_origin=data_origin)
    try:
        resolved_manifest = _coerce_manifest(manifest)
    except CursorImportError as exc:
        return _failed(exc.code, started=started, apply=apply, data_origin=data_origin)

    if approval is None:
        pending = tuple(
            SourceOutcome(
                source_id=source.source_id,
                file_name=source.path.name,
                status=STATUS_APPROVAL_PENDING,
            )
            for source in resolved_manifest.sources
        )
        return CursorImportResult(
            schema_version=CURSOR_IMPORT_SCHEMA_VERSION,
            status=STATUS_APPROVAL_PENDING,
            approval_state=STATUS_APPROVAL_PENDING,
            apply=bool(apply),
            data_origin=data_origin,
            store_name=None,
            store_path=None,
            store_sha256=None,
            store_bytes=None,
            integrity=None,
            fts_available=None,
            import_executed=False,
            real_report_import_executed=False,
            real_report_acceptance=ACCEPTANCE_NOT_RUN,
            manifest_source_count=len(resolved_manifest.sources),
            sources=pending,
            preview=None,
            sync_report=None,
            removed_sources=(),
            store_snapshot={},
            search=(),
            errors=("APPROVAL_REQUIRED",),
            duration_seconds=round(time.monotonic() - started, 6),
        )

    try:
        resolved_approval = _coerce_approval(approval)
    except CursorImportError as exc:
        return _failed(
            exc.code,
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
        )

    try:
        target = assert_temporary_store(store_path, allowed_root=allowed_store_root)
    except ReadinessError as exc:
        return _failed(
            exc.code,
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
        )
    try:
        resolved_target = target.resolve(strict=False)
        runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    except (OSError, RuntimeError):
        return _failed(
            "STORE_PATH_REJECTED",
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
        )
    if resolved_target == runtime_root or resolved_target.is_relative_to(runtime_root):
        return _failed(
            "PRODUCTION_RUNTIME_ROOT_REJECTED",
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
        )
    try:
        _assert_not_production_inode(target)
    except CursorImportError as exc:
        return _failed(
            exc.code,
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
        )

    try:
        validate_approval(resolved_approval, manifest=resolved_manifest, store_path=target)
    except CursorImportError as exc:
        return _failed(
            exc.code,
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
        )

    validated: list[_ValidatedSource] = []
    source_errors: list[str] = []
    failed_sources: list[SourceOutcome] = []
    for source in resolved_manifest.sources:
        item, code = validate_source_path(source, limits=limits)
        if item is None:
            source_errors.append(f"{source.source_id}:{code}")
            failed_sources.append(
                SourceOutcome(
                    source_id=source.source_id,
                    file_name=source.path.name,
                    status="REJECTED",
                    error=code,
                )
            )
            continue
        validated.append(item)
    resolved_paths = [str(item.resolved) for item in validated]
    if len(set(resolved_paths)) != len(resolved_paths):
        source_errors.append("DUPLICATE_SOURCE_PATH")
    if source_errors:
        return _failed(
            source_errors[0],
            started=started,
            apply=apply,
            data_origin=data_origin,
            manifest=resolved_manifest,
            sources=tuple(failed_sources),
            errors=tuple(source_errors),
        )

    staging_root: Path | None = None
    try:
        staging_root = Path(
            tempfile.mkdtemp(prefix="bc11d-cursor-staging-", dir=str(Path(allowed_store_root)))
        )
        os.chmod(staging_root, 0o700)
        specs, by_checkpoint, names = _stage(validated, staging_root)
        effective = _effective_limits(limits, staging_root)
        engine = ContinuousSyncEngine(limits=effective)

        removed = _removed_sources(target, {spec.identifier for spec in specs})

        preview = engine.preview(specs, store_path=target)
        preview_entries = {
            entry.get("source_id"): entry for entry in preview.entries if entry.get("source_id")
        }

        if not apply:
            outcomes: list[SourceOutcome] = []
            for spec in specs:
                item = by_checkpoint[spec.identifier]
                entry = preview_entries.get(spec.identifier, {})
                outcomes.append(
                    SourceOutcome(
                        source_id=item.source.source_id,
                        file_name=names[item.source.source_id],
                        status=STATUS_APPROVED,
                        state=entry.get("state"),
                        content_sha256=item.content_sha256,
                        size_bytes=item.size_bytes,
                    )
                )
            return CursorImportResult(
                schema_version=CURSOR_IMPORT_SCHEMA_VERSION,
                status=STATUS_APPROVED,
                approval_state=STATUS_APPROVED,
                apply=False,
                data_origin=data_origin,
                store_name=target.name,
                store_path=str(target),
                store_sha256=_sha256_file(target) if target.is_file() else None,
                store_bytes=target.stat().st_size if target.is_file() else None,
                integrity=None,
                fts_available=None,
                import_executed=False,
                real_report_import_executed=False,
                real_report_acceptance=(
                    ACCEPTANCE_PREVIEW_ONLY if data_origin == DATA_ORIGIN_REAL else ACCEPTANCE_NOT_RUN
                ),
                manifest_source_count=len(resolved_manifest.sources),
                sources=tuple(outcomes),
                preview=preview.to_dict(),
                sync_report=None,
                removed_sources=removed,
                store_snapshot=_store_snapshot(target),
                search=(),
                errors=(),
                duration_seconds=round(time.monotonic() - started, 6),
            )

        if not target.is_file():
            try:
                KnowledgeStore.create(target).close()
            except StoreError as exc:
                return _failed(
                    exc.code,
                    started=started,
                    apply=True,
                    data_origin=data_origin,
                    manifest=resolved_manifest,
                    sources=tuple(failed_sources),
                )

        store = KnowledgeStore.open(target)
        try:
            try:
                report = engine.sync(
                    specs,
                    store,
                    store_path=target,
                    indexed_at=indexed_at,
                    scan_scope="bc11d-cursor",
                )
            except StoreError as exc:
                return _failed(
                    exc.code,
                    started=started,
                    apply=True,
                    data_origin=data_origin,
                    manifest=resolved_manifest,
                    sources=tuple(failed_sources),
                )
            integrity = store.integrity_check()
        finally:
            store.close()

        sync_payload = report.to_dict()
        sync_failed = (
            report.status == STATUS_ERROR
            or bool(report.errors)
            or report.rejected > 0
            or report.rejected_source_count > 0
            or report.missing_source_count > 0
        )

        outcomes = []
        for spec in specs:
            item = by_checkpoint[spec.identifier]
            entry = preview_entries.get(spec.identifier, {})
            state = entry.get("state")
            if sync_failed:
                status = "FAILED"
                error = report.errors[0] if report.errors else "SYNC_FAILED"
            elif state == "UNCHANGED":
                status = "SKIPPED"
                error = None
            elif state in {"NEW", "UPDATED"}:
                status = "IMPORTED"
                error = None
            else:
                status = "IMPORTED"
                error = None
            outcomes.append(
                SourceOutcome(
                    source_id=item.source.source_id,
                    file_name=names[item.source.source_id],
                    status=status,
                    state=state,
                    error=error,
                    content_sha256=item.content_sha256,
                    size_bytes=item.size_bytes,
                )
            )

        snapshot = _store_snapshot(target)
        import_executed = any(outcome.status in {"IMPORTED", "SKIPPED"} for outcome in outcomes)
        search = _run_search(target, search_probes)
        real_import = bool(import_executed and data_origin == DATA_ORIGIN_REAL)
        if data_origin != DATA_ORIGIN_REAL:
            real_acceptance = ACCEPTANCE_NOT_RUN
        elif sync_failed:
            real_acceptance = ACCEPTANCE_BLOCKED
        else:
            real_acceptance = ACCEPTANCE_PASS
        return CursorImportResult(
            schema_version=CURSOR_IMPORT_SCHEMA_VERSION,
            status=STATUS_IMPORT_FAILED if sync_failed else STATUS_IMPORT_COMPLETE,
            approval_state=STATUS_APPROVED,
            apply=True,
            data_origin=data_origin,
            store_name=target.name,
            store_path=str(target),
            store_sha256=_sha256_file(target) if target.is_file() else None,
            store_bytes=target.stat().st_size if target.is_file() else None,
            integrity=integrity,
            fts_available=_fts_available(target),
            import_executed=import_executed,
            real_report_import_executed=real_import,
            real_report_acceptance=real_acceptance,
            manifest_source_count=len(resolved_manifest.sources),
            sources=tuple(outcomes),
            preview=preview.to_dict(),
            sync_report=sync_payload,
            removed_sources=removed,
            store_snapshot=snapshot,
            search=tuple(search),
            errors=tuple(report.errors) if sync_failed else (),
            duration_seconds=round(time.monotonic() - started, 6),
        )
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)


def build_synthetic_cursor_reports(root: str | Path) -> dict[str, Path]:
    """Write three synthetic Cursor saved reports under ``root``."""

    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    reports = {
        "report_a": directory / "cursor_report_a.md",
        "report_b": directory / "cursor_report_b.txt",
        "report_c": directory / "cursor_report_c.md",
    }
    reports["report_a"].write_text(
        "\n".join(
            [
                "TASK_ID: TEST-CURSOR-A",
                "VERDICT: PASS",
                "SOURCE: CURSOR_SAVED_REPORT",
                "cursoralphamarker synthetic saved report",
            ]
        ),
        encoding="utf-8",
    )
    reports["report_b"].write_text(
        "\n".join(
            [
                "TASK_ID: TEST-CURSOR-B",
                "VERDICT: BLOCKED",
                "SOURCE: CURSOR_SAVED_REPORT",
                "cursorbetamarker synthetic saved report",
            ]
        ),
        encoding="utf-8",
    )
    reports["report_c"].write_text(
        "\n".join(
            [
                "TASK_ID: TEST-CURSOR-C",
                "VERDICT: PASS",
                "SOURCE: CURSOR_SAVED_REPORT",
                "cursorcharliecharlie synthetic saved report",
            ]
        ),
        encoding="utf-8",
    )
    return reports


__all__ = [
    "ACCEPTANCE_BLOCKED",
    "ACCEPTANCE_NOT_RUN",
    "ACCEPTANCE_PASS",
    "ACCEPTANCE_PREVIEW_ONLY",
    "CURSOR_APPROVAL_SCHEMA_VERSION",
    "CURSOR_IMPORT_SCHEMA_VERSION",
    "CURSOR_REPORT_SUFFIXES",
    "CURSOR_SOURCE_TYPE",
    "CursorApproval",
    "CursorImportError",
    "CursorImportResult",
    "CursorManifest",
    "CursorSource",
    "DATA_ORIGIN_REAL",
    "DATA_ORIGIN_SYNTHETIC",
    "ApprovedSource",
    "SourceOutcome",
    "STATUS_APPROVAL_PENDING",
    "STATUS_APPROVED",
    "STATUS_IMPORT_COMPLETE",
    "STATUS_IMPORT_FAILED",
    "STATUS_NOT_PROVIDED",
    "build_synthetic_cursor_reports",
    "empty_result",
    "load_approval",
    "load_manifest",
    "parse_approval",
    "parse_manifest",
    "run_cursor_report_import",
    "validate_approval",
    "validate_source_path",
]
