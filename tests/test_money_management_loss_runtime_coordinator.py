import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from backend.money_management.loss_persistence_adapter import *
from backend.money_management.loss_runtime_checkpoint_coordinator import (
    LossLimitRuntimeCheckpointCoordinator,
)
from backend.money_management.loss_runtime_checkpoint_models import *
from backend.money_management.loss_runtime_checkpoint_policy import (
    build_loss_limit_checkpoint_policy_decision,
)
from backend.money_management.loss_runtime_coordination_models import *
from backend.money_management.loss_runtime_coordinator import LossLimitRuntimeCoordinator
from backend.money_management.loss_runtime_integration_models import *
from backend.money_management.loss_runtime_startup_coordinator import (
    LossLimitRuntimeStartupCoordinator,
)
from backend.money_management.loss_runtime_startup_models import *
from backend.money_management.loss_runtime_store import LossLimitRuntimeStateStore
from tests.test_money_management_loss_persistence_contract import NOW, state
from tests.test_money_management_loss_runtime_store import update


class Persistence:
    def __init__(self, load_result, fail_save=False):
        self.load_result = load_result
        self.fail_save = fail_save
        self.loads = 0
        self.saves = []

    def load(self):
        self.loads += 1
        return self.load_result

    def save(self, value):
        self.saves.append(value)
        if self.fail_save:
            return LossPersistenceSaveResult(
                SaveStatus.FAILED, SaveFailureCode.WRITE_FAILED, "failed"
            )
        return LossPersistenceSaveResult(SaveStatus.SAVED)


def system(load_result, fail_save=False):
    persistence = Persistence(load_result, fail_save)
    store = LossLimitRuntimeStateStore()
    startup = LossLimitRuntimeStartupCoordinator(persistence, store)
    checkpoint = LossLimitRuntimeCheckpointCoordinator(persistence, store)
    return LossLimitRuntimeCoordinator(startup, store, checkpoint), persistence, store


def startup_request(initial=None):
    return LossLimitRuntimeStartupRequest(
        initial, StartupMode.STARTUP, RecoveryStatus.NOT_REQUIRED, NOW, NOW
    )


class RuntimeCoordinatorTests(unittest.TestCase):
    def test_persisted_startup_does_not_checkpoint(self):
        coordinator, persistence, _ = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        result = coordinator.startup(startup_request())
        self.assertEqual(result.status, RuntimeCoordinationStatus.SUCCEEDED)
        self.assertTrue(result.runtime_succeeded)
        self.assertFalse(result.checkpoint_attempted)
        self.assertFalse(result.durability_pending)
        self.assertEqual(persistence.saves, [])

    def test_initial_startup_checkpoints_once(self):
        coordinator, persistence, _ = system(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        result = coordinator.startup(startup_request(state()))
        self.assertEqual(result.status, RuntimeCoordinationStatus.SUCCEEDED)
        self.assertTrue(result.checkpoint_succeeded)
        self.assertEqual(len(persistence.saves), 1)
        self.assertEqual(result.snapshot.revision, 1)

    def test_initial_save_failure_is_partial_without_rollback_and_can_retry(self):
        coordinator, persistence, store = system(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing"),
            True,
        )
        first = coordinator.startup(startup_request(state()))
        saved_snapshot = store.get_snapshot().snapshot
        self.assertEqual(first.status, RuntimeCoordinationStatus.PARTIAL)
        self.assertTrue(first.runtime_succeeded)
        self.assertTrue(first.durability_pending)
        self.assertEqual(first.snapshot.to_dict(), saved_snapshot.to_dict())
        persistence.fail_save = False
        second = coordinator.startup(startup_request(state()))
        self.assertEqual(second.status, RuntimeCoordinationStatus.IDEMPOTENT)
        self.assertTrue(second.checkpoint_succeeded)
        self.assertEqual(len(persistence.saves), 2)

    def test_corrupt_startup_never_saves(self):
        coordinator, persistence, _ = system(
            LossPersistenceLoadResult(LoadStatus.CORRUPT, None, "CORRUPT", "bad")
        )
        result = coordinator.startup(startup_request(state()))
        self.assertEqual(result.status, RuntimeCoordinationStatus.RECOVERY_REQUIRED)
        self.assertTrue(result.recovery_required)
        self.assertFalse(result.checkpoint_attempted)
        self.assertEqual(persistence.saves, [])

    def test_runtime_update_then_duplicate_does_not_double_save(self):
        coordinator, persistence, _ = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        coordinator.startup(startup_request())
        first = coordinator.apply_update(update())
        second = coordinator.apply_update(update(rev=2, seq=2))
        self.assertEqual(first.status, RuntimeCoordinationStatus.SUCCEEDED)
        self.assertEqual(second.status, RuntimeCoordinationStatus.IDEMPOTENT)
        self.assertEqual(len(persistence.saves), 1)

    def test_update_save_failure_keeps_new_runtime_snapshot(self):
        coordinator, persistence, store = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state()), True
        )
        coordinator.startup(startup_request())
        result = coordinator.apply_update(update())
        self.assertEqual(result.status, RuntimeCoordinationStatus.PARTIAL)
        self.assertEqual(result.snapshot.revision, 2)
        self.assertEqual(store.get_snapshot().snapshot.revision, 2)
        self.assertTrue(result.durability_pending)

    def test_update_failure_never_checkpoints(self):
        coordinator, persistence, store = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        coordinator.startup(startup_request())
        before = store.get_snapshot().snapshot.to_dict()
        result = coordinator.apply_update(update(rev=9))
        self.assertEqual(result.status, RuntimeCoordinationStatus.FAILED)
        self.assertEqual(persistence.saves, [])
        self.assertEqual(store.get_snapshot().snapshot.to_dict(), before)

    def test_stop_checkpoints_stopped_snapshot_and_duplicate_is_idempotent(self):
        coordinator, persistence, store = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        coordinator.startup(startup_request())
        first = coordinator.stop(
            LossLimitRuntimeStopRequest(1, 1, NOW + timedelta(seconds=1), NOW)
        )
        second = coordinator.stop(
            LossLimitRuntimeStopRequest(2, 2, NOW + timedelta(seconds=2), NOW)
        )
        self.assertEqual(first.snapshot.lifecycle, RuntimeLifecycle.STOPPED)
        self.assertEqual(first.status, RuntimeCoordinationStatus.SUCCEEDED)
        self.assertEqual(second.status, RuntimeCoordinationStatus.IDEMPOTENT)
        self.assertEqual(store.get_snapshot().snapshot.lifecycle, RuntimeLifecycle.STOPPED)
        self.assertEqual(len(persistence.saves), 1)

    def test_manual_checkpoint_does_not_mutate_store(self):
        coordinator, persistence, store = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        coordinator.startup(startup_request())
        before = store.get_snapshot().snapshot.to_dict()
        request = LossLimitRuntimeCheckpointRequest(
            SaveTrigger.MANUAL_CHECKPOINT, 1, 1, NOW, CheckpointMode.MANUAL
        )
        result = coordinator.checkpoint(request)
        self.assertEqual(result.status, RuntimeCoordinationStatus.SUCCEEDED)
        self.assertEqual(store.get_snapshot().snapshot.to_dict(), before)
        self.assertEqual(len(persistence.saves), 1)

    def test_manual_checkpoint_preserves_request_revision_validation(self):
        coordinator, persistence, _ = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        coordinator.startup(startup_request())
        request = LossLimitRuntimeCheckpointRequest(
            SaveTrigger.MANUAL_CHECKPOINT, 9, 1, NOW, CheckpointMode.MANUAL
        )
        result = coordinator.checkpoint(request)
        self.assertEqual(result.status, RuntimeCoordinationStatus.PARTIAL)
        self.assertTrue(result.runtime_succeeded)
        self.assertTrue(result.durability_pending)
        self.assertEqual(persistence.saves, [])

    def test_checkpoint_exception_is_safe_partial_success(self):
        coordinator, _, store = system(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )

        class RaisingCheckpoint:
            def checkpoint(self, request):
                raise RuntimeError("/home/private raw-json-secret digest-secret")

        coordinator._checkpoint = RaisingCheckpoint()
        result = coordinator.startup(startup_request(state()))
        self.assertEqual(result.status, RuntimeCoordinationStatus.PARTIAL)
        self.assertTrue(result.runtime_succeeded)
        self.assertIsNotNone(store.get_snapshot().snapshot)
        serialized = str(result.to_dict())
        self.assertNotIn("private", serialized)
        self.assertNotIn("secret", serialized)

    def test_concurrent_startup_serializes_and_saves_once(self):
        coordinator, persistence, _ = system(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        request = startup_request(state())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: coordinator.startup(request), range(4)))
        self.assertEqual(len(persistence.saves), 1)
        self.assertEqual(
            sum(item.status is RuntimeCoordinationStatus.SUCCEEDED for item in results),
            1,
        )
        self.assertTrue(
            all(
                item.status
                in (
                    RuntimeCoordinationStatus.SUCCEEDED,
                    RuntimeCoordinationStatus.IDEMPOTENT,
                )
                for item in results
            )
        )

    def test_policy_priority_is_deterministic(self):
        store = LossLimitRuntimeStateStore()
        persistence = Persistence(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        startup = LossLimitRuntimeStartupCoordinator(persistence, store)
        startup.start(startup_request(state()))
        original = store.get_snapshot().snapshot
        snapshot = LossLimitRuntimeSnapshot(
            original.lifecycle,
            original.state,
            original.state_source,
            original.governance_projection,
            original.recovery_requirement,
            (
                SaveTrigger.METRIC_CHANGED,
                SaveTrigger.STATE_TRANSITION,
                SaveTrigger.PERIOD_ROLLOVER,
            ),
            original.revision,
            original.sequence,
            original.initialized_at,
            original.updated_at,
            original.last_transition,
        )
        decision = build_loss_limit_checkpoint_policy_decision(
            RuntimeOperationType.UPDATE,
            "SUCCEEDED",
            snapshot,
            True,
            snapshot.save_triggers,
        )
        self.assertEqual(decision.trigger, SaveTrigger.PERIOD_ROLLOVER)
        self.assertTrue(decision.mandatory)

    def test_invalid_request_is_safe(self):
        coordinator, _, _ = system(
            LossPersistenceLoadResult(LoadStatus.VALID, state())
        )
        result = coordinator.apply_update(object())
        self.assertEqual(result.status, RuntimeCoordinationStatus.FAILED)
        self.assertEqual(
            result.failure.code,
            RuntimeCoordinationFailureCode.LOSS_RUNTIME_COORDINATION_REQUEST_INVALID,
        )
        self.assertNotIn("object at", str(result.to_dict()))


if __name__ == "__main__":
    unittest.main()
