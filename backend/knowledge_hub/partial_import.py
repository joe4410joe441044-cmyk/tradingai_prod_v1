"""Safe partial import of explicitly approved content records.

A source-file approval selects files. It does not approve the records inside
those files. This orchestrator reads selected files, evaluates every discovered
record against the record-level approval ledger, and imports only eligible
records into an isolated store. Blocked records are reported and never written.

The module reuses the BC-3 knowledge store and FTS search. It does not create a
second schema, contact a network, or delete previously imported records.
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

from .config import CollectorConfig
from .import_readiness import (
    DEFAULT_ALLOWED_STORE_ROOT,
    PRODUCTION_RUNTIME_ROOT,
    ReadinessError,
    SearchProbe,
    assert_temporary_store,
)
from .knowledge_store import KnowledgeStore, StoreError, StoreItem
from .reader import ReaderLimits, RequestContext, open_reader
from .record_approval import (
    ApprovalLedger,
    OperatorAuthorization,
    _require_text,
)
from .report_collector import _fields_from_json, _fields_from_text
from .security import secret_bytes, secret_filename, valid_commit_sha


PARTIAL_IMPORT_SCHEMA_VERSION = "tradingai-partial-record-import/v1"
SOURCE_APPROVAL_SCHEMA_VERSION = "tradingai-source-file-approval/v1"
REPORT_SUFFIXES = frozenset({".md", ".txt", ".json"})

STATUS_NOT_PROVIDED = "NOT_PROVIDED"
STATUS_APPROVAL_REQUIRED = "SOURCE_APPROVAL_REQUIRED"
STATUS_BLOCKED = "BLOCKED"
STATUS_PARTIAL = "PARTIAL"
STATUS_COMPLETE = "COMPLETE"
STATUS_PREVIEW = "PREVIEW"

OUTCOME_ELIGIBLE = "ELIGIBLE"
OUTCOME_IMPORTED = "IMPORTED"
OUTCOME_SKIPPED = "SKIPPED"
OUTCOME_BLOCKED = "BLOCKED"
OUTCOME_DUPLICATE = "DUPLICATE"

OPERATOR = RequestContext(caller_scope="OPERATOR", caller_id="bc-record-import")


class PartialImportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SourceFileApproval:
    schema_version: str
    store_path: str
    approved_at: str
    approved_by: str
    source_paths: tuple[str, ...]
    authorized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "store_path": self.store_path,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "source_paths": list(self.source_paths),
            "authorized": self.authorized,
        }


def create_source_file_approval(
    source_paths: Sequence[str | Path],
    *,
    store_path: str | Path,
    authorization: OperatorAuthorization | None,
) -> SourceFileApproval:
    if authorization is None or authorization.authorized is not True:
        raise PartialImportError("AUTHORIZATION_REQUIRED")
    _require_text(authorization.authority, "AUTHORITY_REQUIRED")
    _require_text(authorization.authorization_id, "AUTHORIZATION_ID_REQUIRED")
    _require_text(authorization.issued_at, "AUTHORIZATION_TIMESTAMP_REQUIRED")
    paths = tuple(str(Path(item)) for item in source_paths)
    if not paths:
        raise PartialImportError("SOURCE_REQUIRED")
    return SourceFileApproval(
        schema_version=SOURCE_APPROVAL_SCHEMA_VERSION,
        store_path=str(store_path),
        approved_at=authorization.issued_at,
        approved_by=authorization.authority,
        source_paths=paths,
        authorized=True,
    )


@dataclass(frozen=True)
class DiscoveredRecord:
    record_id: str
    source_file: str
    relative_path: str
    content_hash: str
    content: str
    title: str
    fields: Mapping[str, str]
    size_bytes: int
    workstream: str | None


@dataclass(frozen=True)
class RecordOutcome:
    record_id: str
    content_hash: str
    source_file: str
    status: str
    code: str
    workstream: str | None = None
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "content_hash": self.content_hash,
            "source_file": self.source_file,
            "status": self.status,
            "code": self.code,
            "workstream": self.workstream,
            "redacted": self.redacted,
        }


@dataclass(frozen=True)
class PartialImportResult:
    schema_version: str
    status: str
    apply: bool
    source_approval_state: str
    store_name: str | None
    store_path: str | None
    store_sha256: str | None
    store_bytes: int | None
    integrity: str | None
    fts_count: int | None
    total_count: int | None
    candidate_count: int
    eligible_count: int
    imported_count: int
    skipped_count: int
    blocked_count: int
    duplicate_count: int
    outcomes: tuple[RecordOutcome, ...]
    search: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "apply": self.apply,
            "source_approval_state": self.source_approval_state,
            "store_name": self.store_name,
            "store_path": self.store_path,
            "store_sha256": self.store_sha256,
            "store_bytes": self.store_bytes,
            "integrity": self.integrity,
            "fts_count": self.fts_count,
            "total_count": self.total_count,
            "candidate_count": self.candidate_count,
            "eligible_count": self.eligible_count,
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "blocked_count": self.blocked_count,
            "duplicate_count": self.duplicate_count,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "search": [dict(item) for item in self.search],
            "errors": list(self.errors),
            "duration_seconds": self.duration_seconds,
        }


def _resolved(path: str | Path) -> str:
    try:
        return str(Path(path).resolve(strict=False))
    except (OSError, RuntimeError):
        raise PartialImportError("PATH_REJECTED") from None


def _validate_allowed_root(path: Path, roots: Sequence[str | Path]) -> str | None:
    if not roots:
        return "SOURCE_ROOT_REQUIRED"
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        return "PATH_REJECTED"
    production = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    if resolved == production or resolved.is_relative_to(production):
        return "PRODUCTION_SOURCE_REJECTED"
    allowed = tuple(Path(root).resolve(strict=False) for root in roots)
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        return "SOURCE_ROOT_NOT_ALLOWLISTED"
    return None


def validate_source_file_approval(
    approval: SourceFileApproval | Mapping[str, Any] | None,
    *,
    source_paths: Sequence[str | Path],
    store_path: str | Path,
) -> SourceFileApproval:
    if approval is None:
        raise PartialImportError("SOURCE_APPROVAL_REQUIRED")
    if isinstance(approval, Mapping):
        approval = SourceFileApproval(
            schema_version=str(approval.get("schema_version", "")),
            store_path=str(approval.get("store_path", "")),
            approved_at=str(approval.get("approved_at", "")),
            approved_by=str(approval.get("approved_by", "")),
            source_paths=tuple(str(item) for item in approval.get("source_paths", [])),
            authorized=approval.get("authorized") is True,
        )
    if approval.schema_version != SOURCE_APPROVAL_SCHEMA_VERSION:
        raise PartialImportError("SOURCE_APPROVAL_SCHEMA_MISMATCH")
    if approval.authorized is not True:
        raise PartialImportError("SOURCE_APPROVAL_NOT_AUTHORIZED")
    _require_text(approval.approved_by, "SOURCE_APPROVAL_AUTHORITY_REQUIRED")
    _require_text(approval.approved_at, "SOURCE_APPROVAL_TIMESTAMP_REQUIRED")
    if _resolved(approval.store_path) != _resolved(store_path):
        raise PartialImportError("SOURCE_APPROVAL_STORE_MISMATCH")
    approved = [_resolved(item) for item in approval.source_paths]
    requested = [_resolved(item) for item in source_paths]
    if len(set(approved)) != len(approved):
        raise PartialImportError("SOURCE_APPROVAL_DUPLICATE")
    if set(approved) != set(requested):
        raise PartialImportError("SOURCE_APPROVAL_SET_MISMATCH")
    return approval


def _relative_for(path: Path, resolved: Path, roots: Sequence[str | Path]) -> str:
    for root in roots:
        try:
            root_path = Path(root).resolve(strict=False)
            return resolved.relative_to(root_path).as_posix()
        except (OSError, ValueError):
            continue
    return path.name


def _workstream(fields: Mapping[str, str]) -> str | None:
    value = fields.get("WORKSTREAM")
    if value is None or value == "UNKNOWN" or not value.strip():
        return None
    return value.strip()[:120]


def discover_records(
    source_paths: Sequence[str | Path],
    *,
    source_roots: Sequence[str | Path],
    limits: Any | None = None,
) -> tuple[tuple[DiscoveredRecord, ...], tuple[RecordOutcome, ...]]:
    config = limits or CollectorConfig()
    records: list[DiscoveredRecord] = []
    blocked: list[RecordOutcome] = []
    seen: set[str] = set()
    for raw_path in source_paths:
        requested = Path(raw_path)
        if requested.is_symlink():
            blocked.append(_blocked_unknown(requested, "SYMLINK_REJECTED"))
            continue
        root_error = _validate_allowed_root(requested, source_roots)
        if root_error is not None:
            blocked.append(_blocked_unknown(requested, root_error))
            continue
        try:
            resolved = requested.resolve(strict=True)
        except FileNotFoundError:
            blocked.append(_blocked_unknown(requested, "SOURCE_NOT_FOUND"))
            continue
        except (OSError, RuntimeError):
            blocked.append(_blocked_unknown(requested, "SOURCE_PATH_REJECTED"))
            continue
        if not resolved.is_file():
            blocked.append(_blocked_unknown(requested, "SOURCE_NOT_FILE"))
            continue
        if secret_filename(resolved.name):
            blocked.append(_blocked_unknown(requested, "SECRET_FILENAME_EXCLUDED"))
            continue
        if resolved.suffix.lower() not in REPORT_SUFFIXES:
            blocked.append(_blocked_unknown(requested, "UNSUPPORTED_FILE_TYPE"))
            continue
        try:
            size = resolved.stat().st_size
        except OSError:
            blocked.append(_blocked_unknown(requested, "SOURCE_STAT_FAILED"))
            continue
        if size == 0:
            blocked.append(_blocked_unknown(requested, "EMPTY_FILE"))
            continue
        if size > config.max_file_bytes:
            blocked.append(_blocked_unknown(requested, "FILE_TOO_LARGE"))
            continue
        try:
            raw = resolved.read_bytes()
        except PermissionError:
            blocked.append(_blocked_unknown(requested, "PERMISSION_DENIED"))
            continue
        except OSError:
            blocked.append(_blocked_unknown(requested, "SOURCE_READ_FAILED"))
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            blocked.append(_blocked_unknown(requested, "INVALID_ENCODING"))
            continue
        if resolved.suffix.lower() == ".json":
            try:
                fields = _fields_from_json(json.loads(decoded))
            except json.JSONDecodeError:
                fields = None
        else:
            fields = _fields_from_text(decoded)
        if fields is None:
            blocked.append(_blocked_unknown(requested, "MALFORMED_REPORT"))
            continue
        content_hash = hashlib.sha256(raw).hexdigest()
        if content_hash in seen:
            continue
        seen.add(content_hash)
        relative = _relative_for(requested, resolved, source_roots)
        records.append(
            DiscoveredRecord(
                record_id=f"rec_{content_hash[:24]}",
                source_file=str(resolved),
                relative_path=relative,
                content_hash=content_hash,
                content=decoded,
                title=relative[:300],
                fields=fields,
                size_bytes=size,
                workstream=_workstream(fields),
            )
        )
    return tuple(records), tuple(blocked)


def _blocked_unknown(path: Path, code: str) -> RecordOutcome:
    return RecordOutcome(
        record_id="",
        content_hash="",
        source_file=str(path),
        status=OUTCOME_BLOCKED,
        code=code,
    )


def _build_item(
    record: DiscoveredRecord,
    *,
    content: str,
    content_hash: str,
    workstream: str | None,
    decision_record_id: str,
    redacted: bool,
    indexed_at: str,
) -> StoreItem:
    fields = record.fields
    commit_sha = fields.get("COMMIT_SHA")
    if commit_sha is not None and not valid_commit_sha(commit_sha):
        commit_sha = None
    branch = fields.get("BRANCH")
    if branch in {None, "UNKNOWN"}:
        branch = None
    worktree = fields.get("WORKTREE")
    if worktree in {None, "UNKNOWN"}:
        worktree = None
    reported_at = fields.get("REPORTED_AT")
    if reported_at in {None, "UNKNOWN"}:
        reported_at = None
    return StoreItem(
        source_type="DEVELOPMENT_REPORT",
        source_identifier=record.source_file,
        record_type=(
            "DEVELOPMENT_DECISION"
            if "decision" in record.relative_path.lower()
            else "DEVELOPMENT_REPORT"
        ),
        title=record.title,
        content=content,
        content_hash=content_hash,
        collected_at=indexed_at,
        verification_state="COLLECTED",
        truth_kind="AGENT_REPORTED",
        relative_path=record.relative_path,
        commit_sha=commit_sha,
        branch=branch,
        worktree=worktree,
        reported_at=reported_at,
        observed_at=indexed_at,
        workstream=workstream,
        metadata={
            "access_scope": "OPERATOR",
            "truth_class": "AGENT_REPORTED_HISTORY",
            "trust": "UNTRUSTED_KNOWLEDGE",
            "source_agent": "EXPLICIT",
            "runtime_truth": "NOT_ASSERTED",
            "historical_authority": "UNTRUSTED_HISTORICAL",
            "record_approval_record_id": decision_record_id,
            "record_approval_content_hash": record.content_hash,
            "redaction_status": "APPLIED" if redacted else "NOT_REQUIRED",
            "workstream_attribution": workstream or "UNKNOWN",
        },
    )


def _empty_result(*, apply: bool, error: str, started: float) -> PartialImportResult:
    return PartialImportResult(
        schema_version=PARTIAL_IMPORT_SCHEMA_VERSION,
        status=STATUS_BLOCKED,
        apply=apply,
        source_approval_state=STATUS_BLOCKED,
        store_name=None,
        store_path=None,
        store_sha256=None,
        store_bytes=None,
        integrity=None,
        fts_count=None,
        total_count=None,
        candidate_count=0,
        eligible_count=0,
        imported_count=0,
        skipped_count=0,
        blocked_count=0,
        duplicate_count=0,
        outcomes=(),
        search=(),
        errors=(error,),
        duration_seconds=round(time.monotonic() - started, 6),
    )


def run_partial_import(
    store_path: str | Path,
    *,
    source_paths: Sequence[str | Path] = (),
    source_roots: Sequence[str | Path] = (),
    source_approval: SourceFileApproval | Mapping[str, Any] | None = None,
    ledger: ApprovalLedger | None = None,
    indexed_at: str,
    apply: bool = False,
    sanitized_representations: Mapping[str, str] | None = None,
    search_probes: Sequence[SearchProbe] = (),
    limits: Any | None = None,
    allowed_store_root: str | Path = DEFAULT_ALLOWED_STORE_ROOT,
) -> PartialImportResult:
    started = time.monotonic()
    if not source_paths:
        return _empty_result(apply=apply, error="SOURCE_REQUIRED", started=started)
    if ledger is None:
        return _empty_result(apply=apply, error="APPROVAL_LEDGER_REQUIRED", started=started)
    if not indexed_at or not isinstance(indexed_at, str):
        return _empty_result(apply=apply, error="TIMESTAMP_REQUIRED", started=started)
    try:
        target = assert_temporary_store(store_path, allowed_root=allowed_store_root)
    except ReadinessError as exc:
        return _empty_result(apply=apply, error=exc.code, started=started)
    try:
        resolved_target = target.resolve(strict=False)
        runtime_root = PRODUCTION_RUNTIME_ROOT.resolve(strict=False)
    except (OSError, RuntimeError):
        return _empty_result(apply=apply, error="STORE_PATH_REJECTED", started=started)
    if resolved_target == runtime_root or resolved_target.is_relative_to(runtime_root):
        return _empty_result(
            apply=apply, error="PRODUCTION_RUNTIME_ROOT_REJECTED", started=started
        )
    try:
        validate_source_file_approval(
            source_approval, source_paths=source_paths, store_path=target
        )
    except PartialImportError as exc:
        return _empty_result(apply=apply, error=exc.code, started=started)

    sanitized = dict(sanitized_representations or {})
    discovered, discovery_blocked = discover_records(
        source_paths, source_roots=source_roots, limits=limits
    )
    outcomes: list[RecordOutcome] = list(discovery_blocked)
    prepared: list[tuple[DiscoveredRecord, StoreItem, str | None]] = []
    errors: list[str] = []
    seen_import_hashes: set[str] = set()
    duplicate_count = 0

    for record in discovered:
        eligibility = ledger.evaluate(
            content_hash=record.content_hash,
            record_id=record.record_id,
            source_file=record.source_file,
        )
        if not eligibility.eligible:
            outcomes.append(
                RecordOutcome(
                    record_id=record.record_id,
                    content_hash=record.content_hash,
                    source_file=record.source_file,
                    status=OUTCOME_BLOCKED,
                    code=eligibility.code,
                    workstream=record.workstream,
                )
            )
            errors.append(f"{record.record_id}:{eligibility.code}")
            continue
        content = record.content
        content_hash = record.content_hash
        redacted = False
        if eligibility.redaction_required:
            representation = sanitized.get(record.content_hash)
            if representation is None:
                outcomes.append(
                    RecordOutcome(
                        record_id=record.record_id,
                        content_hash=record.content_hash,
                        source_file=record.source_file,
                        status=OUTCOME_BLOCKED,
                        code="SANITIZED_REPRESENTATION_REQUIRED",
                        workstream=record.workstream,
                    )
                )
                errors.append(f"{record.record_id}:SANITIZED_REPRESENTATION_REQUIRED")
                continue
            representation_hash = hashlib.sha256(representation.encode("utf-8")).hexdigest()
            if representation_hash != eligibility.sanitized_content_hash:
                outcomes.append(
                    RecordOutcome(
                        record_id=record.record_id,
                        content_hash=record.content_hash,
                        source_file=record.source_file,
                        status=OUTCOME_BLOCKED,
                        code="SANITIZED_HASH_MISMATCH",
                        workstream=record.workstream,
                    )
                )
                errors.append(f"{record.record_id}:SANITIZED_HASH_MISMATCH")
                continue
            if secret_bytes(representation.encode("utf-8")):
                outcomes.append(
                    RecordOutcome(
                        record_id=record.record_id,
                        content_hash=record.content_hash,
                        source_file=record.source_file,
                        status=OUTCOME_BLOCKED,
                        code="SANITIZED_CONTENT_UNSAFE",
                        workstream=record.workstream,
                    )
                )
                errors.append(f"{record.record_id}:SANITIZED_CONTENT_UNSAFE")
                continue
            content = representation
            content_hash = representation_hash
            redacted = True
        elif secret_bytes(record.content.encode("utf-8")):
            outcomes.append(
                RecordOutcome(
                    record_id=record.record_id,
                    content_hash=record.content_hash,
                    source_file=record.source_file,
                    status=OUTCOME_BLOCKED,
                    code="SECRET_CONTENT_UNSANITIZED",
                    workstream=record.workstream,
                )
            )
            errors.append(f"{record.record_id}:SECRET_CONTENT_UNSANITIZED")
            continue
        if content_hash in seen_import_hashes:
            duplicate_count += 1
            outcomes.append(
                RecordOutcome(
                    record_id=record.record_id,
                    content_hash=record.content_hash,
                    source_file=record.source_file,
                    status=OUTCOME_DUPLICATE,
                    code="DUPLICATE_CONTENT",
                    workstream=record.workstream,
                    redacted=redacted,
                )
            )
            continue
        seen_import_hashes.add(content_hash)
        decision = ledger.decision_for(content_hash=record.content_hash, record_id=record.record_id)
        workstream = record.workstream or (decision.workstream if decision is not None else None)
        decision_record_id = decision.record_id if decision is not None else record.record_id
        item = _build_item(
            record,
            content=content,
            content_hash=content_hash,
            workstream=workstream,
            decision_record_id=decision_record_id,
            redacted=redacted,
            indexed_at=indexed_at,
        )
        prepared.append((record, item, decision_record_id))
        outcomes.append(
            RecordOutcome(
                record_id=record.record_id,
                content_hash=record.content_hash,
                source_file=record.source_file,
                status=OUTCOME_ELIGIBLE,
                code="ELIGIBLE",
                workstream=workstream,
                redacted=redacted,
            )
        )

    if not apply:
        return PartialImportResult(
            schema_version=PARTIAL_IMPORT_SCHEMA_VERSION,
            status=STATUS_PREVIEW,
            apply=False,
            source_approval_state="APPROVED",
            store_name=target.name,
            store_path=str(target),
            store_sha256=None,
            store_bytes=None,
            integrity=None,
            fts_count=None,
            total_count=None,
            candidate_count=len(discovered),
            eligible_count=len(prepared),
            imported_count=0,
            skipped_count=0,
            blocked_count=sum(1 for item in outcomes if item.status == OUTCOME_BLOCKED),
            duplicate_count=duplicate_count,
            outcomes=tuple(outcomes),
            search=(),
            errors=tuple(errors),
            duration_seconds=round(time.monotonic() - started, 6),
        )

    imported = skipped = 0
    if prepared:
        try:
            if not target.is_file():
                KnowledgeStore.create(target).close()
            store = KnowledgeStore.open(target)
        except StoreError as exc:
            return _empty_result(apply=True, error=exc.code, started=started)
        try:
            for record, item, _ in prepared:
                try:
                    state = store.upsert(item, indexed_at=indexed_at, scan_scope="partial-record-import")
                except StoreError as exc:
                    outcomes.append(
                        RecordOutcome(
                            record_id=record.record_id,
                            content_hash=record.content_hash,
                            source_file=record.source_file,
                            status=OUTCOME_BLOCKED,
                            code=exc.code,
                            workstream=item.workstream,
                        )
                    )
                    errors.append(f"{record.record_id}:{exc.code}")
                    continue
                if state == "SKIPPED":
                    skipped += 1
                    status = OUTCOME_SKIPPED
                else:
                    imported += 1
                    status = OUTCOME_IMPORTED
                for index, outcome in enumerate(outcomes):
                    if outcome.record_id == record.record_id:
                        outcomes[index] = RecordOutcome(
                            record_id=outcome.record_id,
                            content_hash=outcome.content_hash,
                            source_file=outcome.source_file,
                            status=status,
                            code=state,
                            workstream=outcome.workstream,
                            redacted=outcome.redacted,
                        )
                        break
            integrity = store.integrity_check()
        finally:
            store.close()
    else:
        integrity = None

    store_exists = target.is_file()
    snapshot = _store_counts(target) if store_exists else {}
    search = _run_search(target, search_probes) if store_exists else ()
    blocked = sum(1 for item in outcomes if item.status == OUTCOME_BLOCKED)
    if prepared and (imported + skipped) > 0:
        status = STATUS_COMPLETE if blocked == 0 else STATUS_PARTIAL
    elif prepared:
        status = STATUS_PARTIAL
    else:
        status = STATUS_BLOCKED
    return PartialImportResult(
        schema_version=PARTIAL_IMPORT_SCHEMA_VERSION,
        status=status,
        apply=True,
        source_approval_state="APPROVED",
        store_name=target.name,
        store_path=str(target),
        store_sha256=_sha256(target) if store_exists else None,
        store_bytes=target.stat().st_size if store_exists else None,
        integrity=integrity,
        fts_count=snapshot.get("fts"),
        total_count=snapshot.get("total"),
        candidate_count=len(discovered),
        eligible_count=len(prepared),
        imported_count=imported,
        skipped_count=skipped,
        blocked_count=blocked,
        duplicate_count=duplicate_count,
        outcomes=tuple(outcomes),
        search=tuple(search),
        errors=tuple(errors),
        duration_seconds=round(time.monotonic() - started, 6),
    )


def _store_counts(path: Path) -> dict[str, int]:
    uri = "file:" + quote(path.absolute().as_posix(), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return {}
    try:
        total = int(connection.execute("SELECT count(*) FROM records").fetchone()[0])
        fts = int(connection.execute("SELECT count(*) FROM records_fts").fetchone()[0])
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return {"total": total, "fts": fts}


def _run_search(path: Path, probes: Sequence[SearchProbe]) -> list[dict[str, Any]]:
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
                    "record_ids": sorted({hit.record_id for hit in response.results}),
                    "worktrees": sorted(
                        {
                            hit.worktree
                            for hit in response.results
                            if hit.worktree is not None
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
    "DiscoveredRecord",
    "PARTIAL_IMPORT_SCHEMA_VERSION",
    "PartialImportError",
    "PartialImportResult",
    "RecordOutcome",
    "SOURCE_APPROVAL_SCHEMA_VERSION",
    "STATUS_BLOCKED",
    "STATUS_COMPLETE",
    "STATUS_PARTIAL",
    "STATUS_PREVIEW",
    "SourceFileApproval",
    "create_source_file_approval",
    "discover_records",
    "run_partial_import",
    "validate_source_file_approval",
]
