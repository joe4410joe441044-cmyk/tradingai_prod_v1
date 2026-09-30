"""OS advisory cross-process ownership lock for the future Supervisor
manual-trigger route (Work I③, Phase 3D-2B).

This module implements **only** the host-scoped, crash-safe advisory ownership
lock and a thin fencing/verification coordinator over the Phase 3D-2A
idempotency authority.  It does not add an API route, does not import or invoke
the manual monitoring runner, does not execute monitoring, does not emit
operator alerts, does not schedule background work and does not connect
Production.

Safety properties:

- importing the module performs no I/O;
- constructing the ownership object performs no I/O and requires an explicit
  caller-injected lock path (there is no automatically active Production
  default path);
- the lock file is opened only by an explicit :meth:`MonitoringTriggerOwnership.acquire`
  call, using an ``O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW`` open with a restrictive
  ``0o600`` mode;
- acquisition is non-blocking exclusive (``flock(LOCK_EX|LOCK_NB)``) and never
  silently downgrades to an in-process lock;
- the descriptor is retained for the whole ownership period and released in a
  ``finally``/context-manager path; the lock file is never unlinked;
- PID alone never proves ownership: ownership is the kernel advisory lock, and
  the stored metadata is diagnostic only;
- a lock holder whose idempotency generation/owner is stale is rejected and the
  lock is released without mutating the idempotency record.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat as stat_module
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import Field, field_validator

from .monitoring_models import Contract, Count, Token, aware

try:  # pragma: no cover - platform dependent
    import fcntl as _fcntl
except Exception:  # noqa: BLE001 - absent on non-POSIX platforms
    _fcntl = None

# Advisory locking is only attempted when the platform provides it.  Tests patch
# this flag to exercise the fail-closed UNSUPPORTED path.
FCNTL_AVAILABLE = _fcntl is not None and hasattr(_fcntl, "flock")

OWNERSHIP_SCHEMA_VERSION = "supervisor-trigger-ownership-v1"
OWNER_METADATA_AUTHORITY = "ADVISORY_LOCK_NOT_PID"

# Explicit path authority: there is no Production default lock path and the path
# must be injected by trusted server-side code.
EXPLICIT_LOCK_PATH_REQUIRED = True
PRODUCTION_DEFAULT_LOCK_PATH = None

OS_ADVISORY_LOCK_IMPLEMENTED = "YES"
GENERATION_FENCING_INTEGRATED = "YES"
STALE_OWNER_REJECTED = "YES"
RUNNER_CONNECTED = "NO"

DEFAULT_MAX_METADATA_BYTES = 2048
DEFAULT_MAX_READ_BYTES = 8192

MAX_REQUEST_ID_LENGTH = 128
MAX_RUN_ID_LENGTH = 128
MAX_OPERATION_LENGTH = 64
MAX_OWNER_ID_LENGTH = 128

_LOOPBACK = getattr(errno, "EWOULDBLOCK", errno.EAGAIN)
_BUSY_ERRNOS = frozenset({errno.EAGAIN, _LOOPBACK, errno.EACCES})

_ACCESS_ERRNOS = frozenset({errno.EACCES, errno.EPERM})
_MISSING_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SECRET_MARKERS = ("API_KEY", "APIKEY", "PASSWORD", "PRIVATE_KEY", "SECRET", "BEARER", "TOKEN")

OwnershipState = Literal[
    "NOT_CONFIGURED",
    "ACQUIRED",
    "BUSY",
    "FENCED",
    "UNSUPPORTED",
    "INVALID_PATH",
    "PERMISSION_DENIED",
    "UNSAFE_FILE",
    "ERROR",
]
FencingState = Literal[
    "VERIFIED",
    "STALE_GENERATION",
    "WRONG_OWNER",
    "RECORD_NOT_FOUND",
    "AUTHORITY_UNAVAILABLE",
    "NOT_ACQUIRED",
]
ProcessStartState = Literal["AVAILABLE", "UNAVAILABLE"]
MetadataAuthority = Literal["DIAGNOSTIC_ONLY"]
IdempotencyAuthority = Literal["SQLITE_IDEMPOTENCY_GENERATION"]


class OwnershipInputError(ValueError):
    """Bounded, presentation-safe input rejection."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class OwnershipLimits:
    max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES

    def __post_init__(self) -> None:
        if not 1 <= self.max_metadata_bytes <= 64 * 1024:
            raise ValueError("max_metadata_bytes out of range")
        if not 1 <= self.max_read_bytes <= 1024 * 1024:
            raise ValueError("max_read_bytes out of range")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check_token(value: Any, name: str, max_length: int) -> str:
    if not isinstance(value, str) or isinstance(value, bool):
        raise OwnershipInputError("INPUT_INVALID")
    if not 1 <= len(value) <= max_length:
        raise OwnershipInputError("INPUT_INVALID")
    if not _TOKEN_RE.match(value):
        raise OwnershipInputError("INPUT_INVALID")
    upper = value.upper()
    if any(marker in upper for marker in _SECRET_MARKERS):
        raise OwnershipInputError("INPUT_INVALID")
    if value.startswith(("sk-", "eyJ")):
        raise OwnershipInputError("INPUT_INVALID")
    return value


def _check_generation(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise OwnershipInputError("INPUT_INVALID")
    if value > 10**12:
        raise OwnershipInputError("INPUT_INVALID")
    return value


def default_instance_id() -> str:
    """Privacy-safe, bounded instance reference derived from the host name."""

    try:
        node = os.uname().nodename
    except Exception:  # noqa: BLE001 - platform dependent
        node = ""
    if not node:
        return "IUNKNOWN"
    return "I" + hashlib.sha256(node.encode("utf-8")).hexdigest()[:24]


def default_process_start_identity(pid: int) -> str | None:
    """Best-effort process-start identity source (Linux ``/proc`` only).

    Returns the raw field-22 start time, hashed by the caller.  Unsupported or
    unreadable platforms return ``None``; this is never an error and never
    proves ownership.
    """

    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            data = handle.read(4096)
    except OSError:
        return None
    try:
        text = data.decode("latin-1")
    except Exception:  # noqa: BLE001
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 2:].split()
    if len(fields) < 20:
        return None
    return fields[19]


def _derive_process_start(
    pid: int, provider: Callable[[int], str | None] | None
) -> tuple[str | None, ProcessStartState]:
    source = provider if provider is not None else default_process_start_identity
    try:
        raw = source(pid)
    except Exception:  # noqa: BLE001 - failure never proves ownership
        return None, "UNAVAILABLE"
    if not isinstance(raw, str) or not 0 < len(raw) <= 256:
        return None, "UNAVAILABLE"
    if any(ord(character) < 32 for character in raw):
        return None, "UNAVAILABLE"
    digest = hashlib.sha256(f"{pid}|{raw}".encode("utf-8")).hexdigest()[:24]
    return "PS" + digest, "AVAILABLE"


class OwnerMetadata(Contract):
    """Bounded, sanitized, diagnostic owner envelope.  Never a lock authority."""

    schema_version: Token = OWNERSHIP_SCHEMA_VERSION
    authority: Literal["ADVISORY_LOCK_NOT_PID"] = OWNER_METADATA_AUTHORITY
    instance_id: Token
    process_id: Count
    process_start_identity: Token | None = None
    process_start_state: ProcessStartState = "UNAVAILABLE"
    acquired_at: datetime
    request_id: Token
    run_id: Token | None = None
    operation: Token
    generation: Count
    owner_ref: Token | None = None

    _aware = field_validator("acquired_at")(aware)


class OwnershipResult(Contract):
    """Bounded acquisition/fencing result.  No filesystem path is exposed."""

    state: OwnershipState
    reason_code: Token
    acquired: bool = False
    configured: bool = False
    lock_path_configured: bool = False
    explicit_path_required: bool = EXPLICIT_LOCK_PATH_REQUIRED
    production_default_path: None = None
    unsupported_platform: bool = False
    generation: Count | None = None
    owner_metadata: OwnerMetadata | None = None
    fencing_state: FencingState | None = None
    expected_generation: Count | None = None
    observed_generation: Count | None = None


class OwnershipStatus(Contract):
    """In-memory ownership status.  No I/O, no path exposure."""

    configured: bool
    active: bool
    descriptor_open: bool
    state: OwnershipState
    generation: Count | None = None
    owner_metadata: OwnerMetadata | None = None
    explicit_path_required: bool = EXPLICIT_LOCK_PATH_REQUIRED
    production_default_path: None = None
    authority: Literal["OS_ADVISORY_FLOCK"] = "OS_ADVISORY_FLOCK"


class OwnerMetadataView(Contract):
    """Diagnostic read of persisted metadata.  Never proves active ownership."""

    present: bool
    metadata: OwnerMetadata | None = None
    authority: MetadataAuthority = "DIAGNOSTIC_ONLY"
    active_owner: bool = False


class FencingResult(Contract):
    """Generation/owner verification against the SQLite idempotency authority."""

    state: FencingState
    reason_code: Token
    expected_generation: Count | None = None
    observed_generation: Count | None = None
    owner_matches: bool | None = None
    authority: IdempotencyAuthority = "SQLITE_IDEMPOTENCY_GENERATION"


class OwnershipLease:
    """A held (or rejected) ownership acquisition.

    When ``acquired`` is true the OS lock is held until :meth:`release` (or the
    enclosing context manager) runs.  Rejections carry a bounded result only.
    """

    __slots__ = ("_owner", "result")

    def __init__(self, owner: "MonitoringTriggerOwnership", result: OwnershipResult) -> None:
        self._owner = owner
        self.result = result

    @property
    def state(self) -> str:
        return self.result.state

    @property
    def acquired(self) -> bool:
        return bool(self.result.acquired) and self._owner.active

    @property
    def generation(self) -> int | None:
        return self.result.generation

    @property
    def owner_metadata(self) -> OwnerMetadata | None:
        return self.result.owner_metadata

    @property
    def fencing_state(self) -> str | None:
        return self.result.fencing_state

    def release(self) -> None:
        self._owner.release()

    def __enter__(self) -> "OwnershipLease":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        self.release()
        return False

    def __bool__(self) -> bool:
        return self.acquired

    def __repr__(self) -> str:  # pragma: no cover - never contains a path
        return (
            f"OwnershipLease(state={self.result.state!r}, "
            f"acquired={self.result.acquired!r})"
        )


def _pwrite_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.pwrite(fd, data[offset:], offset)
        if written <= 0:
            raise OSError("short write")
        offset += written


def _read_all(fd: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining > 0:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class MonitoringTriggerOwnership:
    """Explicit, injected-path OS advisory ownership lock.

    The constructor is side-effect free.  Only :meth:`acquire` opens the lock
    file; :meth:`release` is idempotent and never unlinks the file.
    """

    def __init__(
        self,
        path: str | os.PathLike | None,
        *,
        create_parent: bool = False,
        limits: OwnershipLimits | None = None,
        clock: Callable[[], datetime] | None = None,
        instance_id: str | None = None,
        process_start_provider: Callable[[int], str | None] | None = None,
    ) -> None:
        if path is None or isinstance(path, bool):
            raise TypeError("an explicit lock path is required")
        candidate = Path(path)
        if str(candidate).strip() in ("", "."):
            raise TypeError("an explicit lock path is required")
        if not candidate.is_absolute():
            raise ValueError("the lock path must be absolute")
        self.path = candidate
        self.create_parent = bool(create_parent)
        self.limits = limits or OwnershipLimits()
        self._clock = clock if clock is not None else _utcnow
        self._instance_id = (
            _check_token(instance_id, "instance_id", 64) if instance_id is not None else None
        )
        if process_start_provider is not None and not callable(process_start_provider):
            raise TypeError("process_start_provider must be callable")
        self._process_start_provider = process_start_provider

        self._fd: int | None = None
        self._active = False
        self._state: OwnershipState = "NOT_CONFIGURED"
        self._generation: int | None = None
        self._metadata: OwnerMetadata | None = None

    # -- introspection -------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active and self._fd is not None

    @property
    def owner_metadata(self) -> OwnerMetadata | None:
        """Metadata for the current (or most recent) ownership.  Diagnostic only."""

        return self._metadata

    def current_status(self) -> OwnershipStatus:
        return OwnershipStatus(
            configured=True,
            active=self.active,
            descriptor_open=self._fd is not None,
            state="ACQUIRED" if self.active else self._state,
            generation=self._generation,
            owner_metadata=self._metadata,
        )

    def read_owner_metadata(self) -> OwnerMetadataView:
        """Read persisted diagnostic metadata.  Never proves ownership."""

        fd: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags)
        except OSError:
            return OwnerMetadataView(present=False)
        try:
            info = os.fstat(fd)
            if not stat_module.S_ISREG(info.st_mode):
                return OwnerMetadataView(present=False)
            raw = _read_all(fd, self.limits.max_read_bytes)
        except OSError:
            return OwnerMetadataView(present=False)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        if not raw:
            return OwnerMetadataView(present=False)
        try:
            payload = json.loads(raw.decode("utf-8"))
            metadata = OwnerMetadata.model_validate(payload)
        except Exception:  # noqa: BLE001 - unreadable metadata is bounded
            return OwnerMetadataView(present=False)
        return OwnerMetadataView(present=True, metadata=metadata)

    # -- results -------------------------------------------------------------

    def _result(self, state: OwnershipState, reason: str, **fields: Any) -> OwnershipResult:
        return OwnershipResult(
            state=state, reason_code=reason,
            configured=True, lock_path_configured=True, **fields,
        )

    def _rejected(self, state: OwnershipState, reason: str, **fields: Any) -> OwnershipLease:
        self._state = state
        return OwnershipLease(self, self._result(state, reason, **fields))

    # -- acquisition ---------------------------------------------------------

    def acquire(
        self,
        request_id: str,
        run_id: str | None,
        operation: str,
        generation: int,
        *,
        owner_id: str | None = None,
    ) -> OwnershipLease:
        """Non-blocking exclusive acquisition of the explicit lock path."""

        if self.active:
            return self._rejected("BUSY", "ALREADY_HELD")

        try:
            clean_request = _check_token(request_id, "request_id", MAX_REQUEST_ID_LENGTH)
            clean_operation = _check_token(operation, "operation", MAX_OPERATION_LENGTH)
            clean_run = (
                None if run_id is None
                else _check_token(run_id, "run_id", MAX_RUN_ID_LENGTH)
            )
            clean_owner = (
                None if owner_id is None
                else _check_token(owner_id, "owner_id", MAX_OWNER_ID_LENGTH)
            )
            clean_generation = _check_generation(generation)
        except OwnershipInputError:
            return self._rejected("ERROR", "INPUT_INVALID")

        if not FCNTL_AVAILABLE:
            return self._rejected("UNSUPPORTED", "ADVISORY_LOCK_UNSUPPORTED",
                                  unsupported_platform=True)

        path = self.path
        parent = path.parent

        try:
            parent_is_symlink = parent.is_symlink()
        except OSError:
            return self._rejected("INVALID_PATH", "PATH_STAT_FAILED")
        if parent_is_symlink:
            return self._rejected("INVALID_PATH", "PARENT_SYMLINK")
        if not parent.exists():
            if not self.create_parent:
                return self._rejected("NOT_CONFIGURED", "PARENT_MISSING")
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                return self._rejected("INVALID_PATH", "PARENT_CREATE_FAILED")
        elif not parent.is_dir():
            return self._rejected("INVALID_PATH", "PARENT_NOT_DIRECTORY")

        pre_stat: os.stat_result | None = None
        try:
            path_lstat = path.lstat()
        except FileNotFoundError:
            path_lstat = None
        except OSError:
            return self._rejected("INVALID_PATH", "PATH_STAT_FAILED")
        if path_lstat is not None:
            if stat_module.S_ISLNK(path_lstat.st_mode):
                return self._rejected("UNSAFE_FILE", "SYMLINK_REJECTED")
            if not stat_module.S_ISREG(path_lstat.st_mode):
                return self._rejected("UNSAFE_FILE", "NOT_REGULAR")
            pre_stat = path_lstat

        flags = (
            os.O_RDWR | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            fd = os.open(path, flags, 0o600)
        except FileNotFoundError:
            return self._rejected("INVALID_PATH", "PATH_MISSING")
        except IsADirectoryError:
            return self._rejected("UNSAFE_FILE", "NOT_REGULAR")
        except PermissionError:
            return self._rejected("PERMISSION_DENIED", "OPEN_DENIED")
        except OSError as exc:
            number = exc.errno
            if number == errno.ELOOP:
                return self._rejected("UNSAFE_FILE", "SYMLINK_REJECTED")
            if number in (errno.EISDIR, errno.ENOTDIR):
                return self._rejected("UNSAFE_FILE", "NOT_REGULAR")
            if number in _ACCESS_ERRNOS:
                return self._rejected("PERMISSION_DENIED", "OPEN_DENIED")
            if number in _MISSING_ERRNOS:
                return self._rejected("INVALID_PATH", "PATH_MISSING")
            return self._rejected("ERROR", "OPEN_FAILED")
        except Exception:  # noqa: BLE001 - never surface raw exception text
            return self._rejected("ERROR", "OPEN_FAILED")

        try:
            info = os.fstat(fd)
        except OSError:
            _close_quietly(fd)
            return self._rejected("ERROR", "FSTAT_FAILED")
        if not stat_module.S_ISREG(info.st_mode):
            _close_quietly(fd)
            return self._rejected("UNSAFE_FILE", "NOT_REGULAR")
        if pre_stat is not None and (
            info.st_ino != pre_stat.st_ino or info.st_dev != pre_stat.st_dev
        ):
            _close_quietly(fd)
            return self._rejected("UNSAFE_FILE", "TYPE_CHANGED")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            _close_quietly(fd)
            return self._rejected("PERMISSION_DENIED", "OWNER_MISMATCH")
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            _close_quietly(fd)
            return self._rejected("PERMISSION_DENIED", "MODE_ENFORCE_FAILED")
        try:
            info = os.fstat(fd)
        except OSError:
            _close_quietly(fd)
            return self._rejected("ERROR", "FSTAT_FAILED")
        if info.st_mode & 0o077:
            _close_quietly(fd)
            return self._rejected("UNSAFE_FILE", "UNSAFE_PERMISSIONS")

        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError as exc:
            _close_quietly(fd)
            if exc.errno in _BUSY_ERRNOS:
                return self._rejected("BUSY", "LOCK_BUSY")
            return self._rejected("ERROR", "LOCK_FAILED")

        metadata, metadata_state = self._build_metadata(
            request_id=clean_request, run_id=clean_run, operation=clean_operation,
            generation=clean_generation, owner_id=clean_owner,
        )
        if metadata_state != "OK":
            _unlock_and_close(fd)
            return self._rejected("ERROR", metadata_state)

        try:
            raw = metadata.stable_json().encode("utf-8")
        except Exception:  # noqa: BLE001 - serialization must fail closed
            _unlock_and_close(fd)
            return self._rejected("ERROR", "METADATA_SERIALIZATION_FAILED")
        if len(raw) > self.limits.max_metadata_bytes:
            _unlock_and_close(fd)
            return self._rejected("ERROR", "METADATA_TOO_LARGE")
        try:
            os.ftruncate(fd, 0)
            _pwrite_all(fd, raw)
            os.fsync(fd)
        except OSError:
            _unlock_and_close(fd)
            return self._rejected("ERROR", "METADATA_WRITE_FAILED")

        self._fd = fd
        self._active = True
        self._state = "ACQUIRED"
        self._generation = clean_generation
        self._metadata = metadata
        return OwnershipLease(
            self,
            self._result(
                "ACQUIRED", "ACQUIRED",
                acquired=True,
                generation=clean_generation,
                owner_metadata=metadata,
            ),
        )

    def _build_metadata(
        self, *, request_id: str, run_id: str | None, operation: str,
        generation: int, owner_id: str | None,
    ) -> tuple[OwnerMetadata, str]:
        try:
            instance_id = self._instance_id or default_instance_id()
        except Exception:  # noqa: BLE001
            instance_id = "IUNKNOWN"
        pid = os.getpid()
        start_identity, start_state = _derive_process_start(
            pid, self._process_start_provider
        )
        try:
            metadata = OwnerMetadata(
                instance_id=instance_id,
                process_id=pid,
                process_start_identity=start_identity,
                process_start_state=start_state,
                acquired_at=aware(self._clock()),
                request_id=request_id,
                run_id=run_id,
                operation=operation,
                generation=generation,
                owner_ref=owner_id,
            )
        except Exception:  # noqa: BLE001 - metadata must never leak or crash
            return None, "METADATA_INVALID"  # type: ignore[return-value]
        return metadata, "OK"

    # -- release -------------------------------------------------------------

    def release(self) -> None:
        """Idempotent release: unlock, then close.  Never unlinks the file."""

        fd = self._fd
        self._fd = None
        self._active = False
        self._state = "NOT_CONFIGURED"
        if fd is None:
            return
        _unlock_and_close(fd)

    def __enter__(self) -> "MonitoringTriggerOwnership":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        self.release()
        return False


def _unlock_and_close(fd: int) -> None:
    if _fcntl is not None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001 - release must never raise
            pass
    _close_quietly(fd)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except Exception:  # noqa: BLE001 - close must never raise
        pass


class MonitoringTriggerOwnershipCoordinator:
    """Thin ownership + fencing boundary.

    It accepts an already-created idempotency claim, acquires the OS lock,
    verifies the claim generation/owner against the durable SQLite authority and
    returns an ownership lease.  It never calls the manual runner, never
    executes monitoring, never handles HTTP, never evaluates authentication/CSRF,
    never schedules work and never completes a monitoring result.
    """

    def __init__(
        self,
        *,
        ownership: MonitoringTriggerOwnership,
        store: Any,
    ) -> None:
        if not isinstance(ownership, MonitoringTriggerOwnership):
            raise TypeError("ownership must be a MonitoringTriggerOwnership")
        if not callable(getattr(store, "get_record", None)):
            raise TypeError("store must expose an explicit get_record method")
        self._ownership = ownership
        self._store = store

    @property
    def ownership(self) -> MonitoringTriggerOwnership:
        return self._ownership

    def _read_record(self, request_id: str, operation: str, principal_scope: str):
        return self._store.get_record(
            key=request_id, operation=operation, principal_scope=principal_scope
        )

    def acquire_for_claim(
        self,
        *,
        request_id: str,
        run_id: str | None,
        operation: str,
        principal_scope: str,
        request_fingerprint: str,
        expected_generation: int,
        expected_owner_id: str | None = None,
        now: datetime | None = None,
    ) -> OwnershipLease:
        """Acquire the OS lock, then verify the claim generation/owner."""

        del request_fingerprint, now  # validated request identity already exists
        lease = self._ownership.acquire(
            request_id=request_id, run_id=run_id, operation=operation,
            generation=expected_generation, owner_id=expected_owner_id,
        )
        if not lease.acquired:
            return lease

        try:
            record = self._read_record(request_id, operation, principal_scope)
        except Exception:  # noqa: BLE001 - authority failure fails closed
            return self._fence(
                lease, "AUTHORITY_UNAVAILABLE", "IDEMPOTENCY_AUTHORITY_UNAVAILABLE",
                expected_generation=expected_generation,
            )
        if record is None:
            return self._fence(
                lease, "RECORD_NOT_FOUND", "RECORD_NOT_FOUND",
                expected_generation=expected_generation,
            )
        observed = getattr(record, "generation", None)
        if observed != expected_generation:
            return self._fence(
                lease, "STALE_GENERATION", "STALE_GENERATION",
                expected_generation=expected_generation, observed_generation=observed,
            )
        if expected_owner_id is not None and getattr(record, "owner_id", None) != expected_owner_id:
            return self._fence(
                lease, "WRONG_OWNER", "WRONG_OWNER",
                expected_generation=expected_generation, observed_generation=observed,
            )
        fenced = lease.result.model_copy(
            update={
                "fencing_state": "VERIFIED",
                "expected_generation": expected_generation,
                "observed_generation": observed,
            }
        )
        return OwnershipLease(self._ownership, fenced)

    def verify_owner(
        self,
        *,
        request_id: str,
        operation: str,
        principal_scope: str,
        expected_generation: int,
        expected_owner_id: str | None = None,
    ) -> FencingResult:
        """Read-only generation/owner verification.  Never mutates the record."""

        try:
            clean_generation = _check_generation(expected_generation)
        except OwnershipInputError:
            return FencingResult(state="NOT_ACQUIRED", reason_code="INPUT_INVALID")
        try:
            record = self._read_record(request_id, operation, principal_scope)
        except Exception:  # noqa: BLE001
            return FencingResult(
                state="AUTHORITY_UNAVAILABLE", reason_code="IDEMPOTENCY_AUTHORITY_UNAVAILABLE",
                expected_generation=clean_generation,
            )
        if record is None:
            return FencingResult(
                state="RECORD_NOT_FOUND", reason_code="RECORD_NOT_FOUND",
                expected_generation=clean_generation,
            )
        observed = getattr(record, "generation", None)
        if observed != clean_generation:
            return FencingResult(
                state="STALE_GENERATION", reason_code="STALE_GENERATION",
                expected_generation=clean_generation, observed_generation=observed,
            )
        owner_matches = (
            None if expected_owner_id is None
            else getattr(record, "owner_id", None) == expected_owner_id
        )
        if owner_matches is False:
            return FencingResult(
                state="WRONG_OWNER", reason_code="WRONG_OWNER",
                expected_generation=clean_generation, observed_generation=observed,
                owner_matches=False,
            )
        return FencingResult(
            state="VERIFIED", reason_code="VERIFIED",
            expected_generation=clean_generation, observed_generation=observed,
            owner_matches=owner_matches,
        )

    def _fence(
        self, lease: OwnershipLease, state: FencingState, reason: str,
        *, expected_generation: int, observed_generation: int | None = None,
    ) -> OwnershipLease:
        self._ownership.release()
        fenced = OwnershipResult(
            state="FENCED",
            reason_code=reason,
            acquired=False,
            configured=True,
            lock_path_configured=True,
            generation=None,
            owner_metadata=lease.result.owner_metadata,
            fencing_state=state,
            expected_generation=expected_generation,
            observed_generation=observed_generation,
        )
        return OwnershipLease(self._ownership, fenced)


__all__ = [
    "DEFAULT_MAX_METADATA_BYTES",
    "DEFAULT_MAX_READ_BYTES",
    "EXPLICIT_LOCK_PATH_REQUIRED",
    "FCNTL_AVAILABLE",
    "FencingResult",
    "GENERATION_FENCING_INTEGRATED",
    "MonitoringTriggerOwnership",
    "MonitoringTriggerOwnershipCoordinator",
    "OS_ADVISORY_LOCK_IMPLEMENTED",
    "OwnerMetadata",
    "OwnerMetadataView",
    "OwnershipInputError",
    "OwnershipLease",
    "OwnershipLimits",
    "OwnershipResult",
    "OwnershipState",
    "OwnershipStatus",
    "OWNERSHIP_SCHEMA_VERSION",
    "PRODUCTION_DEFAULT_LOCK_PATH",
    "RUNNER_CONNECTED",
    "STALE_OWNER_REJECTED",
    "default_instance_id",
    "default_process_start_identity",
]
