"""MM-4D explicit, fail-closed loss-limit checkpoint coordinator."""
from hashlib import sha256
from threading import RLock

from .loss_persistence_adapter import LossPersistenceSaveResult, SaveStatus
from .loss_persistence_serialization import build_canonical_loss_state_json
from .loss_runtime_checkpoint_models import (
    CheckpointFailureCode,
    CheckpointMode,
    CheckpointStatus,
    LossLimitRuntimeCheckpointFailure,
    LossLimitRuntimeCheckpointRequest,
    LossLimitRuntimeCheckpointResult,
)
from .loss_runtime_integration_models import SaveTrigger
from .loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
    StoreResultStatus,
)


def _failure(code, message, trigger=None, status=CheckpointStatus.FAILED):
    failure = None
    if status is CheckpointStatus.FAILED:
        failure = LossLimitRuntimeCheckpointFailure(code, message)
    return LossLimitRuntimeCheckpointResult(
        status, None, None, trigger, False, True, failure
    )


class LossLimitRuntimeCheckpointCoordinator:
    """Serializes checkpoints for one process without mutating runtime state."""

    def __init__(
        self,
        persistence_adapter,
        runtime_store,
        last_saved_revision=None,
        last_saved_sequence=None,
        last_saved_canonical_state=None,
    ):
        if (last_saved_revision is None) != (last_saved_sequence is None):
            raise ValueError("checkpoint metadata must be complete")
        if last_saved_revision is not None and (
            type(last_saved_revision) is not int
            or last_saved_revision < 1
            or type(last_saved_sequence) is not int
            or last_saved_sequence < 1
        ):
            raise ValueError("invalid checkpoint metadata")
        if last_saved_canonical_state is not None and not isinstance(
            last_saved_canonical_state, bytes
        ):
            raise TypeError("canonical state must be bytes")
        self._adapter = persistence_adapter
        self._store = runtime_store
        self._last_revision = last_saved_revision
        self._last_sequence = last_saved_sequence
        self._last_canonical = last_saved_canonical_state
        self._lock = RLock()

    @property
    def last_saved_revision(self):
        return self._last_revision

    @property
    def last_saved_sequence(self):
        return self._last_sequence

    def _read_snapshot(self):
        result = self._store.get_snapshot()
        if (
            result.status is not StoreResultStatus.SUCCEEDED
            or not isinstance(result.snapshot, LossLimitRuntimeSnapshot)
        ):
            return None
        return result.snapshot

    @staticmethod
    def _trigger_allowed(request, snapshot):
        if request.checkpoint_mode is CheckpointMode.MANUAL:
            return request.trigger is SaveTrigger.MANUAL_CHECKPOINT
        if request.checkpoint_mode is CheckpointMode.SHUTDOWN:
            return request.trigger is SaveTrigger.RUNTIME_SHUTDOWN
        return request.trigger in snapshot.save_triggers

    def checkpoint(self, request):
        if not isinstance(request, LossLimitRuntimeCheckpointRequest):
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_REQUEST_INVALID,
                "invalid checkpoint request",
            )
        try:
            snapshot = self._read_snapshot()
        except Exception:
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_INTERNAL_FAILURE,
                "checkpoint unavailable",
                request.trigger,
            )
        if snapshot is None:
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_STORE_NOT_INITIALIZED,
                "runtime store not initialized",
                request.trigger,
            )
        try:
            canonical = build_canonical_loss_state_json(snapshot.state)
        except Exception:
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_SNAPSHOT_INVALID,
                "runtime snapshot invalid",
                request.trigger,
            )
        if request.expected_revision != snapshot.revision:
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_REVISION_MISMATCH,
                "checkpoint revision mismatch",
                request.trigger,
            )
        if request.expected_sequence != snapshot.sequence:
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_SEQUENCE_MISMATCH,
                "checkpoint sequence mismatch",
                request.trigger,
            )
        fingerprint = sha256(canonical).hexdigest()
        if (
            request.expected_snapshot_fingerprint is not None
            and request.expected_snapshot_fingerprint != fingerprint
        ):
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_CONFLICT,
                "checkpoint fingerprint conflict",
                request.trigger,
            )
        if not self._trigger_allowed(request, snapshot):
            return _failure(
                CheckpointFailureCode.LOSS_CHECKPOINT_TRIGGER_INVALID,
                "checkpoint trigger invalid",
                request.trigger,
            )
        with self._lock:
            if self._last_revision is not None:
                pair = (snapshot.revision, snapshot.sequence)
                last = (self._last_revision, self._last_sequence)
                if pair < last:
                    return LossLimitRuntimeCheckpointResult(
                        CheckpointStatus.STALE,
                        self._last_revision,
                        self._last_sequence,
                        request.trigger,
                        False,
                        True,
                        None,
                    )
                if pair == last:
                    if canonical == self._last_canonical:
                        return LossLimitRuntimeCheckpointResult(
                            CheckpointStatus.IDEMPOTENT,
                            self._last_revision,
                            self._last_sequence,
                            request.trigger,
                            True,
                            False,
                            None,
                        )
                    return LossLimitRuntimeCheckpointResult(
                        CheckpointStatus.CONFLICT,
                        self._last_revision,
                        self._last_sequence,
                        request.trigger,
                        False,
                        True,
                        None,
                    )
                if (
                    snapshot.revision != self._last_revision + 1
                    or snapshot.sequence != self._last_sequence + 1
                ):
                    return _failure(
                        CheckpointFailureCode.LOSS_CHECKPOINT_SEQUENCE_GAP,
                        "checkpoint sequence gap",
                        request.trigger,
                    )
            try:
                result = self._adapter.save(snapshot.state)
            except Exception:
                return _failure(
                    CheckpointFailureCode.LOSS_CHECKPOINT_SAVE_FAILED,
                    "persistence save failed",
                    request.trigger,
                )
            if not isinstance(result, LossPersistenceSaveResult):
                return _failure(
                    CheckpointFailureCode.LOSS_CHECKPOINT_SAVE_RESULT_INVALID,
                    "persistence result invalid",
                    request.trigger,
                )
            if result.status is not SaveStatus.SAVED:
                return _failure(
                    CheckpointFailureCode.LOSS_CHECKPOINT_SAVE_FAILED,
                    "persistence save failed",
                    request.trigger,
                )
            self._last_revision = snapshot.revision
            self._last_sequence = snapshot.sequence
            self._last_canonical = canonical
            return LossLimitRuntimeCheckpointResult(
                CheckpointStatus.SUCCEEDED,
                snapshot.revision,
                snapshot.sequence,
                request.trigger,
                True,
                False,
                None,
                SaveStatus.SAVED.value,
            )
