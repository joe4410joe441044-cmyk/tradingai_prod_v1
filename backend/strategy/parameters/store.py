"""Hardened atomic-file persistence for canonical strategy parameters (E-PARAM-1).

The store is deliberately narrow: it persists and loads one canonical
:class:`StrategyParameterSet` per scope.  It never invents trading values.  A
missing or corrupt file is surfaced as an explicit typed result so the future
resolver/authority (E-PARAM-2 / E-PARAM-3) can decide whether to fall back to
a named migration baseline.

This module reuses the hardened atomic-file pattern from
``backend/money_management/loss_persistence_adapter.py``.  It does not use
ConfigStore, Redis or a database, and it stores no credentials or secrets.
"""

from __future__ import annotations

import hmac
import json
import os
import stat
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Optional, Union

from .model import ParameterScope, StrategyParameterSet

ENVELOPE_VERSION = "strategy-parameter-envelope/v1"
INTEGRITY_ALGORITHM = "SHA256"
MAX_FILE_SIZE = 256 * 1024
STORAGE_SUBDIRECTORY = "strategy_parameters"

_SUPPORTED_SCOPES = (ParameterScope.PAPER, ParameterScope.LIVE)


class StoreLoadStatus(str, Enum):
    VALID = "VALID"
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"
    INVALID = "INVALID"


class StoreSaveStatus(str, Enum):
    SAVED = "SAVED"
    FAILED = "FAILED"


class StoreFailureCode(str, Enum):
    INVALID_SET = "INVALID_SET"
    UNSUPPORTED_SCOPE = "UNSUPPORTED_SCOPE"
    UNSAFE_PATH = "UNSAFE_PATH"
    UNSAFE_FILE = "UNSAFE_FILE"
    TEMPORARY_FILE_EXISTS = "TEMPORARY_FILE_EXISTS"
    TOO_LARGE = "TOO_LARGE"
    SERIALIZATION_FAILED = "SERIALIZATION_FAILED"
    WRITE_FAILED = "WRITE_FAILED"
    FSYNC_FAILED = "FSYNC_FAILED"
    REPLACE_FAILED = "REPLACE_FAILED"
    DIRECTORY_FSYNC_FAILED = "DIRECTORY_FSYNC_FAILED"


@dataclass(frozen=True)
class StoreLoadResult:
    status: StoreLoadStatus
    parameter_set: Optional[StrategyParameterSet] = None
    failure_code: Optional[str] = None
    safe_message: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", StoreLoadStatus(self.status))
        if self.status is StoreLoadStatus.VALID:
            if self.parameter_set is None or self.failure_code is not None:
                raise ValueError("valid load result requires a parameter set")
        elif self.parameter_set is not None or not self.failure_code:
            raise ValueError("failure load result requires a failure code")

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "parameter_set": (
                self.parameter_set.to_dict() if self.parameter_set else None
            ),
            "failure_code": self.failure_code,
            "safe_message": self.safe_message,
        }


@dataclass(frozen=True)
class StoreSaveResult:
    status: StoreSaveStatus
    failure_code: Optional[StoreFailureCode] = None
    safe_message: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", StoreSaveStatus(self.status))
        if self.status is StoreSaveStatus.SAVED and self.failure_code is not None:
            raise ValueError("saved result cannot carry a failure code")
        if self.status is StoreSaveStatus.FAILED and self.failure_code is None:
            raise ValueError("failed result requires a failure code")

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "failure_code": (
                self.failure_code.value if self.failure_code else None
            ),
            "safe_message": self.safe_message,
        }


def _reject_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def _strict_json(raw: bytes):
    def hook(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate JSON key")
        return dict(pairs)

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=hook,
        parse_constant=_reject_constant,
    )


def _canonical_payload_bytes(parameter_set: StrategyParameterSet) -> bytes:
    return json.dumps(
        parameter_set.to_dict(),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _build_digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def serialize_parameter_envelope(parameter_set: StrategyParameterSet) -> bytes:
    """Deterministic integrity envelope for a canonical parameter set."""

    if not isinstance(parameter_set, StrategyParameterSet):
        raise TypeError("StrategyParameterSet required")
    payload = _canonical_payload_bytes(parameter_set)
    envelope = {
        "envelopeVersion": ENVELOPE_VERSION,
        "integrityAlgorithm": INTEGRITY_ALGORITHM,
        "integrityDigest": _build_digest(payload),
        "payload": json.loads(payload.decode("utf-8")),
    }
    return json.dumps(
        envelope,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _coerce_scope(scope: Union[ParameterScope, str]) -> ParameterScope:
    if isinstance(scope, ParameterScope):
        return scope
    return ParameterScope(scope)


def _safe_base(base_directory: Path) -> Path:
    if not isinstance(base_directory, Path) or not base_directory.is_absolute():
        raise ValueError("base directory must be an absolute path")
    if not base_directory.exists() or not base_directory.is_dir():
        raise OSError("unsafe base directory")
    if base_directory.is_symlink():
        raise OSError("unsafe base directory")
    current = Path(base_directory.anchor)
    for part in base_directory.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise OSError("unsafe parent directory")
    return base_directory


def _ensure_scope_directory(base_directory: Path) -> Path:
    directory = base_directory / STORAGE_SUBDIRECTORY
    if directory.is_symlink():
        raise OSError("unsafe scope directory")
    if not directory.exists():
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
    if directory.is_symlink() or not directory.is_dir():
        raise OSError("unsafe scope directory")
    return directory


def _filename(scope: ParameterScope) -> str:
    return f"strategy-params__{scope.value}.json"


def _temp_filename(scope: ParameterScope) -> str:
    return f".strategy-params__{scope.value}.json.tmp"


class StrategyParameterStore:
    """Atomic, integrity-checked, scope-isolated parameter set store."""

    def __init__(self, base_directory: Path):
        self._base_directory = base_directory

    @property
    def base_directory(self) -> Path:
        return self._base_directory

    def path_for(self, scope: Union[ParameterScope, str]) -> Path:
        resolved = _coerce_scope(scope)
        if resolved not in _SUPPORTED_SCOPES:
            raise ValueError(f"unsupported scope: {resolved.value}")
        return (
            self._base_directory
            / STORAGE_SUBDIRECTORY
            / _filename(resolved)
        )

    def save(self, parameter_set: StrategyParameterSet) -> StoreSaveResult:
        temp = None
        phase = "write"
        if not isinstance(parameter_set, StrategyParameterSet):
            return StoreSaveResult(
                StoreSaveStatus.FAILED,
                StoreFailureCode.INVALID_SET,
                "invalid parameter set",
            )
        scope = parameter_set.scope
        if scope not in _SUPPORTED_SCOPES:
            return StoreSaveResult(
                StoreSaveStatus.FAILED,
                StoreFailureCode.UNSUPPORTED_SCOPE,
                "unsupported scope",
            )
        try:
            try:
                base = _safe_base(self._base_directory)
            except (ValueError, OSError):
                return StoreSaveResult(
                    StoreSaveStatus.FAILED,
                    StoreFailureCode.UNSAFE_PATH,
                    "unsafe path",
                )
            directory = _ensure_scope_directory(base)
            target = directory / _filename(scope)
            temp = directory / _temp_filename(scope)
            if target.exists() and (
                target.is_symlink()
                or not stat.S_ISREG(target.stat().st_mode)
                or target.stat().st_mode & 0o077
            ):
                return StoreSaveResult(
                    StoreSaveStatus.FAILED,
                    StoreFailureCode.UNSAFE_FILE,
                    "unsafe target",
                )
            if temp.exists():
                return StoreSaveResult(
                    StoreSaveStatus.FAILED,
                    StoreFailureCode.TEMPORARY_FILE_EXISTS,
                    "temporary file exists",
                )
            raw = serialize_parameter_envelope(parameter_set)
            if len(raw) > MAX_FILE_SIZE:
                return StoreSaveResult(
                    StoreSaveStatus.FAILED,
                    StoreFailureCode.TOO_LARGE,
                    "parameter set too large",
                )
            fd = os.open(
                temp,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                offset = 0
                while offset < len(raw):
                    written = os.write(fd, raw[offset:])
                    if written <= 0:
                        raise OSError("short write")
                    offset += written
                phase = "file_fsync"
                os.fsync(fd)
            finally:
                os.close(fd)
            if temp.is_symlink() or not stat.S_ISREG(temp.stat().st_mode):
                raise OSError("unsafe temporary file")
            phase = "replace"
            os.replace(temp, target)
            fd = os.open(
                directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                phase = "directory_fsync"
                os.fsync(fd)
            finally:
                os.close(fd)
            return StoreSaveResult(StoreSaveStatus.SAVED)
        except ValueError:
            return StoreSaveResult(
                StoreSaveStatus.FAILED,
                StoreFailureCode.SERIALIZATION_FAILED,
                "serialization failed",
            )
        except OSError:
            code = {
                "file_fsync": StoreFailureCode.FSYNC_FAILED,
                "directory_fsync": StoreFailureCode.DIRECTORY_FSYNC_FAILED,
                "replace": StoreFailureCode.REPLACE_FAILED,
            }.get(phase, StoreFailureCode.WRITE_FAILED)
            return StoreSaveResult(StoreSaveStatus.FAILED, code, "persistence failed")
        finally:
            if temp is not None and temp.exists() and not temp.is_symlink():
                try:
                    temp.unlink()
                except OSError:
                    pass

    def load(self, scope: Union[ParameterScope, str]) -> StoreLoadResult:
        try:
            resolved = _coerce_scope(scope)
        except ValueError:
            return StoreLoadResult(
                StoreLoadStatus.INVALID,
                None,
                "UNSUPPORTED_SCOPE",
                "unsupported scope",
            )
        if resolved not in _SUPPORTED_SCOPES:
            return StoreLoadResult(
                StoreLoadStatus.INVALID,
                None,
                "UNSUPPORTED_SCOPE",
                "unsupported scope",
            )
        try:
            base = _safe_base(self._base_directory)
        except (ValueError, OSError):
            return StoreLoadResult(
                StoreLoadStatus.INVALID,
                None,
                "UNSAFE_PATH",
                "unsafe path",
            )
        directory = base / STORAGE_SUBDIRECTORY
        if directory.is_symlink():
            return StoreLoadResult(
                StoreLoadStatus.INVALID,
                None,
                "UNSAFE_FILE",
                "unsafe directory",
            )
        target = directory / _filename(resolved)
        try:
            if not target.exists():
                return StoreLoadResult(
                    StoreLoadStatus.MISSING, None, "MISSING", "parameter set missing"
                )
            if target.is_symlink() or not stat.S_ISREG(target.stat().st_mode):
                return StoreLoadResult(
                    StoreLoadStatus.INVALID, None, "UNSAFE_FILE", "unsafe file"
                )
            info = target.stat()
            if info.st_size > MAX_FILE_SIZE:
                return StoreLoadResult(
                    StoreLoadStatus.INVALID, None, "TOO_LARGE", "file too large"
                )
            if info.st_mode & 0o077:
                return StoreLoadResult(
                    StoreLoadStatus.INVALID,
                    None,
                    "UNSAFE_FILE",
                    "unsafe permissions",
                )
            fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                raw = os.read(fd, MAX_FILE_SIZE + 1)
            finally:
                os.close(fd)
            if len(raw) > MAX_FILE_SIZE:
                return StoreLoadResult(
                    StoreLoadStatus.INVALID, None, "TOO_LARGE", "file too large"
                )
            envelope = _strict_json(raw)
            if not isinstance(envelope, dict):
                raise ValueError("envelope must be an object")
            if set(envelope) != {
                "envelopeVersion",
                "integrityAlgorithm",
                "integrityDigest",
                "payload",
            }:
                raise ValueError("invalid envelope shape")
            if (
                envelope["envelopeVersion"] != ENVELOPE_VERSION
                or envelope["integrityAlgorithm"] != INTEGRITY_ALGORITHM
            ):
                return StoreLoadResult(
                    StoreLoadStatus.INVALID,
                    None,
                    "INCOMPATIBLE_VERSION",
                    "incompatible envelope version",
                )
            payload = envelope["payload"]
            canonical = json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            digest = _build_digest(canonical)
            stored_digest = envelope["integrityDigest"]
            if (
                not isinstance(stored_digest, str)
                or len(stored_digest) != 64
                or not hmac.compare_digest(digest, stored_digest)
            ):
                raise ValueError("integrity mismatch")
        except UnicodeDecodeError:
            return StoreLoadResult(
                StoreLoadStatus.CORRUPT, None, "CORRUPT", "invalid encoding"
            )
        except (ValueError, TypeError, OverflowError):
            return StoreLoadResult(
                StoreLoadStatus.CORRUPT, None, "CORRUPT", "invalid envelope"
            )
        except OSError:
            return StoreLoadResult(
                StoreLoadStatus.INVALID, None, "IO_ERROR", "I/O failed"
            )
        try:
            parameter_set = StrategyParameterSet.from_dict(payload)
        except (ValueError, KeyError, TypeError, OverflowError):
            return StoreLoadResult(
                StoreLoadStatus.INVALID, None, "INVALID_SCHEMA", "invalid parameter set"
            )
        return StoreLoadResult(StoreLoadStatus.VALID, parameter_set)
