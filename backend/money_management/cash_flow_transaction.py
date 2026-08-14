"""Crash-consistent MM loss-state and external cash-flow checkpoint commit."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from .external_cash_flow import (
    CashFlowCheckpoint, _payload as checkpoint_payload,
    load_cash_flow_checkpoint, save_cash_flow_checkpoint,
)
from .loss_persistence_adapter import (
    LoadStatus, SaveStatus, _state, load_loss_state, save_loss_state,
)
from .loss_persistence_models import PersistedLossState


SCHEMA_VERSION = "money-management-cash-flow-transaction/v1"
JOURNAL_FILENAME = ".cash_flow_transaction.json"
MAX_JOURNAL_SIZE = 2 * 1024 * 1024


class CashFlowTransactionError(RuntimeError):
    pass


class CashFlowCASConflict(CashFlowTransactionError):
    pass


@dataclass(frozen=True)
class CashFlowCommitResult:
    transaction_id: str
    revision: int
    event_ids: tuple[str, ...]
    recovered: bool = False


class CashFlowTransactionCoordinator:
    """Production composition boundary; it performs no exchange mutations."""

    def __init__(self, base_directory):
        self._base_directory = _safe_base(base_directory)

    @property
    def poll_interval_seconds(self):
        # History reconciliation is deliberately independent of the 10s AMS loop.
        return 300

    def recover(self):
        return recover_cash_flow_transaction(self._base_directory)

    def commit(self, *, expected_revision, new_state, new_checkpoint,
               event_ids, now=None):
        return commit_cash_flow_transaction(
            base_directory=self._base_directory,
            expected_revision=expected_revision, new_state=new_state,
            new_checkpoint=new_checkpoint, event_ids=event_ids, now=now,
        )


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _directory_fsync(base):
    fd = os.open(base, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _safe_base(base_directory):
    base = Path(base_directory)
    if not base.is_absolute() or not base.is_dir() or base.is_symlink():
        raise OSError("unsafe transaction directory")
    return base


def _journal_path(base):
    return base / JOURNAL_FILENAME


def _write_journal(base, payload):
    target = _journal_path(base)
    temporary = base / (JOURNAL_FILENAME + ".tmp")
    if target.exists() or temporary.exists():
        raise CashFlowTransactionError("cash-flow transaction already pending")
    envelope = {"integrityAlgorithm": "SHA256", "payload": payload,
                "integrityDigest": _digest(payload)}
    raw = _canonical(envelope)
    if len(raw) > MAX_JOURNAL_SIZE:
        raise CashFlowTransactionError("cash-flow transaction too large")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    raise OSError("short journal write")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, target)
        _directory_fsync(base)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _read_journal(base):
    target = _journal_path(base)
    if not target.exists():
        return None
    info = target.stat()
    if target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise CashFlowTransactionError("unsafe cash-flow transaction journal")
    if info.st_size > MAX_JOURNAL_SIZE:
        raise CashFlowTransactionError("cash-flow transaction journal too large")
    envelope = json.loads(target.read_text("utf-8"))
    if set(envelope) != {"integrityAlgorithm", "integrityDigest", "payload"}:
        raise CashFlowTransactionError("cash-flow transaction journal invalid")
    if envelope["integrityAlgorithm"] != "SHA256" or not hmac.compare_digest(
            str(envelope["integrityDigest"]), _digest(envelope["payload"])):
        raise CashFlowTransactionError("cash-flow transaction journal integrity invalid")
    payload = envelope["payload"]
    required = {"schemaVersion", "transactionId", "oldRevision", "newRevision",
                "eventIds", "oldStateDigest", "newStateDigest",
                "oldCheckpointDigest", "newCheckpointDigest", "newState",
                "newCheckpoint", "status", "preparedAt"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise CashFlowTransactionError("cash-flow transaction journal invalid")
    if payload["schemaVersion"] != SCHEMA_VERSION or payload["status"] != "COMMIT_INTENT":
        raise CashFlowTransactionError("cash-flow transaction journal incompatible")
    return payload


def _load_authority(base):
    state_result = load_loss_state(base)
    if state_result.status is not LoadStatus.VALID:
        raise CashFlowTransactionError("authoritative MM state unavailable")
    checkpoint = load_cash_flow_checkpoint(base)
    return state_result.state, checkpoint


def _authority_digests(state, checkpoint):
    return _digest(state.to_dict()), _digest(checkpoint_payload(checkpoint))


def _checkpoint_from_payload(value):
    expected = {"schemaVersion", "source", "lastSuccessfulSyncAt", "processedEventIds", "revision"}
    if not isinstance(value, dict) or set(value) != expected:
        raise CashFlowTransactionError("checkpoint transaction payload invalid")
    at = value["lastSuccessfulSyncAt"]
    parsed = datetime.fromisoformat(at.replace("Z", "+00:00")) if at else None
    return CashFlowCheckpoint(parsed, tuple(value["processedEventIds"]),
                              value["source"], value["schemaVersion"], value["revision"])


def _finish(base, payload, *, recovered):
    state, checkpoint = _load_authority(base)
    state_digest, checkpoint_digest = _authority_digests(state, checkpoint)
    if state_digest not in {payload["oldStateDigest"], payload["newStateDigest"]}:
        raise CashFlowCASConflict("MM state changed during cash-flow transaction")
    if checkpoint_digest not in {payload["oldCheckpointDigest"], payload["newCheckpointDigest"]}:
        raise CashFlowCASConflict("checkpoint changed during cash-flow transaction")
    new_state = _state(payload["newState"])
    new_checkpoint = _checkpoint_from_payload(payload["newCheckpoint"])
    if state_digest != payload["newStateDigest"]:
        result = save_loss_state(new_state, base)
        if result.status is not SaveStatus.SAVED:
            raise CashFlowTransactionError("MM state commit failed")
    if checkpoint_digest != payload["newCheckpointDigest"]:
        save_cash_flow_checkpoint(new_checkpoint, base)
    final_state, final_checkpoint = _load_authority(base)
    if _authority_digests(final_state, final_checkpoint) != (
            payload["newStateDigest"], payload["newCheckpointDigest"]):
        raise CashFlowTransactionError("cash-flow transaction verification failed")
    _journal_path(base).unlink()
    _directory_fsync(base)
    return CashFlowCommitResult(payload["transactionId"], payload["newRevision"],
                                tuple(payload["eventIds"]), recovered)


def recover_cash_flow_transaction(base_directory):
    base = _safe_base(base_directory)
    payload = _read_journal(base)
    return _finish(base, payload, recovered=True) if payload else None


def commit_cash_flow_transaction(*, base_directory, expected_revision, new_state,
                                 new_checkpoint, event_ids, now=None):
    base = _safe_base(base_directory)
    if _read_journal(base) is not None:
        recover_cash_flow_transaction(base)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected revision must be a nonnegative integer")
    if not isinstance(new_state, PersistedLossState) or not isinstance(new_checkpoint, CashFlowCheckpoint):
        raise TypeError("typed MM state and checkpoint required")
    old_state, old_checkpoint = _load_authority(base)
    old_state_digest, old_checkpoint_digest = _authority_digests(old_state, old_checkpoint)
    current_revision = old_checkpoint.revision
    if expected_revision != current_revision:
        raise CashFlowCASConflict("cash-flow transaction revision conflict")
    ids = tuple(event_ids)
    if len(ids) != len(set(ids)) or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError("unique event IDs required")
    if any(item in old_checkpoint.processed_event_ids for item in ids):
        raise CashFlowCASConflict("cash-flow event already committed")
    if any(item not in new_checkpoint.processed_event_ids for item in ids):
        raise ValueError("new checkpoint does not contain every event")
    if new_checkpoint.revision != current_revision + len(ids):
        raise ValueError("new checkpoint revision mismatch")
    prepared = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "schemaVersion": SCHEMA_VERSION, "transactionId": uuid4().hex,
        "oldRevision": current_revision, "newRevision": current_revision + len(ids),
        "eventIds": list(ids), "oldStateDigest": old_state_digest,
        "newStateDigest": _digest(new_state.to_dict()),
        "oldCheckpointDigest": old_checkpoint_digest,
        "newCheckpointDigest": _digest(checkpoint_payload(new_checkpoint)),
        "newState": new_state.to_dict(), "newCheckpoint": checkpoint_payload(new_checkpoint),
        "status": "COMMIT_INTENT", "preparedAt": prepared.isoformat().replace("+00:00", "Z"),
    }
    _write_journal(base, payload)
    return _finish(base, payload, recovered=False)
