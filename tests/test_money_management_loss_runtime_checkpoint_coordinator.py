import unittest
from datetime import datetime, timezone

from backend.money_management.loss_persistence_adapter import (
    LossPersistenceSaveResult,
    SaveFailureCode,
    SaveStatus,
)
from backend.money_management.loss_runtime_checkpoint_coordinator import (
    LossLimitRuntimeCheckpointCoordinator,
)
from backend.money_management.loss_runtime_checkpoint_models import *
from backend.money_management.loss_runtime_integration_models import *
from backend.money_management.loss_runtime_store_models import *
from tests.test_money_management_loss_persistence_contract import state


NOW = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)


def snapshot(revision=1, sequence=1, triggers=(SaveTrigger.INITIAL_STATE_CREATED,)):
    return LossLimitRuntimeSnapshot(
        RuntimeLifecycle.READY,
        state(),
        StateSource.INITIAL_STATE,
        GovernanceProjection.CONTINUE,
        LossLimitRecoveryRequirement(False, (), False, False, False, "not required"),
        triggers,
        revision,
        sequence,
        NOW,
        NOW,
        "TEST",
    )


class Store:
    def __init__(self, value):
        self.value = value

    def get_snapshot(self):
        if self.value is None:
            return LossLimitRuntimeStoreResult(
                StoreResultStatus.FAILED,
                None,
                LossLimitRuntimeStoreFailure(
                    StoreFailureCode.LOSS_RUNTIME_STORE_NOT_INITIALIZED,
                    "not initialized",
                ),
                False,
                False,
            )
        return LossLimitRuntimeStoreResult(
            StoreResultStatus.SUCCEEDED, self.value, None, False, False
        )


class Adapter:
    def __init__(self, result=None, error=False):
        self.result = result or LossPersistenceSaveResult(SaveStatus.SAVED)
        self.error = error
        self.calls = []

    def save(self, value):
        self.calls.append(value)
        if self.error:
            raise RuntimeError("/private/state raw-json-secret digest-secret")
        return self.result


def request(revision=1, sequence=1):
    return LossLimitRuntimeCheckpointRequest(
        SaveTrigger.INITIAL_STATE_CREATED,
        revision,
        sequence,
        NOW,
        CheckpointMode.STARTUP_INITIAL_STATE,
    )


class CheckpointCoordinatorTests(unittest.TestCase):
    def test_initial_checkpoint_saves_once_and_does_not_mutate_snapshot(self):
        current = snapshot()
        before = current.to_dict()
        adapter = Adapter()
        coordinator = LossLimitRuntimeCheckpointCoordinator(adapter, Store(current))
        result = coordinator.checkpoint(request())
        self.assertEqual(result.status, CheckpointStatus.SUCCEEDED)
        self.assertTrue(result.checkpoint_succeeded)
        self.assertFalse(result.durability_pending)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(current.to_dict(), before)

    def test_duplicate_is_idempotent_without_second_save(self):
        adapter = Adapter()
        coordinator = LossLimitRuntimeCheckpointCoordinator(adapter, Store(snapshot()))
        self.assertEqual(coordinator.checkpoint(request()).status, CheckpointStatus.SUCCEEDED)
        self.assertEqual(coordinator.checkpoint(request()).status, CheckpointStatus.IDEMPOTENT)
        self.assertEqual(len(adapter.calls), 1)

    def test_expected_revision_mismatch_never_saves(self):
        adapter = Adapter()
        result = LossLimitRuntimeCheckpointCoordinator(
            adapter, Store(snapshot())
        ).checkpoint(request(revision=2))
        self.assertEqual(result.failure.code, CheckpointFailureCode.LOSS_CHECKPOINT_REVISION_MISMATCH)
        self.assertEqual(adapter.calls, [])

    def test_gap_is_rejected(self):
        adapter = Adapter()
        coordinator = LossLimitRuntimeCheckpointCoordinator(
            adapter,
            Store(snapshot(revision=3, sequence=3)),
            last_saved_revision=1,
            last_saved_sequence=1,
        )
        result = coordinator.checkpoint(request(3, 3))
        self.assertEqual(result.failure.code, CheckpointFailureCode.LOSS_CHECKPOINT_SEQUENCE_GAP)
        self.assertEqual(adapter.calls, [])

    def test_save_failure_preserves_metadata_and_is_pending(self):
        adapter = Adapter(
            LossPersistenceSaveResult(
                SaveStatus.FAILED, SaveFailureCode.WRITE_FAILED, "failed"
            )
        )
        coordinator = LossLimitRuntimeCheckpointCoordinator(adapter, Store(snapshot()))
        result = coordinator.checkpoint(request())
        self.assertEqual(result.status, CheckpointStatus.FAILED)
        self.assertTrue(result.durability_pending)
        self.assertIsNone(coordinator.last_saved_revision)

    def test_exception_message_is_not_exposed(self):
        result = LossLimitRuntimeCheckpointCoordinator(
            Adapter(error=True), Store(snapshot())
        ).checkpoint(request())
        serialized = str(result.to_dict())
        self.assertNotIn("private", serialized)
        self.assertNotIn("secret", serialized)

    def test_manual_and_shutdown_are_explicit(self):
        for trigger, mode in (
            (SaveTrigger.MANUAL_CHECKPOINT, CheckpointMode.MANUAL),
            (SaveTrigger.RUNTIME_SHUTDOWN, CheckpointMode.SHUTDOWN),
        ):
            adapter = Adapter()
            req = LossLimitRuntimeCheckpointRequest(trigger, 1, 1, NOW, mode)
            result = LossLimitRuntimeCheckpointCoordinator(
                adapter, Store(snapshot(triggers=()))
            ).checkpoint(req)
            self.assertEqual(result.status, CheckpointStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
