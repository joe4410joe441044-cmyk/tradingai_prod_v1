"""Read explicit development reports from caller-named directories.

``/tmp`` itself and the home directory are not acceptable roots. Report
text is stored as data. A verdict written in the file does not become
``RUNTIME_VERIFIED``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re

from .config import DEFAULT_REPORT_ROOTS, REPORT_SUFFIXES, CollectorConfig
from .models import CollectionBatch, KnowledgeRecord
from .provenance import build_provenance, stamp
from .security import directory_inside, redact_text, secret_bytes, secret_filename


_KEYS = (
    "TASK_ID",
    "WORKSTREAM",
    "PHASE",
    "VERDICT",
    "REPORT_PATH",
    "COMMIT_SHA",
    "BRANCH",
    "WORKTREE",
    "TEST_RESULTS",
    "BLOCK_REASONS",
    "NEXT_RECOMMENDED_TASK",
    "REPORTED_AT",
    "PROVENANCE",
)
_LINE = re.compile(
    r"(?im)^(?:[-*]\s*)?(?:\*\*)?(" + "|".join(_KEYS) + r")(?:\*\*)?\s*[:=]\s*(\S.*?)\s*$"
)
_FORBIDDEN_CLAIMS = {"RUNTIME_VERIFIED", "EXCHANGE_VERIFIED"}


def _fields_from_text(text: str) -> dict[str, str]:
    found = {key: "UNKNOWN" for key in _KEYS}
    for match in _LINE.finditer(text):
        key = match.group(1).upper()
        value = redact_text(match.group(2))
        if key in found and value is not None and value not in _FORBIDDEN_CLAIMS:
            found[key] = value
    return found


def _fields_from_json(payload: object) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    found = {key: "UNKNOWN" for key in _KEYS}
    for key in _KEYS:
        raw = payload.get(key)
        if raw is None:
            raw = payload.get(key.lower())
        if not isinstance(raw, str):
            continue
        value = redact_text(raw)
        if value is not None and value not in _FORBIDDEN_CLAIMS:
            found[key] = value
    return found


def _record(
    *,
    path: Path,
    root: Path,
    status: str,
    collected_at: str,
    fields: dict[str, str],
    content_hash: str | None,
    size_bytes: int | None,
    text: str | None,
) -> KnowledgeRecord:
    reported_at = fields.get("REPORTED_AT")
    if reported_at == "UNKNOWN":
        reported_at = None
    verification = "COLLECTED" if status in {"METADATA_ONLY", "TEXT_INCLUDED"} else "UNVERIFIED"
    if status in {"MALFORMED", "SECRET_EXCLUDED", "PERMISSION_DENIED", "SYMLINK_REJECTED"}:
        verification = "REJECTED" if status != "MALFORMED" else "UNVERIFIED"
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        relative = path.name
    return KnowledgeRecord(
        provenance=build_provenance(
            source_type="DEVELOPMENT_REPORT",
            source_identifier=relative,
            collected_at=collected_at,
            truth_kind="AGENT_REPORTED",
            record_type="DEVELOPMENT_REPORT",
            verification_state=verification,
            content_hash=content_hash,
            relative_path=relative,
            reported_at=reported_at,
            observed_at=collected_at,
            branch=None if fields.get("BRANCH") in {None, "UNKNOWN"} else fields.get("BRANCH"),
            worktree=None if fields.get("WORKTREE") in {None, "UNKNOWN"} else fields.get("WORKTREE"),
            commit_sha=None if fields.get("COMMIT_SHA") in {None, "UNKNOWN"} else fields.get("COMMIT_SHA"),
        ),
        collection_status=status,
        size_bytes=size_bytes,
        fields=fields,
        text=text,
    )


def collect_reports(
    directories: tuple[Path, ...] | list[Path],
    *,
    allowed_roots: tuple[Path, ...] | None = None,
    config: CollectorConfig | None = None,
    clock=None,
) -> CollectionBatch:
    settings = config or CollectorConfig()
    collected_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    roots = allowed_roots if allowed_roots is not None else DEFAULT_REPORT_ROOTS
    if not directories:
        return CollectionBatch((), error="REPORT_ROOT_REQUIRED")
    records: list[KnowledgeRecord] = []
    stopped: str | None = None
    for directory in directories:
        requested = Path(directory)
        if requested.is_symlink():
            return CollectionBatch((), error="SYMLINK_REJECTED")
        if not any(directory_inside(requested, allowed) for allowed in roots):
            return CollectionBatch((), error="REPORT_ROOT_NOT_ALLOWLISTED")
        if not requested.is_dir():
            return CollectionBatch((), error="SOURCE_ROOT_NOT_FOUND")
        names = sorted(path.name for path in requested.iterdir() if path.is_file() and not path.is_symlink())
        for name in names:
            if len(records) >= settings.max_report_files:
                stopped = "FILE_COUNT_LIMIT"
                break
            path = requested / name
            if path.is_symlink() or secret_filename(name) or name.startswith("."):
                records.append(
                    _record(
                        path=path,
                        root=requested,
                        status="SYMLINK_REJECTED" if path.is_symlink() else "SECRET_EXCLUDED",
                        collected_at=collected_at,
                        fields={key: "UNKNOWN" for key in _KEYS},
                        content_hash=None,
                        size_bytes=None,
                        text=None,
                    )
                )
                continue
            if path.suffix.lower() not in REPORT_SUFFIXES:
                continue
            try:
                size = path.stat().st_size
            except PermissionError:
                records.append(
                    _record(
                        path=path,
                        root=requested,
                        status="PERMISSION_DENIED",
                        collected_at=collected_at,
                        fields={key: "UNKNOWN" for key in _KEYS},
                        content_hash=None,
                        size_bytes=None,
                        text=None,
                    )
                )
                continue
            if size > settings.max_file_bytes:
                records.append(
                    _record(
                        path=path,
                        root=requested,
                        status="FILE_TOO_LARGE",
                        collected_at=collected_at,
                        fields={key: "UNKNOWN" for key in _KEYS},
                        content_hash=None,
                        size_bytes=size,
                        text=None,
                    )
                )
                continue
            try:
                raw = path.read_bytes()
            except PermissionError:
                records.append(
                    _record(
                        path=path,
                        root=requested,
                        status="PERMISSION_DENIED",
                        collected_at=collected_at,
                        fields={key: "UNKNOWN" for key in _KEYS},
                        content_hash=None,
                        size_bytes=size,
                        text=None,
                    )
                )
                continue
            if secret_bytes(raw):
                records.append(
                    _record(
                        path=path,
                        root=requested,
                        status="SECRET_EXCLUDED",
                        collected_at=collected_at,
                        fields={key: "UNKNOWN" for key in _KEYS},
                        content_hash=None,
                        size_bytes=len(raw),
                        text=None,
                    )
                )
                continue
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError:
                records.append(
                    _record(
                        path=path,
                        root=requested,
                        status="UNSUPPORTED_ENCODING",
                        collected_at=collected_at,
                        fields={key: "UNKNOWN" for key in _KEYS},
                        content_hash=hashlib.sha256(raw).hexdigest(),
                        size_bytes=len(raw),
                        text=None,
                    )
                )
                continue
            fields: dict[str, str] | None
            status = "METADATA_ONLY"
            if path.suffix.lower() == ".json":
                try:
                    fields = _fields_from_json(json.loads(decoded))
                except json.JSONDecodeError:
                    fields = {key: "UNKNOWN" for key in _KEYS}
                    status = "MALFORMED"
            else:
                fields = _fields_from_text(decoded)
            if fields is None:
                fields = {key: "UNKNOWN" for key in _KEYS}
                status = "MALFORMED"
            digest = hashlib.sha256(raw).hexdigest()
            records.append(
                _record(
                    path=path,
                    root=requested,
                    status=status,
                    collected_at=collected_at,
                    fields=fields,
                    content_hash=digest,
                    size_bytes=len(raw),
                    text=decoded if settings.include_text and status != "MALFORMED" else None,
                )
            )
        if stopped:
            break
    return CollectionBatch(tuple(records), stopped_reason=stopped)
