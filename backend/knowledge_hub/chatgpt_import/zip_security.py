"""Read-only ZIP access with explicit bounds.

The ZIP is never extracted. Only the single ``conversations.json`` entry is
read, and only after the whole archive passes the path, link, duplicate, size,
and compression-ratio checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import re
import stat
import zipfile

from .models import ImportLimits


_CONVERSATIONS = "conversations.json"
_DRIVE = re.compile(r"^[A-Za-z]:")


class ZipSecurityError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ZipPayload:
    data: bytes | None
    entry_name: str | None
    error: str | None = None


def _check_name(name: str) -> str:
    if not isinstance(name, str) or name == "" or "\x00" in name:
        raise ZipSecurityError("EMPTY_ENTRY")
    if name.startswith(("/", "\\")) or _DRIVE.match(name):
        raise ZipSecurityError("ABSOLUTE_PATH")
    normalized = name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts:
        raise ZipSecurityError("EMPTY_ENTRY")
    if any(part == ".." for part in parts):
        raise ZipSecurityError("PATH_TRAVERSAL")
    return "/".join(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _is_encrypted(info: zipfile.ZipInfo) -> bool:
    return bool(info.flag_bits & 0x1)


def read_conversations_json(source: str | Path | bytes, limits: ImportLimits | None = None) -> ZipPayload:
    bounds = limits or ImportLimits()
    if isinstance(source, (bytes, bytearray, memoryview)):
        raw = bytes(source)
        if len(raw) > bounds.max_zip_bytes:
            return ZipPayload(None, None, "ZIP_TOO_LARGE")
        stream = io.BytesIO(raw)
        try:
            return _read_stream(stream, bounds)
        finally:
            stream.close()
    path = Path(source)
    if path.is_symlink() or not path.exists() or not path.is_file():
        return ZipPayload(None, None, "SOURCE_NOT_FOUND")
    try:
        if path.stat().st_size > bounds.max_zip_bytes:
            return ZipPayload(None, None, "ZIP_TOO_LARGE")
    except OSError:
        return ZipPayload(None, None, "SOURCE_NOT_FOUND")
    try:
        with path.open("rb") as handle:
            return _read_stream(handle, bounds)
    except OSError:
        return ZipPayload(None, None, "SOURCE_NOT_FOUND")


def _read_stream(stream, bounds: ImportLimits) -> ZipPayload:
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError):
        return ZipPayload(None, None, "INVALID_ZIP")
    try:
        infos = archive.infolist()
        if len(infos) > bounds.max_entries:
            return ZipPayload(None, None, "ENTRY_LIMIT")
        seen: set[str] = set()
        total = 0
        candidates: list[zipfile.ZipInfo] = []
        for info in infos:
            try:
                normalized = _check_name(info.filename)
            except ZipSecurityError as exc:
                return ZipPayload(None, None, exc.code)
            if normalized in seen:
                return ZipPayload(None, None, "DUPLICATE_ENTRY")
            seen.add(normalized)
            if _is_symlink(info):
                return ZipPayload(None, None, "SYMLINK_REJECTED")
            if _is_encrypted(info):
                return ZipPayload(None, None, "ENCRYPTED_ZIP")
            if info.is_dir():
                continue
            total += info.file_size
            if total > bounds.max_uncompressed_bytes:
                return ZipPayload(None, None, "UNCOMPRESSED_LIMIT")
            if info.file_size >= 1024:
                if info.compress_size <= 0:
                    return ZipPayload(None, None, "COMPRESSION_RATIO")
                if info.file_size / info.compress_size > bounds.max_compression_ratio:
                    return ZipPayload(None, None, "COMPRESSION_RATIO")
            if normalized.rsplit("/", 1)[-1] == _CONVERSATIONS:
                candidates.append(info)
        if not candidates:
            return ZipPayload(None, None, "MISSING_CONVERSATIONS")
        if len(candidates) > 1:
            return ZipPayload(None, None, "DUPLICATE_CONVERSATIONS")
        chosen = candidates[0]
        if chosen.file_size > bounds.max_json_bytes:
            return ZipPayload(None, None, "JSON_TOO_LARGE")
        try:
            with archive.open(chosen, "r") as handle:
                data = handle.read(bounds.max_json_bytes + 1)
        except RuntimeError:
            return ZipPayload(None, None, "ENCRYPTED_ZIP")
        except (zipfile.BadZipFile, OSError, ValueError):
            return ZipPayload(None, None, "INVALID_ZIP")
        if len(data) > bounds.max_json_bytes:
            return ZipPayload(None, None, "JSON_TOO_LARGE")
        return ZipPayload(data, chosen.filename, None)
    finally:
        archive.close()
