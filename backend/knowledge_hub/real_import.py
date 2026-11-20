"""Approval-gated acceptance workflow for real ChatGPT exports.

This module is an orchestrator only. It reuses the BC-11A isolated store guard,
the BC-7 preview/approval/sync engine, and the BC-5 account resolver. It does
not implement a second parser, a second importer, or a new store schema.

A real export is imported only when the caller explicitly applies an approval
manifest whose account alias, export content hash, and isolated database path
all match the observed export. Without an explicit export and a matching
approval, no store is created and no data is read or written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import sqlite3
import time
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .chatgpt_import.account import AccountError, resolve_account
from .chatgpt_sync import (
    Approval,
    ApprovalError,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    SyncLimits,
    preview_export_sync,
    sync_export,
    validate_approval,
)
from .import_readiness import (
    DEFAULT_ALLOWED_STORE_ROOT,
    PRODUCTION_RUNTIME_ROOT,
    PRODUCTION_STORE_PATH,
    ReadinessError,
    SearchProbe,
    assert_temporary_store,
)
from .knowledge_store import KnowledgeStore, StoreError
from .reader import ReaderFilters, ReaderLimits, RequestContext, open_reader


REAL_IMPORT_SCHEMA_VERSION = "tradingai-real-export-acceptance/v1"
APPROVAL_SCHEMA_VERSION = "tradingai-real-export-approval/v1"
ACCOUNT_ALIASES = ("chatgpt_account_a", "chatgpt_account_b")
OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc11b-real-import")

STATUS_PREVIEW = "PREVIEW"
STATUS_BLOCKED = "BLOCKED"
STATUS_COMPLETE = "COMPLETE"

ACCEPTANCE_NOT_RUN = "NOT_RUN"
ACCEPTANCE_PREVIEW_ONLY = "PREVIEW_ONLY"
ACCEPTANCE_PASS = "PASS"
ACCEPTANCE_BLOCKED = "BLOCKED"


class RealImportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExportValidation:
    status: str
    code: str | None
    account_alias: str
    export_name: str | None
    export_bytes: int | None
    source: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "account_alias": self.account_alias,
            "export_name": self.export_name,
            "export_bytes": self.export_bytes,
        }


@dataclass(frozen=True)
class ApprovalManifest:
    schema_version: str
    approvals: tuple[Approval, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approvals": [
                {
                    "account_alias": approval.account_alias,
                    "export_content_hash": approval.export_content_hash,
                    "store_path": approval.store_path,
                    "approved_at": approval.approved_at,
                    "approved_by": approval.approved_by,
                }
                for approval in self.approvals
            ],
        }


@dataclass(frozen=True)
class AccountImportResult:
    account_alias: str
    stage: str
    status: str
    error: str | None
    approved: bool
    imported: bool
    export_name: str | None
    export_content_hash: str | None
    export_format: str | None
    export_bytes: int | None
    preview: dict[str, Any]
    import_report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_alias": self.account_alias,
            "stage": self.stage,
            "status": self.status,
            "error": self.error,
            "approved": self.approved,
            "imported": self.imported,
            "export_name": self.export_name,
            "export_content_hash": self.export_content_hash,
            "export_format": self.export_format,
            "export_bytes": self.export_bytes,
            "preview": dict(self.preview),
            "import_report": None if self.import_report is None else dict(self.import_report),
        }


@dataclass(frozen=True)
class RealImportResult:
    schema_version: str
    mode: str
    apply: bool
    real_import_executed: bool
    real_export_acceptance: str
    store_name: str | None
    store_sha256: str | None
    store_bytes: int | None
    integrity: str | None
    store: dict[str, Any]
    accounts: tuple[AccountImportResult, ...]
    search: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "apply": self.apply,
            "real_import_executed": self.real_import_executed,
            "real_export_acceptance": self.real_export_acceptance,
            "REAL_IMPORT_EXECUTED": "YES" if self.real_import_executed else "NO",
            "REAL_EXPORT_ACCEPTANCE": self.real_export_acceptance,
            "store_name": self.store_name,
            "store_sha256": self.store_sha256,
            "store_bytes": self.store_bytes,
            "integrity": self.integrity,
            "store": dict(self.store),
            "accounts": [account.to_dict() for account in self.accounts],
            "search": [dict(item) for item in self.search],
            "errors": list(self.errors),
            "duration_seconds": self.duration_seconds,
        }


def empty_result() -> RealImportResult:
    """Return the no-input result: nothing read, nothing written."""

    return RealImportResult(
        schema_version=REAL_IMPORT_SCHEMA_VERSION,
        mode="NO_INPUT",
        apply=False,
        real_import_executed=False,
        real_export_acceptance=ACCEPTANCE_NOT_RUN,
        store_name=None,
        store_sha256=None,
        store_bytes=None,
        integrity=None,
        store={},
        accounts=(),
        search=(),
        errors=("REAL_EXPORTS_NOT_PROVIDED",),
        duration_seconds=0.0,
    )


def validate_export_source(
    source: str | Path,
    *,
    account_alias: str,
    limits: SyncLimits | None = None,
    store_path: str | Path | None = None,
) -> ExportValidation:
    """Validate one explicit export path before it is parsed."""

    try:
        account = resolve_account(account_alias)
        if account.alias not in ACCOUNT_ALIASES:
            raise RealImportError("ACCOUNT_NAMESPACE_REJECTED")
    except (AccountError, RealImportError) as exc:
        code = getattr(exc, "code", "INVALID_ACCOUNT_ALIAS")
        return ExportValidation(STATUS_ERROR, code, str(account_alias or ""), None, None)

    requested = Path(source)
    if requested.is_symlink():
        return ExportValidation(STATUS_ERROR, "EXPORT_SYMLINK_REJECTED", account.alias, requested.name, None)
    production = PRODUCTION_STORE_PATH.resolve(strict=False)
    runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    try:
        candidate = requested.resolve(strict=False)
    except (OSError, RuntimeError):
        return ExportValidation(STATUS_ERROR, "EXPORT_PATH_REJECTED", account.alias, requested.name, None)
    if candidate == production or candidate.is_relative_to(runtime_root):
        return ExportValidation(STATUS_ERROR, "PRODUCTION_EXPORT_REJECTED", account.alias, candidate.name, None)
    try:
        resolved = requested.resolve(strict=True)
    except FileNotFoundError:
        return ExportValidation(STATUS_ERROR, "EXPORT_NOT_FOUND", account.alias, requested.name, None)
    except (OSError, RuntimeError):
        return ExportValidation(STATUS_ERROR, "EXPORT_PATH_REJECTED", account.alias, requested.name, None)
    if not resolved.is_file():
        return ExportValidation(STATUS_ERROR, "EXPORT_NOT_FILE", account.alias, requested.name, None)
    if resolved.suffix.lower() != ".zip":
        return ExportValidation(STATUS_ERROR, "EXPORT_NOT_ZIP", account.alias, resolved.name, None)
    if store_path is not None and str(store_path) != "":
        try:
            store_resolved = Path(store_path).resolve(strict=False)
        except (OSError, RuntimeError):
            return ExportValidation(STATUS_ERROR, "STORE_PATH_REJECTED", account.alias, resolved.name, None)
        if resolved == store_resolved:
            return ExportValidation(STATUS_ERROR, "EXPORT_IS_STORE", account.alias, resolved.name, None)
    try:
        size = resolved.stat().st_size
    except OSError:
        return ExportValidation(STATUS_ERROR, "EXPORT_NOT_FOUND", account.alias, resolved.name, None)
    if size == 0:
        return ExportValidation(STATUS_ERROR, "EXPORT_EMPTY", account.alias, resolved.name, size)
    bounds = limits or SyncLimits()
    if size > bounds.import_limits.max_zip_bytes:
        return ExportValidation(STATUS_ERROR, "EXPORT_TOO_LARGE", account.alias, resolved.name, size)
    return ExportValidation(STATUS_OK, None, account.alias, resolved.name, size, resolved)


def parse_approval_manifest(payload: Mapping[str, Any]) -> ApprovalManifest:
    if not isinstance(payload, Mapping):
        raise RealImportError("APPROVAL_MANIFEST_INVALID")
    if payload.get("schema_version") != APPROVAL_SCHEMA_VERSION:
        raise RealImportError("APPROVAL_MANIFEST_SCHEMA_MISMATCH")
    raw_entries = payload.get("approvals")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RealImportError("APPROVAL_MANIFEST_EMPTY")
    approvals: list[Approval] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise RealImportError("APPROVAL_MANIFEST_INVALID")
        try:
            alias = str(raw["account_alias"])
            export_hash = str(raw["export_content_hash"])
            store_path = str(raw["store_path"])
            approved_at = str(raw["approved_at"])
            approved_by = str(raw.get("approved_by", "OPERATOR"))
        except KeyError:
            raise RealImportError("APPROVAL_MANIFEST_INVALID") from None
        try:
            account = resolve_account(alias)
        except AccountError as exc:
            raise RealImportError(exc.code) from None
        if account.alias not in ACCOUNT_ALIASES:
            raise RealImportError("ACCOUNT_NAMESPACE_REJECTED")
        if len(export_hash) != 64 or any(char not in "0123456789abcdef" for char in export_hash.lower()):
            raise RealImportError("APPROVAL_EXPORT_HASH_INVALID")
        if not store_path or not approved_at or not approved_by:
            raise RealImportError("APPROVAL_MANIFEST_INVALID")
        if account.alias in seen:
            raise RealImportError("APPROVAL_MANIFEST_DUPLICATE_ACCOUNT")
        seen.add(account.alias)
        approvals.append(
            Approval(
                account_alias=account.alias,
                export_content_hash=export_hash.lower(),
                store_path=store_path,
                approved_at=approved_at,
                approved_by=approved_by,
            )
        )
    return ApprovalManifest(schema_version=APPROVAL_SCHEMA_VERSION, approvals=tuple(approvals))


def load_approval_manifest(path: str | Path) -> ApprovalManifest:
    source = Path(path)
    if source.is_symlink():
        raise RealImportError("APPROVAL_MANIFEST_SYMLINK_REJECTED")
    if not source.is_file():
        raise RealImportError("APPROVAL_MANIFEST_NOT_FOUND")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RealImportError("APPROVAL_MANIFEST_INVALID") from None
    return parse_approval_manifest(payload)


def select_approval(manifest: ApprovalManifest | None, account_alias: str) -> Approval | None:
    if manifest is None:
        return None
    for approval in manifest.approvals:
        if approval.account_alias == account_alias:
            return approval
    return None


def run_real_import(
    store_path: str | Path,
    *,
    chatgpt_exports: Mapping[str, str | Path],
    approval_manifest: ApprovalManifest | Mapping[str, Any] | str | Path | None = None,
    observed_at: str,
    indexed_at: str,
    apply: bool = False,
    search_probes: Sequence[SearchProbe] = (),
    limits: SyncLimits | None = None,
    allowed_store_root: str | Path = DEFAULT_ALLOWED_STORE_ROOT,
) -> RealImportResult:
    """Validate, gate, and optionally import explicit ChatGPT exports.

    ``apply=False`` performs preview only and never writes a database. A real
    write requires ``apply=True`` plus a matching approval manifest.
    """

    if not chatgpt_exports:
        return empty_result()
    started = time.monotonic()
    if not observed_at or not isinstance(observed_at, str):
        raise RealImportError("TIMESTAMP_REQUIRED")
    if not indexed_at or not isinstance(indexed_at, str):
        raise RealImportError("TIMESTAMP_REQUIRED")
    try:
        target = assert_temporary_store(store_path, allowed_root=allowed_store_root)
    except ReadinessError as exc:
        return _guard_blocked_result(exc.code, apply=apply, started=started)
    try:
        resolved_target = target.resolve(strict=False)
    except (OSError, RuntimeError):
        return _guard_blocked_result("STORE_PATH_REJECTED", apply=apply, started=started)
    production_runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    if resolved_target == production_runtime_root or resolved_target.is_relative_to(production_runtime_root):
        return _guard_blocked_result(
            "PRODUCTION_RUNTIME_ROOT_REJECTED", apply=apply, started=started
        )

    if isinstance(approval_manifest, (str, Path)):
        try:
            manifest = load_approval_manifest(approval_manifest)
        except RealImportError as exc:
            return _guard_blocked_result(exc.code, apply=apply, started=started)
    elif isinstance(approval_manifest, Mapping):
        try:
            manifest = parse_approval_manifest(approval_manifest)
        except RealImportError as exc:
            return _guard_blocked_result(exc.code, apply=apply, started=started)
    else:
        manifest = approval_manifest

    accounts: list[AccountImportResult] = []
    prepared: list[_PreparedAccount] = []
    errors: list[str] = []
    for alias, source in chatgpt_exports.items():
        ready, blocked = _prepare_account(
            str(alias),
            source,
            target=target,
            manifest=manifest,
            observed_at=observed_at,
            apply=apply,
            limits=limits,
        )
        if blocked is not None:
            accounts.append(blocked)
            if blocked.error:
                errors.append(blocked.error)
            continue
        assert ready is not None
        prepared.append(ready)
        accounts.append(_preview_account(ready))

    if apply and errors:
        store_exists = target.is_file()
        return _finalize(
            target=target,
            apply=True,
            accounts=accounts,
            real_import_executed=False,
            acceptance=ACCEPTANCE_BLOCKED,
            store_snapshot=_store_snapshot(target) if store_exists else {},
            search=(),
            errors=tuple(errors),
            started=started,
        )

    if apply:
        if not target.is_file():
            try:
                KnowledgeStore.create(target).close()
            except StoreError as exc:
                return _guard_blocked_result(exc.code, apply=True, started=started)
        updated: list[AccountImportResult] = []
        for account in accounts:
            ready = next(
                (item for item in prepared if item.account_alias == account.account_alias),
                None,
            )
            if ready is None:
                updated.append(account)
                continue
            report = sync_export(
                ready.source,
                ready.account_alias,
                target,
                observed_at=observed_at,
                indexed_at=indexed_at,
                preview=ready.preview,
                approval=ready.approval,
                limits=limits,
                scan_scope="bc11b-real-export",
            )
            payload = report.to_dict()
            if report.status == STATUS_ERROR:
                blocked = _blocked_account(
                    ready.account_alias,
                    report.errors[0] if report.errors else "IMPORT_FAILED",
                    export_name=ready.export_name,
                    export_bytes=ready.export_bytes,
                    export_content_hash=ready.export_content_hash,
                    export_format=ready.export_format,
                    preview=ready.summary,
                    import_report=payload,
                )
                updated.append(blocked)
                errors.append(blocked.error or "IMPORT_FAILED")
            else:
                updated.append(_complete_account(ready, payload))
        accounts = updated

    store_exists = target.is_file()
    store_snapshot = _store_snapshot(target) if store_exists else {}
    search = _run_search(target, search_probes) if store_exists and apply and not errors else ()
    executed = bool(apply and any(account.imported for account in accounts))
    if not apply:
        acceptance = ACCEPTANCE_PREVIEW_ONLY
    elif accounts and all(account.status in {STATUS_OK, STATUS_PARTIAL} for account in accounts):
        acceptance = ACCEPTANCE_PASS
    else:
        acceptance = ACCEPTANCE_BLOCKED
    return _finalize(
        target=target,
        apply=bool(apply),
        accounts=accounts,
        real_import_executed=executed,
        acceptance=acceptance,
        store_snapshot=store_snapshot,
        search=tuple(search),
        errors=tuple(errors),
        started=started,
    )


@dataclass(frozen=True)
class _PreparedAccount:
    account_alias: str
    source: Path
    export_name: str | None
    export_bytes: int | None
    export_content_hash: str
    export_format: str
    preview: Any
    summary: dict[str, Any]
    approval: Approval | None
    approved: bool
    approval_error: str | None


def _prepare_account(
    account_alias: str,
    source: str | Path,
    *,
    target: Path,
    manifest: ApprovalManifest | None,
    observed_at: str,
    apply: bool,
    limits: SyncLimits | None,
) -> tuple[_PreparedAccount | None, AccountImportResult | None]:
    validation = validate_export_source(
        source,
        account_alias=account_alias,
        limits=limits,
        store_path=target,
    )
    if validation.status != STATUS_OK or validation.source is None:
        return None, _blocked_account(
            validation.account_alias,
            validation.code or "EXPORT_VALIDATION_FAILED",
            export_name=validation.export_name,
            export_bytes=validation.export_bytes,
        )

    preview = preview_export_sync(
        validation.source,
        validation.account_alias,
        store_path=target,
        observed_at=observed_at,
        limits=limits,
    )
    summary = _preview_summary(preview)
    if preview.status != STATUS_OK or preview.export_identity is None:
        return None, _blocked_account(
            validation.account_alias,
            preview.error or "PREVIEW_FAILED",
            export_name=validation.export_name,
            export_bytes=validation.export_bytes,
            preview=summary,
        )

    export_hash = preview.export_identity.export_content_hash
    approval = select_approval(manifest, validation.account_alias)
    approved = False
    approval_error: str | None = None
    if approval is not None or apply:
        try:
            validate_approval(
                approval,
                preview=preview,
                account_alias=validation.account_alias,
                export_content_hash=export_hash,
                store_path=target,
            )
            approved = True
        except ApprovalError as exc:
            approval_error = exc.code
            if apply:
                return None, _blocked_account(
                    validation.account_alias,
                    exc.code,
                    export_name=validation.export_name,
                    export_bytes=validation.export_bytes,
                    export_content_hash=export_hash,
                    export_format=preview.export_format,
                    preview=summary,
                )
    return (
        _PreparedAccount(
            account_alias=validation.account_alias,
            source=validation.source,
            export_name=validation.export_name,
            export_bytes=validation.export_bytes,
            export_content_hash=export_hash,
            export_format=preview.export_format,
            preview=preview,
            summary=summary,
            approval=approval,
            approved=approved,
            approval_error=approval_error,
        ),
        None,
    )


def _preview_account(ready: _PreparedAccount) -> AccountImportResult:
    return AccountImportResult(
        account_alias=ready.account_alias,
        stage=STATUS_PREVIEW,
        status=STATUS_PREVIEW,
        error=ready.approval_error,
        approved=ready.approved,
        imported=False,
        export_name=ready.export_name,
        export_content_hash=ready.export_content_hash,
        export_format=ready.export_format,
        export_bytes=ready.export_bytes,
        preview=ready.summary,
    )


def _complete_account(ready: _PreparedAccount, payload: dict[str, Any]) -> AccountImportResult:
    return AccountImportResult(
        account_alias=ready.account_alias,
        stage=STATUS_COMPLETE,
        status=str(payload["status"]),
        error=None,
        approved=True,
        imported=True,
        export_name=ready.export_name,
        export_content_hash=ready.export_content_hash,
        export_format=ready.export_format,
        export_bytes=ready.export_bytes,
        preview=ready.summary,
        import_report=payload,
    )


def _finalize(
    *,
    target: Path,
    apply: bool,
    accounts: list[AccountImportResult],
    real_import_executed: bool,
    acceptance: str,
    store_snapshot: dict[str, Any],
    search: tuple[dict[str, Any], ...],
    errors: tuple[str, ...],
    started: float,
) -> RealImportResult:
    store_exists = target.is_file()
    integrity = store_snapshot.get("integrity") if store_snapshot else None
    return RealImportResult(
        schema_version=REAL_IMPORT_SCHEMA_VERSION,
        mode="REAL",
        apply=bool(apply),
        real_import_executed=real_import_executed,
        real_export_acceptance=acceptance,
        store_name=target.name,
        store_sha256=_sha256(target) if store_exists else None,
        store_bytes=target.stat().st_size if store_exists else None,
        integrity=integrity,
        store=store_snapshot,
        accounts=tuple(accounts),
        search=tuple(search),
        errors=tuple(errors),
        duration_seconds=round(time.monotonic() - started, 6),
    )


def _preview_summary(preview) -> dict[str, Any]:
    return {
        "status": preview.status,
        "export_format": preview.export_format,
        "export_content_hash": preview.export_content_hash,
        "conversation_count": preview.conversation_count,
        "message_count": preview.message_count,
        "new_conversation_count": preview.new_conversation_count,
        "new_message_count": preview.new_message_count,
        "updated_message_count": preview.updated_message_count,
        "unchanged_message_count": preview.unchanged_message_count,
        "missing_conversation_count": preview.missing_conversation_count,
        "reappeared_conversation_count": preview.reappeared_conversation_count,
        "review_required_count": preview.review_required_count,
        "secret_rejected_count": preview.secret_rejected_count,
        "out_of_scope_count": preview.out_of_scope_count,
        "graph_change_count": preview.graph_change_count,
        "estimated_database_growth_bytes": preview.estimated_database_growth_bytes,
        "error": preview.error,
    }


def _blocked_account(
    account_alias: str,
    error: str,
    *,
    export_name: str | None = None,
    export_bytes: int | None = None,
    export_content_hash: str | None = None,
    export_format: str | None = None,
    preview: dict[str, Any] | None = None,
    import_report: dict[str, Any] | None = None,
) -> AccountImportResult:
    return AccountImportResult(
        account_alias=account_alias,
        stage=STATUS_BLOCKED,
        status=STATUS_BLOCKED,
        error=error,
        approved=False,
        imported=False,
        export_name=export_name,
        export_content_hash=export_content_hash,
        export_format=export_format,
        export_bytes=export_bytes,
        preview=preview or {},
        import_report=import_report,
    )


def _guard_blocked_result(error: str, *, apply: bool, started: float) -> RealImportResult:
    return RealImportResult(
        schema_version=REAL_IMPORT_SCHEMA_VERSION,
        mode="REAL",
        apply=bool(apply),
        real_import_executed=False,
        real_export_acceptance=ACCEPTANCE_BLOCKED,
        store_name=None,
        store_sha256=None,
        store_bytes=None,
        integrity=None,
        store={},
        accounts=(),
        search=(),
        errors=(error,),
        duration_seconds=round(time.monotonic() - started, 6),
    )


def _store_snapshot(path: Path) -> dict[str, Any]:
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
        by_account = {
            row["source_account"]: int(row["count"])
            for row in connection.execute(
                "SELECT source_account, count(*) AS count FROM records "
                "WHERE source_account IS NOT NULL GROUP BY source_account"
            )
        }
        by_presence = {
            row["presence"]: int(row["count"])
            for row in connection.execute(
                "SELECT presence, count(*) AS count FROM records GROUP BY presence"
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
        "by_account": by_account,
        "by_presence": by_presence,
    }


def _run_search(path: Path, probes: Sequence[SearchProbe]) -> list[dict[str, Any]]:
    reader, failure = open_reader(path, ReaderLimits(max_results=20))
    if reader is None:
        return [{"name": "OPEN", "status": failure or "NOT_AVAILABLE"}]
    results: list[dict[str, Any]] = []
    try:
        for probe in probes:
            response = reader.search(
                probe.text,
                request=OPERATOR,
                filters=probe.filters,
            )
            results.append(
                {
                    "name": probe.name,
                    "status": response.status,
                    "error_code": response.error_code,
                    "total_count": response.total_count,
                    "returned_count": response.returned_count,
                    "source_types": sorted({hit.source_type for hit in response.results}),
                    "accounts": sorted(
                        {
                            hit.source_account
                            for hit in response.results
                            if hit.source_account is not None
                        }
                    ),
                }
            )
    finally:
        reader.close()
    return results


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ACCEPTANCE_BLOCKED",
    "ACCEPTANCE_NOT_RUN",
    "ACCEPTANCE_PASS",
    "ACCEPTANCE_PREVIEW_ONLY",
    "ACCOUNT_ALIASES",
    "APPROVAL_SCHEMA_VERSION",
    "AccountImportResult",
    "ApprovalManifest",
    "ExportValidation",
    "REAL_IMPORT_SCHEMA_VERSION",
    "RealImportError",
    "RealImportResult",
    "empty_result",
    "load_approval_manifest",
    "parse_approval_manifest",
    "run_real_import",
    "select_approval",
    "validate_export_source",
]
