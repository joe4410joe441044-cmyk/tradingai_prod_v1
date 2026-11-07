"""Allowlisted, read-only source metadata.

The walk starts at the configured prefixes. It does not start at the
repository root, and it does not read ``.git`` internals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os

from .config import SOURCE_SUFFIXES, CollectorConfig
from .git_collector import default_git_runner, read_head
from .models import CollectionBatch, KnowledgeRecord
from .provenance import build_provenance, stamp
from .security import (
    PathRejected,
    allowed_by_prefix,
    assert_allow_prefix,
    contained_file,
    normalize_relative,
    path_is_denied,
    secret_bytes,
    secret_filename,
)


def _record_type(relative: str) -> tuple[str, str]:
    name = relative.rsplit("/", 1)[-1].upper()
    if relative.startswith("docs/") and ("SPEC" in name or "ARCHITECTURE" in name):
        return "SPECIFICATION", "UNKNOWN"
    if relative.startswith("docs/"):
        return "DOCUMENT", "UNKNOWN"
    return "SOURCE_FILE", "SOURCE_TRUTH"


def _one(
    *,
    root: Path,
    relative: str,
    status: str,
    collected_at: str,
    commit_sha: str | None,
    branch: str | None,
    content_hash: str | None = None,
    size_bytes: int | None = None,
    modified_at: str | None = None,
    text: str | None = None,
    verification: str = "COLLECTED",
) -> KnowledgeRecord:
    record_type, truth_kind = _record_type(relative) if status in {
        "METADATA_ONLY",
        "TEXT_INCLUDED",
        "UNSUPPORTED_ENCODING",
    } else ("SOURCE_FILE", "UNKNOWN")
    if status != "METADATA_ONLY" and status != "TEXT_INCLUDED" and status != "UNSUPPORTED_ENCODING":
        verification = "REJECTED" if status not in {"SECRET_EXCLUDED"} else "UNVERIFIED"
        truth_kind = "UNKNOWN"
        record_type = "SOURCE_FILE"
    return KnowledgeRecord(
        provenance=build_provenance(
            source_type="SOURCE_FILE",
            source_identifier=relative,
            collected_at=collected_at,
            truth_kind=truth_kind,
            record_type=record_type,
            verification_state=verification,
            content_hash=content_hash,
            relative_path=relative,
            commit_sha=commit_sha,
            worktree=str(root),
            observed_at=collected_at,
            branch=branch,
        ),
        collection_status=status,
        size_bytes=size_bytes,
        modified_at=modified_at,
        text=text,
    )


def _read_file(path: Path, limit: int, include_text: bool) -> tuple[str, str | None, str | None, int]:
    try:
        size = path.stat().st_size
    except PermissionError:
        return "PERMISSION_DENIED", None, None, 0
    except OSError:
        return "PATH_REJECTED", None, None, 0
    if size > limit:
        return "FILE_TOO_LARGE", None, None, size
    try:
        raw = path.read_bytes()
    except PermissionError:
        return "PERMISSION_DENIED", None, None, size
    except OSError:
        return "PATH_REJECTED", None, None, size
    if len(raw) > limit:
        return "FILE_TOO_LARGE", None, None, len(raw)
    if secret_bytes(raw):
        return "SECRET_EXCLUDED", None, None, len(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if not include_text:
        return "METADATA_ONLY", digest, None, len(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "UNSUPPORTED_ENCODING", digest, None, len(raw)
    return "TEXT_INCLUDED", digest, text, len(raw)


def _modified(path: Path) -> str | None:
    try:
        moment = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None
    return moment.isoformat()


def collect_source_file(
    root: Path,
    relative_path: str,
    *,
    config: CollectorConfig | None = None,
    clock=None,
    commit_sha: str | None = None,
) -> CollectionBatch:
    settings = config or CollectorConfig()
    collected_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    base = Path(root)
    try:
        prefixes = tuple(assert_allow_prefix(prefix) for prefix in settings.allow_prefixes)
        parts = normalize_relative(relative_path)
    except PathRejected as rejected:
        return CollectionBatch((), error=rejected.code)
    relative = "/".join(parts)
    denial = path_is_denied(parts)
    if denial is not None or not allowed_by_prefix(relative, prefixes):
        code = denial or "NOT_ALLOWLISTED"
        record = _one(
            root=base,
            relative=relative,
            status=code,
            collected_at=collected_at,
            commit_sha=None,
            branch=None,
        )
        return CollectionBatch((record,), error=code)
    suffix = Path(relative).suffix.lower()
    if suffix not in SOURCE_SUFFIXES:
        record = _one(
            root=base,
            relative=relative,
            status="NOT_ALLOWLISTED",
            collected_at=collected_at,
            commit_sha=None,
            branch=None,
        )
        return CollectionBatch((record,), error="NOT_ALLOWLISTED")
    try:
        file_path = contained_file(base, parts)
    except PathRejected as rejected:
        record = _one(
            root=base,
            relative=relative,
            status=rejected.code,
            collected_at=collected_at,
            commit_sha=None,
            branch=None,
        )
        return CollectionBatch((record,), error=rejected.code)
    status, digest, text, size = _read_file(file_path, settings.max_file_bytes, settings.include_text)
    record = _one(
        root=base,
        relative=relative,
        status=status,
        collected_at=collected_at,
        commit_sha=commit_sha,
        branch=None,
        content_hash=digest,
        size_bytes=size,
        modified_at=_modified(file_path),
        text=text,
    )
    error = None if status in {"METADATA_ONLY", "TEXT_INCLUDED", "UNSUPPORTED_ENCODING"} else status
    return CollectionBatch((record,), error=error)


def collect_sources(
    root: Path,
    *,
    config: CollectorConfig | None = None,
    clock=None,
    git_runner=default_git_runner,
    time_fn=None,
) -> CollectionBatch:
    settings = config or CollectorConfig()
    collected_at = stamp(clock or (lambda: datetime.now(timezone.utc)))
    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        return CollectionBatch((), error="SOURCE_ROOT_NOT_FOUND")
    try:
        prefixes = tuple(assert_allow_prefix(prefix) for prefix in settings.allow_prefixes)
    except PathRejected as rejected:
        return CollectionBatch((), error=rejected.code)

    commit_sha = read_head(base, config=settings, runner=git_runner)

    def now() -> float:
        if time_fn is not None:
            return float(time_fn())
        return datetime.now(timezone.utc).timestamp()

    deadline = now() + settings.timeout_seconds if settings.timeout_seconds > 0 else None
    records: list[KnowledgeRecord] = []
    total = 0
    stopped: str | None = None
    seen: set[str] = set()

    for prefix in prefixes:
        if stopped:
            break
        start = base.joinpath(*prefix[:-1].split("/"))
        if start.is_symlink():
            records.append(
                _one(
                    root=base,
                    relative=prefix[:-1],
                    status="SYMLINK_REJECTED",
                    collected_at=collected_at,
                    commit_sha=commit_sha,
                    branch=None,
                )
            )
            continue
        if not start.exists():
            continue
        for directory, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in {".git", "node_modules", "dist", "venv", "__pycache__", "logs"}
                and not name.startswith(".")
                and not secret_filename(name)
                and not (Path(directory) / name).is_symlink()
            ]
            current = Path(directory)
            if current.is_symlink():
                continue
            for name in filenames:
                if deadline is not None and now() > deadline:
                    stopped = "TIMEOUT"
                    break
                if len(records) >= settings.max_files:
                    stopped = "FILE_COUNT_LIMIT"
                    break
                relative_path = current.joinpath(name).relative_to(base).as_posix()
                if relative_path in seen:
                    continue
                seen.add(relative_path)
                try:
                    parts = normalize_relative(relative_path)
                except PathRejected:
                    continue
                denial = path_is_denied(parts)
                if denial is not None or not allowed_by_prefix(relative_path, prefixes):
                    if denial == "SECRET_EXCLUDED":
                        records.append(
                            _one(
                                root=base,
                                relative=relative_path,
                                status="SECRET_EXCLUDED",
                                collected_at=collected_at,
                                commit_sha=commit_sha,
                                branch=None,
                            )
                        )
                    continue
                if Path(name).suffix.lower() not in SOURCE_SUFFIXES:
                    continue
                try:
                    file_path = contained_file(base, parts)
                except PathRejected as rejected:
                    records.append(
                        _one(
                            root=base,
                            relative=relative_path,
                            status=rejected.code,
                            collected_at=collected_at,
                            commit_sha=commit_sha,
                            branch=None,
                        )
                    )
                    continue
                try:
                    size = file_path.stat().st_size
                except PermissionError:
                    records.append(
                        _one(
                            root=base,
                            relative=relative_path,
                            status="PERMISSION_DENIED",
                            collected_at=collected_at,
                            commit_sha=commit_sha,
                            branch=None,
                        )
                    )
                    continue
                except OSError:
                    continue
                if total + size > settings.max_total_bytes:
                    stopped = "TOTAL_SIZE_LIMIT"
                    break
                status, digest, text, read_size = _read_file(
                    file_path,
                    settings.max_file_bytes,
                    settings.include_text,
                )
                total += read_size
                records.append(
                    _one(
                        root=base,
                        relative=relative_path,
                        status=status,
                        collected_at=collected_at,
                        commit_sha=commit_sha,
                        branch=None,
                        content_hash=digest,
                        size_bytes=read_size,
                        modified_at=_modified(file_path),
                        text=text,
                    )
                )
            if stopped:
                break
    return CollectionBatch(tuple(records), stopped_reason=stopped)
