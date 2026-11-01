"""Explicit-path, atomic durable account registry.

This module never chooses a path, initializes storage, or reads credentials
implicitly. Mutations use a stable process lock and disk-backed CAS.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import errno
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import stat
import time
from threading import RLock
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

from .models import (
    ACCOUNT_IDENTITY_SCHEMA_VERSION,
    AccountId,
    AccountIdentity,
    AccountLifecycleState,
    ExecutionVenue,
)
from .registry_contract import (
    AccountLookupResult,
    AccountRegistrationDraft,
    AccountRegistrationResult,
    RegistryFailureCode,
    RegistryLookupStatus,
    RegistryOperationLookupStatus,
    RegistryOperationReceipt,
    RegistryRegistrationStatus,
    _SAFE_MESSAGES,
)
from .registry_models import (
    REGISTRY_ENVELOPE_SCHEMA_VERSION,
    REGISTRY_EVENT_SCHEMA_VERSION,
    REGISTRY_RECORD_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    AccountRegistryEvent,
    AccountRegistryRecord,
    AccountRegistrySnapshot,
    CredentialBundleReference,
    ExternalAccountBinding,
    RegistryEventType,
    _operation_id as _validate_operation_id,
)


MAX_REGISTRY_BYTES = 1024 * 1024


class RegistryLoadStatus(str, Enum):
    VALID = "VALID"
    MISSING = "MISSING"
    CORRUPT = "CORRUPT"
    INVALID = "INVALID"
    INCOMPATIBLE_VERSION = "INCOMPATIBLE_VERSION"
    UNSAFE_PATH = "UNSAFE_PATH"
    UNSAFE_FILE = "UNSAFE_FILE"
    TOO_LARGE = "TOO_LARGE"
    IO_ERROR = "IO_ERROR"


class RegistryMutationStatus(str, Enum):
    SAVED = "SAVED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    ALREADY_INITIALIZED = "ALREADY_INITIALIZED"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"
    FAILED = "FAILED"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"


@dataclass(frozen=True)
class RegistryLoadResult:
    status: RegistryLoadStatus
    snapshot: Optional[AccountRegistrySnapshot] = None

    def __post_init__(self) -> None:
        try:
            status = RegistryLoadStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry load status") from exc
        object.__setattr__(self, "status", status)
        if self.snapshot is not None and not isinstance(
            self.snapshot, AccountRegistrySnapshot
        ):
            raise TypeError("snapshot must be AccountRegistrySnapshot or None")
        if status is RegistryLoadStatus.VALID and self.snapshot is None:
            raise ValueError("VALID load result requires a snapshot")
        if status is not RegistryLoadStatus.VALID and self.snapshot is not None:
            raise ValueError("non-VALID load result must not contain a snapshot")

    @property
    def safe_message(self) -> str:
        return "" if self.status is RegistryLoadStatus.VALID else "Account registry is unavailable."


@dataclass(frozen=True)
class RegistryMutationResult:
    status: RegistryMutationStatus
    registry_revision: int
    record: Optional[AccountRegistryRecord] = None
    failure_code: RegistryFailureCode = RegistryFailureCode.NONE
    operation_id: Optional[str] = None
    request_fingerprint: Optional[str] = None
    original_registry_revision: Optional[int] = None

    def __post_init__(self) -> None:
        try:
            status = RegistryMutationStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry mutation status") from exc
        object.__setattr__(self, "status", status)
        try:
            failure_code = RegistryFailureCode(self.failure_code)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown registry failure code") from exc
        object.__setattr__(self, "failure_code", failure_code)
        if (
            isinstance(self.registry_revision, bool)
            or not isinstance(self.registry_revision, int)
            or self.registry_revision < 0
        ):
            raise ValueError("registry_revision must be a nonnegative integer")
        if self.original_registry_revision is not None and (
            isinstance(self.original_registry_revision, bool)
            or not isinstance(self.original_registry_revision, int)
            or self.original_registry_revision < 1
        ):
            raise ValueError("original_registry_revision must be a positive integer or None")
        if self.record is not None and not isinstance(self.record, AccountRegistryRecord):
            raise TypeError("record must be AccountRegistryRecord or None")

    @property
    def safe_message(self) -> str:
        return _SAFE_MESSAGES[self.failure_code]


def _reject_duplicate_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise _CorruptDocument("duplicate JSON key")
        result[key] = value
    return result


def _canonical_json(document: object) -> bytes:
    return json.dumps(
        document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class RegistryDocumentTooLarge(ValueError):
    pass


def _valid_expected_revision(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _normalize_label(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("display_label must be text")
    label = value.strip()
    if not label or len(label) > 100 or any(ord(character) < 32 for character in label):
        raise ValueError("display_label must contain 1 to 100 safe characters")
    return label


def _registration_payload(draft: AccountRegistrationDraft) -> dict[str, Any]:
    return {
        "registration_request_id": draft.registration_request_id,
        "account_type": draft.account_type.value,
        "execution_mode": draft.execution_mode.value,
        "execution_venue": draft.execution_venue.value,
        "prop_program": draft.prop_program.value if draft.prop_program else None,
        "prop_phase": draft.prop_phase.value if draft.prop_phase else None,
        "display_label": draft.display_label,
        "registration_source": draft.registration_source.value,
        "credential_reference": (
            draft.credential_reference.to_dict() if draft.credential_reference else None
        ),
        "external_binding": (
            draft.external_binding.to_dict() if draft.external_binding else None
        ),
        "predecessor_account_id": (
            draft.predecessor_account_id.value if draft.predecessor_account_id else None
        ),
    }


def _find_operation_event(
    snapshot: AccountRegistrySnapshot, operation_id: str
) -> Optional[AccountRegistryEvent]:
    return next(
        (event for event in snapshot.events if event.operation_id == operation_id), None
    )


def _registration_event(
    snapshot: AccountRegistrySnapshot, account_id: AccountId
) -> Optional[AccountRegistryEvent]:
    return next(
        (
            event
            for event in snapshot.events
            if event.event_type is RegistryEventType.REGISTERED
            and event.account_id == account_id
        ),
        None,
    )


def _operation_fingerprint(operation: str, account_id: Optional[AccountId], payload: Any) -> str:
    """Canonical, secret-free fingerprint of the meaningful request content.

    Expected CAS revisions and registry-owned timestamps are intentionally
    excluded so an operator can retry the same operation after recovering from
    an ambiguous commit using the current revisions.
    """

    document = {
        "operation": operation,
        "account_id": account_id.value if account_id is not None else None,
        "payload": payload,
    }
    return hashlib.sha256(_canonical_json(document)).hexdigest()


def serialize_snapshot(snapshot: AccountRegistrySnapshot) -> bytes:
    payload = snapshot.to_dict()
    payload_bytes = _canonical_json(payload)
    envelope = {
        "schema_version": REGISTRY_ENVELOPE_SCHEMA_VERSION,
        "digest_algorithm": "SHA256",
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload": payload,
    }
    encoded = _canonical_json(envelope)
    if len(encoded) > MAX_REGISTRY_BYTES:
        raise RegistryDocumentTooLarge("registry document exceeds maximum size")
    return encoded


def deserialize_snapshot(raw: bytes) -> AccountRegistrySnapshot:
    if len(raw) > MAX_REGISTRY_BYTES:
        raise OverflowError("registry document exceeds maximum size")
    try:
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _CorruptDocument("registry JSON is corrupt") from exc
    if not isinstance(envelope, dict):
        raise ValueError("registry envelope must be an object")
    if set(envelope) != {"schema_version", "digest_algorithm", "payload_sha256", "payload"}:
        raise ValueError("registry envelope fields do not match schema")
    if envelope["schema_version"] != REGISTRY_ENVELOPE_SCHEMA_VERSION:
        raise RuntimeError("unsupported registry envelope version")
    if envelope["digest_algorithm"] != "SHA256":
        raise RuntimeError("unsupported registry digest algorithm")
    expected = hashlib.sha256(_canonical_json(envelope["payload"])).hexdigest()
    if not isinstance(envelope["payload_sha256"], str) or not hmac.compare_digest(
        expected, envelope["payload_sha256"]
    ):
        raise _CorruptDocument("registry digest mismatch")
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise ValueError("registry payload must be an object")
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise RuntimeError("unsupported registry payload version")
    return AccountRegistrySnapshot.from_dict(payload)


class AccountRegistryStore:
    """Low-level store with explicit initialization and no constructor side effects."""

    def __init__(self, base_directory: Path, *, lock_timeout: float = 10.0) -> None:
        path = Path(base_directory)
        if not path.is_absolute():
            raise ValueError("account registry base directory must be absolute")
        if isinstance(lock_timeout, bool) or not isinstance(lock_timeout, (int, float)):
            raise TypeError("lock_timeout must be a number")
        if not math.isfinite(lock_timeout) or lock_timeout < 0:
            raise ValueError("lock_timeout must be a finite nonnegative number")
        self.base_directory = path
        self.registry_directory = path / "account_registry"
        self.snapshot_path = self.registry_directory / "account_registry.json"
        self.previous_path = self.registry_directory / "account_registry.previous.json"
        self.lock_path = self.registry_directory / ".account_registry.lock"
        self.lock_timeout = float(lock_timeout)
        self._thread_lock = RLock()

    def _registry_directory_state(self) -> str:
        try:
            info = os.lstat(self.registry_directory)
        except FileNotFoundError:
            return "MISSING"
        except OSError:
            return "UNSAFE"
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return "UNSAFE"
        if info.st_mode & 0o077:
            return "UNSAFE"
        return "SAFE"

    def _safe_registry_directory(self) -> bool:
        return self._registry_directory_state() == "SAFE"

    def _safe_base_directory(self) -> bool:
        try:
            info = os.lstat(self.base_directory)
        except OSError:
            return False
        return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)

    def load(self) -> RegistryLoadResult:
        """Read without creating directories, files, or locks."""
        state = self._registry_directory_state()
        if state == "MISSING":
            return RegistryLoadResult(RegistryLoadStatus.MISSING)
        if state == "UNSAFE":
            return RegistryLoadResult(RegistryLoadStatus.UNSAFE_PATH)
        return self._load_existing()

    def _load_existing(self) -> RegistryLoadResult:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.snapshot_path, flags)
        except FileNotFoundError:
            return RegistryLoadResult(RegistryLoadStatus.MISSING)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                return RegistryLoadResult(RegistryLoadStatus.UNSAFE_FILE)
            return RegistryLoadResult(RegistryLoadStatus.IO_ERROR)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                return RegistryLoadResult(RegistryLoadStatus.UNSAFE_FILE)
            if info.st_size > MAX_REGISTRY_BYTES:
                return RegistryLoadResult(RegistryLoadStatus.TOO_LARGE)
            chunks = []
            remaining = MAX_REGISTRY_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > MAX_REGISTRY_BYTES:
                return RegistryLoadResult(RegistryLoadStatus.TOO_LARGE)
        except OSError:
            return RegistryLoadResult(RegistryLoadStatus.IO_ERROR)
        finally:
            os.close(fd)
        try:
            return RegistryLoadResult(RegistryLoadStatus.VALID, deserialize_snapshot(raw))
        except OverflowError:
            return RegistryLoadResult(RegistryLoadStatus.TOO_LARGE)
        except RuntimeError:
            return RegistryLoadResult(RegistryLoadStatus.INCOMPATIBLE_VERSION)
        except _CorruptDocument:
            return RegistryLoadResult(RegistryLoadStatus.CORRUPT)
        except (TypeError, ValueError):
            return RegistryLoadResult(RegistryLoadStatus.INVALID)

    def initialize(
        self,
        *,
        now: Optional[datetime] = None,
        operation_id: str = "registry-initialize",
    ) -> RegistryMutationResult:
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID, 0, failure_code=RegistryFailureCode.INVALID_DOCUMENT
            )
        if not self._safe_base_directory():
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED, 0, failure_code=RegistryFailureCode.UNSAFE_STORAGE
            )
        state = self._registry_directory_state()
        if state == "MISSING":
            try:
                os.mkdir(self.registry_directory, 0o700)
            except FileExistsError:
                pass
            except OSError:
                return RegistryMutationResult(
                    RegistryMutationStatus.FAILED,
                    0,
                    failure_code=RegistryFailureCode.PERSISTENCE_FAILED,
                )
        if not self._safe_registry_directory():
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED, 0, failure_code=RegistryFailureCode.UNSAFE_STORAGE
            )
        try:
            with self._locked():
                loaded = self._load_existing()
                if loaded.status is RegistryLoadStatus.VALID:
                    return RegistryMutationResult(
                        RegistryMutationStatus.ALREADY_INITIALIZED,
                        loaded.snapshot.registry_revision,
                    )
                if loaded.status is not RegistryLoadStatus.MISSING:
                    return RegistryMutationResult(
                        RegistryMutationStatus.FAILED,
                        0,
                        failure_code=RegistryFailureCode.INVALID_DOCUMENT,
                    )
                fingerprint = _operation_fingerprint("INITIALIZE", None, {})
                event = self._event(
                    RegistryEventType.INITIALIZED,
                    1,
                    timestamp,
                    operation_id=operation_id,
                    request_fingerprint=fingerprint,
                )
                snapshot = AccountRegistrySnapshot(
                    REGISTRY_SCHEMA_VERSION, 1, (), (event,), timestamp, timestamp
                )
                return self._persist(snapshot, previous=None)
        except _LockFailure as exc:
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED, 0, failure_code=exc.code
            )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(self.lock_path, flags, 0o600)
            except OSError as exc:
                if exc.errno in {
                    errno.ELOOP,
                    errno.ENOTDIR,
                    errno.EACCES,
                    errno.EPERM,
                    errno.EISDIR,
                }:
                    raise _LockFailure(RegistryFailureCode.UNSAFE_STORAGE) from exc
                raise _LockFailure(RegistryFailureCode.LOCK_FAILED) from exc
            try:
                self._validate_lock_object(fd)
                self._acquire_flock(fd)
                try:
                    yield
                finally:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                os.close(fd)

    def _validate_lock_object(self, fd: int) -> None:
        try:
            info = os.fstat(fd)
        except OSError as exc:
            raise _LockFailure(RegistryFailureCode.LOCK_FAILED) from exc
        if not stat.S_ISREG(info.st_mode):
            raise _LockFailure(RegistryFailureCode.UNSAFE_STORAGE)
        if info.st_mode & 0o077:
            raise _LockFailure(RegistryFailureCode.UNSAFE_STORAGE)
        if info.st_uid != os.geteuid():
            raise _LockFailure(RegistryFailureCode.UNSAFE_STORAGE)

    def _acquire_flock(self, fd: int) -> None:
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as exc:
                if exc.errno not in {errno.EAGAIN, errno.EACCES}:
                    raise _LockFailure(RegistryFailureCode.LOCK_FAILED) from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _LockFailure(RegistryFailureCode.LOCK_TIMEOUT)
                time.sleep(min(0.01, remaining))

    def _event(
        self,
        event_type: RegistryEventType,
        revision: int,
        occurred_at: datetime,
        record: Optional[AccountRegistryRecord] = None,
        changed_fields: tuple[str, ...] = (),
        *,
        operation_id: str,
        request_fingerprint: str,
    ) -> AccountRegistryEvent:
        return AccountRegistryEvent(
            schema_version=REGISTRY_EVENT_SCHEMA_VERSION,
            event_id=f"evt_{uuid4().hex}",
            event_type=event_type,
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
            registry_revision=revision,
            account_id=record.identity.account_id if record else None,
            record_revision=record.record_revision if record else None,
            identity_revision=record.identity.revision if record else None,
            changed_fields=changed_fields,
            occurred_at=occurred_at,
        )

    def _write_file(self, target: Path, raw: bytes, *, commit_target: bool) -> bool:
        temp = target.with_name(f".{target.name}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = None
        replaced = False
        try:
            fd = os.open(temp, flags, 0o600)
            os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = None
            self._replace(temp, target)
            replaced = True
            os.chmod(target, 0o600, follow_symlinks=False)
            self._fsync_directory()
            return True
        except OSError:
            if commit_target and replaced:
                raise _CommitStateUnknown
            raise
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass

    def _replace(self, source: Path, target: Path) -> None:
        os.replace(source, target)

    def _fsync_directory(self) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        fd = os.open(self.registry_directory, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _persist(
        self,
        snapshot: AccountRegistrySnapshot,
        *,
        previous: Optional[AccountRegistrySnapshot],
    ) -> RegistryMutationResult:
        current_revision = previous.registry_revision if previous else 0
        try:
            target_bytes = serialize_snapshot(snapshot)
            previous_bytes = serialize_snapshot(previous) if previous is not None else None
        except RegistryDocumentTooLarge:
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED,
                current_revision,
                failure_code=RegistryFailureCode.SIZE_LIMIT_EXCEEDED,
            )
        except (TypeError, ValueError):
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED,
                current_revision,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        try:
            if previous_bytes is not None:
                self._write_file(self.previous_path, previous_bytes, commit_target=False)
            self._write_file(self.snapshot_path, target_bytes, commit_target=True)
        except _CommitStateUnknown:
            return RegistryMutationResult(
                RegistryMutationStatus.COMMIT_STATE_UNKNOWN,
                snapshot.registry_revision,
                failure_code=RegistryFailureCode.COMMIT_STATE_UNKNOWN,
            )
        except OSError:
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED,
                current_revision,
                failure_code=RegistryFailureCode.PERSISTENCE_FAILED,
            )
        return RegistryMutationResult(RegistryMutationStatus.SAVED, snapshot.registry_revision)


class _LockFailure(Exception):
    def __init__(self, code: RegistryFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


class _CommitStateUnknown(Exception):
    pass


class _CorruptDocument(ValueError):
    pass


class DurableAccountRegistry:
    """Registry operations over the atomic store; contains no runtime authority."""

    def __init__(
        self,
        store: AccountRegistryStore,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        id_factory: Optional[Callable[[], AccountId]] = None,
    ) -> None:
        self.store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or AccountId.new

    def initialize(self, *, operation_id: str = "registry-initialize") -> RegistryMutationResult:
        return self.store.initialize(now=self._now(), operation_id=operation_id)

    def get(
        self, account_id: AccountId, *, expected_registry_revision: Optional[int] = None
    ) -> AccountLookupResult:
        loaded = self.store.load()
        if loaded.status is not RegistryLoadStatus.VALID:
            return AccountLookupResult(RegistryLookupStatus.INVALID, None, 0)
        snapshot = loaded.snapshot
        if expected_registry_revision is not None and snapshot.registry_revision != expected_registry_revision:
            return AccountLookupResult(
                RegistryLookupStatus.INVALID, None, snapshot.registry_revision
            )
        record = snapshot.find(account_id)
        return AccountLookupResult(
            RegistryLookupStatus.FOUND if record else RegistryLookupStatus.NOT_FOUND,
            record.identity if record else None,
            snapshot.registry_revision,
        )

    def find_by_external_ref(
        self,
        execution_venue: ExecutionVenue,
        external_account_ref: str,
        *,
        expected_registry_revision: Optional[int] = None,
    ) -> AccountLookupResult:
        loaded = self.store.load()
        if loaded.status is not RegistryLoadStatus.VALID:
            return AccountLookupResult(RegistryLookupStatus.INVALID, None, 0)
        snapshot = loaded.snapshot
        if expected_registry_revision is not None and snapshot.registry_revision != expected_registry_revision:
            return AccountLookupResult(RegistryLookupStatus.INVALID, None, snapshot.registry_revision)
        record = next(
            (
                item
                for item in snapshot.records
                if item.external_binding
                and item.external_binding.venue is execution_venue
                and item.external_binding.binding_key == external_account_ref
            ),
            None,
        )
        return AccountLookupResult(
            RegistryLookupStatus.FOUND if record else RegistryLookupStatus.NOT_FOUND,
            record.identity if record else None,
            snapshot.registry_revision,
        )

    def register(
        self,
        draft: AccountRegistrationDraft,
        *,
        expected_registry_revision: int,
        operation_id: str,
    ) -> AccountRegistrationResult:
        if not isinstance(draft, AccountRegistrationDraft):
            return AccountRegistrationResult(RegistryRegistrationStatus.INVALID, None, 0)
        try:
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return AccountRegistrationResult(
                RegistryRegistrationStatus.INVALID,
                None,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        if not _valid_expected_revision(expected_registry_revision):
            return AccountRegistrationResult(
                RegistryRegistrationStatus.INVALID,
                None,
                0,
                operation_id=operation_id,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        fingerprint = _operation_fingerprint(
            "REGISTER", None, _registration_payload(draft)
        )
        state = self.store._registry_directory_state()
        if state == "MISSING":
            return AccountRegistrationResult(
                RegistryRegistrationStatus.NOT_INITIALIZED,
                None,
                0,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
                failure_code=RegistryFailureCode.NOT_INITIALIZED,
            )
        if state != "SAFE":
            return AccountRegistrationResult(
                RegistryRegistrationStatus.FAILED,
                None,
                0,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
                failure_code=RegistryFailureCode.UNSAFE_STORAGE,
            )
        try:
            with self.store._locked():
                loaded = self.store._load_existing()
                if loaded.status is RegistryLoadStatus.MISSING:
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.NOT_INITIALIZED,
                        None,
                        0,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        failure_code=RegistryFailureCode.NOT_INITIALIZED,
                    )
                if loaded.status is not RegistryLoadStatus.VALID:
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.INVALID,
                        None,
                        0,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        failure_code=RegistryFailureCode.INVALID_DOCUMENT,
                    )
                old = loaded.snapshot
                prior_event = _find_operation_event(old, operation_id)
                if prior_event is not None:
                    if prior_event.request_fingerprint != fingerprint:
                        return AccountRegistrationResult(
                            RegistryRegistrationStatus.CONFLICT,
                            None,
                            old.registry_revision,
                            operation_id=operation_id,
                            request_fingerprint=fingerprint,
                            original_registry_revision=prior_event.registry_revision,
                            failure_code=RegistryFailureCode.IDEMPOTENCY_CONFLICT,
                        )
                    prior = old.find(prior_event.account_id)
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.IDEMPOTENT_REPLAY,
                        prior.identity if prior else None,
                        old.registry_revision,
                        operation_id=prior_event.operation_id,
                        request_fingerprint=prior_event.request_fingerprint,
                        original_registry_revision=prior_event.registry_revision,
                    )
                prior = next(
                    (x for x in old.records if x.registration_request_id == draft.registration_request_id),
                    None,
                )
                if prior:
                    registration_event = _registration_event(old, prior.identity.account_id)
                    if self._draft_matches(draft, prior):
                        return AccountRegistrationResult(
                            RegistryRegistrationStatus.IDEMPOTENT_REPLAY,
                            prior.identity,
                            old.registry_revision,
                            operation_id=(
                                registration_event.operation_id
                                if registration_event is not None
                                else operation_id
                            ),
                            request_fingerprint=(
                                registration_event.request_fingerprint
                                if registration_event is not None
                                else fingerprint
                            ),
                            original_registry_revision=(
                                registration_event.registry_revision
                                if registration_event is not None
                                else None
                            ),
                        )
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.CONFLICT,
                        None,
                        old.registry_revision,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        failure_code=RegistryFailureCode.IDEMPOTENCY_CONFLICT,
                    )
                if old.registry_revision != expected_registry_revision:
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.CONFLICT,
                        None,
                        old.registry_revision,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        failure_code=RegistryFailureCode.REVISION_MISMATCH,
                    )
                account_id = self._id_factory()
                if old.find(account_id):
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.ALREADY_EXISTS,
                        None,
                        old.registry_revision,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        failure_code=RegistryFailureCode.DUPLICATE_ACCOUNT_ID,
                    )
                now = self._now()
                identity = AccountIdentity(
                    ACCOUNT_IDENTITY_SCHEMA_VERSION,
                    account_id,
                    draft.account_type,
                    draft.execution_mode,
                    draft.execution_venue,
                    AccountLifecycleState.REGISTERED,
                    1,
                    now,
                    now,
                    draft.prop_program,
                    draft.prop_phase,
                )
                record = AccountRegistryRecord(
                    REGISTRY_RECORD_SCHEMA_VERSION,
                    identity,
                    draft.display_label,
                    draft.credential_reference,
                    draft.external_binding,
                    draft.registration_source,
                    draft.registration_request_id,
                    1,
                    now,
                    now,
                    draft.predecessor_account_id,
                )
                revision = old.registry_revision + 1
                event = self.store._event(
                    RegistryEventType.REGISTERED,
                    revision,
                    now,
                    record,
                    ("identity", "display_label", "credential_reference", "external_binding"),
                    operation_id=operation_id,
                    request_fingerprint=fingerprint,
                )
                new = AccountRegistrySnapshot(
                    REGISTRY_SCHEMA_VERSION,
                    revision,
                    old.records + (record,),
                    old.events + (event,),
                    old.created_at,
                    now,
                )
                saved = self.store._persist(new, previous=old)
                if saved.status is RegistryMutationStatus.SAVED:
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.REGISTERED,
                        identity,
                        saved.registry_revision,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        original_registry_revision=saved.registry_revision,
                    )
                if saved.status is RegistryMutationStatus.COMMIT_STATE_UNKNOWN:
                    return AccountRegistrationResult(
                        RegistryRegistrationStatus.COMMIT_STATE_UNKNOWN,
                        None,
                        saved.registry_revision,
                        operation_id=operation_id,
                        request_fingerprint=fingerprint,
                        original_registry_revision=saved.registry_revision,
                        failure_code=RegistryFailureCode.COMMIT_STATE_UNKNOWN,
                    )
                return AccountRegistrationResult(
                    RegistryRegistrationStatus.FAILED,
                    None,
                    saved.registry_revision,
                    operation_id=operation_id,
                    request_fingerprint=fingerprint,
                    failure_code=saved.failure_code,
                )
        except _LockFailure as exc:
            return AccountRegistrationResult(
                RegistryRegistrationStatus.FAILED,
                None,
                0,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
                failure_code=exc.code,
            )

    def find_operation(self, operation_id: str) -> RegistryOperationReceipt:
        """Read the durable operation ledger without mutating the registry."""

        try:
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return RegistryOperationReceipt(
                RegistryOperationLookupStatus.INVALID,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        loaded = self.store.load()
        if loaded.status is not RegistryLoadStatus.VALID or loaded.snapshot is None:
            return RegistryOperationReceipt(
                RegistryOperationLookupStatus.INVALID,
                operation_id=operation_id,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        snapshot = loaded.snapshot
        event = _find_operation_event(snapshot, operation_id)
        if event is None:
            return RegistryOperationReceipt(
                RegistryOperationLookupStatus.NOT_FOUND,
                current_registry_revision=snapshot.registry_revision,
                operation_id=operation_id,
            )
        record = snapshot.find(event.account_id) if event.account_id is not None else None
        return RegistryOperationReceipt(
            RegistryOperationLookupStatus.FOUND,
            current_registry_revision=snapshot.registry_revision,
            operation_id=event.operation_id,
            request_fingerprint=event.request_fingerprint,
            event_type=event.event_type,
            account_id=event.account_id,
            original_registry_revision=event.registry_revision,
            record_revision_at_event=event.record_revision,
            identity_revision_at_event=event.identity_revision,
            occurred_at=event.occurred_at,
            current_record_revision=record.record_revision if record else None,
            current_lifecycle_state=(
                record.identity.lifecycle_state if record else None
            ),
        )

    def update_label(
        self,
        account_id: AccountId,
        display_label: str,
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        if not isinstance(account_id, AccountId):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        try:
            label = _normalize_label(display_label)
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        fingerprint = _operation_fingerprint(
            "UPDATE_LABEL", account_id, {"display_label": label}
        )
        return self._update(
            account_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            event_type=RegistryEventType.LABEL_UPDATED,
            changed_fields=("display_label",),
            mutation=lambda record, now: replace(
                record,
                display_label=label,
                record_revision=record.record_revision + 1,
                updated_at=now,
            ),
        )

    def rotate_credential_reference(
        self,
        account_id: AccountId,
        credential_reference: Optional[CredentialBundleReference],
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        if not isinstance(account_id, AccountId):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        if credential_reference is not None and not isinstance(
            credential_reference, CredentialBundleReference
        ):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                expected_registry_revision,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        try:
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        fingerprint = _operation_fingerprint(
            "ROTATE_CREDENTIAL_REFERENCE",
            account_id,
            {
                "credential_reference": (
                    credential_reference.to_dict() if credential_reference else None
                )
            },
        )
        return self._update(
            account_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            event_type=RegistryEventType.CREDENTIAL_REFERENCE_UPDATED,
            changed_fields=("credential_reference",),
            mutation=lambda record, now: replace(
                record,
                credential_reference=credential_reference,
                record_revision=record.record_revision + 1,
                updated_at=now,
            ),
        )

    def update_external_binding(
        self,
        account_id: AccountId,
        external_binding: Optional[ExternalAccountBinding],
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        if not isinstance(account_id, AccountId):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        if external_binding is not None and not isinstance(
            external_binding, ExternalAccountBinding
        ):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                expected_registry_revision,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        try:
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        fingerprint = _operation_fingerprint(
            "UPDATE_EXTERNAL_BINDING",
            account_id,
            {
                "external_binding": (
                    external_binding.to_dict() if external_binding else None
                )
            },
        )
        return self._update(
            account_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            event_type=RegistryEventType.EXTERNAL_BINDING_UPDATED,
            changed_fields=("external_binding",),
            mutation=lambda record, now: replace(
                record,
                external_binding=external_binding,
                record_revision=record.record_revision + 1,
                updated_at=now,
            ),
        )

    def disable(
        self,
        account_id: AccountId,
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        return self._lifecycle(
            account_id,
            AccountLifecycleState.DISABLED,
            RegistryEventType.DISABLED,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            operation_id=operation_id,
        )

    def enable(
        self,
        account_id: AccountId,
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        return self._lifecycle(
            account_id,
            AccountLifecycleState.REGISTERED,
            RegistryEventType.ENABLED,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            operation_id=operation_id,
        )

    def retire(
        self,
        account_id: AccountId,
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        return self._lifecycle(
            account_id,
            AccountLifecycleState.RETIRED,
            RegistryEventType.RETIRED,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            operation_id=operation_id,
        )

    def _lifecycle(
        self,
        account_id: AccountId,
        target: AccountLifecycleState,
        event_type: RegistryEventType,
        *,
        expected_registry_revision: int,
        expected_record_revision: int,
        operation_id: str,
    ) -> RegistryMutationResult:
        if not isinstance(account_id, AccountId):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        try:
            operation_id = _validate_operation_id("operation_id", operation_id)
        except (TypeError, ValueError):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
            )
        fingerprint = _operation_fingerprint(
            event_type.value, account_id, {"target_lifecycle_state": target.value}
        )

        def transition(record: AccountRegistryRecord, now: datetime) -> AccountRegistryRecord:
            current = record.identity.lifecycle_state
            allowed = {
                (AccountLifecycleState.REGISTERED, AccountLifecycleState.DISABLED),
                (AccountLifecycleState.DISABLED, AccountLifecycleState.REGISTERED),
                (AccountLifecycleState.REGISTERED, AccountLifecycleState.RETIRED),
                (AccountLifecycleState.DISABLED, AccountLifecycleState.RETIRED),
            }
            if (current, target) not in allowed:
                raise _InvalidTransition
            return replace(
                record,
                record_revision=record.record_revision + 1,
                identity=replace(
                    record.identity,
                    lifecycle_state=target,
                    revision=record.identity.revision + 1,
                    updated_at=now,
                ),
                updated_at=now,
            )

        return self._update(
            account_id,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
            expected_registry_revision=expected_registry_revision,
            expected_record_revision=expected_record_revision,
            event_type=event_type,
            changed_fields=("lifecycle_state",),
            mutation=transition,
        )

    def _update(
        self,
        account_id: AccountId,
        *,
        operation_id: str,
        request_fingerprint: str,
        expected_registry_revision: int,
        expected_record_revision: int,
        event_type: RegistryEventType,
        changed_fields: tuple[str, ...],
        mutation: Callable[[AccountRegistryRecord, datetime], AccountRegistryRecord],
    ) -> RegistryMutationResult:
        if not _valid_expected_revision(expected_registry_revision) or not _valid_expected_revision(
            expected_record_revision
        ):
            return RegistryMutationResult(
                RegistryMutationStatus.INVALID,
                0,
                failure_code=RegistryFailureCode.INVALID_DOCUMENT,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint,
            )
        state = self.store._registry_directory_state()
        if state == "MISSING":
            return RegistryMutationResult(
                RegistryMutationStatus.NOT_INITIALIZED,
                0,
                failure_code=RegistryFailureCode.NOT_INITIALIZED,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint,
            )
        if state != "SAFE":
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED,
                0,
                failure_code=RegistryFailureCode.UNSAFE_STORAGE,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint,
            )
        try:
            with self.store._locked():
                loaded = self.store._load_existing()
                if loaded.status is RegistryLoadStatus.MISSING:
                    return RegistryMutationResult(
                        RegistryMutationStatus.NOT_INITIALIZED,
                        0,
                        failure_code=RegistryFailureCode.NOT_INITIALIZED,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                if loaded.status is not RegistryLoadStatus.VALID:
                    return RegistryMutationResult(
                        RegistryMutationStatus.FAILED,
                        0,
                        failure_code=RegistryFailureCode.INVALID_DOCUMENT,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                old = loaded.snapshot
                prior_event = _find_operation_event(old, operation_id)
                if prior_event is not None:
                    if prior_event.request_fingerprint != request_fingerprint:
                        return RegistryMutationResult(
                            RegistryMutationStatus.CONFLICT,
                            old.registry_revision,
                            failure_code=RegistryFailureCode.IDEMPOTENCY_CONFLICT,
                            operation_id=operation_id,
                            request_fingerprint=request_fingerprint,
                            original_registry_revision=prior_event.registry_revision,
                        )
                    current_record = (
                        old.find(prior_event.account_id)
                        if prior_event.account_id is not None
                        else None
                    )
                    return RegistryMutationResult(
                        RegistryMutationStatus.IDEMPOTENT_REPLAY,
                        old.registry_revision,
                        current_record,
                        operation_id=prior_event.operation_id,
                        request_fingerprint=prior_event.request_fingerprint,
                        original_registry_revision=prior_event.registry_revision,
                    )
                if old.registry_revision != expected_registry_revision:
                    return RegistryMutationResult(
                        RegistryMutationStatus.CONFLICT,
                        old.registry_revision,
                        failure_code=RegistryFailureCode.REVISION_MISMATCH,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                record = old.find(account_id)
                if record is None:
                    return RegistryMutationResult(
                        RegistryMutationStatus.NOT_FOUND,
                        old.registry_revision,
                        failure_code=RegistryFailureCode.NONE,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                if record.record_revision != expected_record_revision:
                    return RegistryMutationResult(
                        RegistryMutationStatus.CONFLICT,
                        old.registry_revision,
                        record,
                        RegistryFailureCode.RECORD_REVISION_MISMATCH,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                now = self._now()
                try:
                    changed = mutation(record, now)
                except _InvalidTransition:
                    return RegistryMutationResult(
                        RegistryMutationStatus.INVALID,
                        old.registry_revision,
                        record,
                        RegistryFailureCode.INVALID_TRANSITION,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                except (TypeError, ValueError):
                    return RegistryMutationResult(
                        RegistryMutationStatus.INVALID,
                        old.registry_revision,
                        record,
                        RegistryFailureCode.INVALID_DOCUMENT,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                records = tuple(changed if item.identity.account_id == account_id else item for item in old.records)
                revision = old.registry_revision + 1
                event = self.store._event(
                    event_type,
                    revision,
                    now,
                    changed,
                    changed_fields,
                    operation_id=operation_id,
                    request_fingerprint=request_fingerprint,
                )
                try:
                    new = AccountRegistrySnapshot(
                        REGISTRY_SCHEMA_VERSION,
                        revision,
                        records,
                        old.events + (event,),
                        old.created_at,
                        now,
                    )
                except (TypeError, ValueError):
                    return RegistryMutationResult(
                        RegistryMutationStatus.INVALID,
                        old.registry_revision,
                        record,
                        RegistryFailureCode.INVALID_DOCUMENT,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                    )
                saved = self.store._persist(new, previous=old)
                if saved.status is RegistryMutationStatus.SAVED:
                    return replace(
                        saved,
                        record=changed,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                        original_registry_revision=saved.registry_revision,
                    )
                if saved.status is RegistryMutationStatus.COMMIT_STATE_UNKNOWN:
                    return replace(
                        saved,
                        record=None,
                        operation_id=operation_id,
                        request_fingerprint=request_fingerprint,
                        original_registry_revision=saved.registry_revision,
                    )
                return replace(
                    saved,
                    record=None,
                    operation_id=operation_id,
                    request_fingerprint=request_fingerprint,
                )
        except _LockFailure as exc:
            return RegistryMutationResult(
                RegistryMutationStatus.FAILED,
                0,
                failure_code=exc.code,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint,
            )

    def _draft_matches(self, draft: AccountRegistrationDraft, record: AccountRegistryRecord) -> bool:
        identity = record.identity
        return (
            identity.account_type is draft.account_type
            and identity.execution_mode is draft.execution_mode
            and identity.execution_venue is draft.execution_venue
            and identity.prop_program is draft.prop_program
            and identity.prop_phase is draft.prop_phase
            and record.display_label == draft.display_label
            and record.registration_source is draft.registration_source
            and record.credential_reference == draft.credential_reference
            and record.external_binding == draft.external_binding
            and record.predecessor_account_id == draft.predecessor_account_id
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("registry clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


class _InvalidTransition(Exception):
    pass
