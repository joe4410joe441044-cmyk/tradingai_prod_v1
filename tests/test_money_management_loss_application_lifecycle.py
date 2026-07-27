import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from backend.money_management.loss_application_composition import (
    build_loss_limit_application_composition,
)
from backend.money_management.loss_application_models import *
from backend.money_management.loss_persistence_adapter import *
from backend.money_management.loss_runtime_checkpoint_models import *
from backend.money_management.loss_runtime_coordination_models import (
    LossLimitRuntimeStopRequest,
)
from backend.money_management.loss_runtime_integration_models import *
from backend.money_management.loss_runtime_startup_models import (
    LossLimitRuntimeStartupRequest,
)
from tests.test_money_management_loss_application_composition import (
    Persistence,
    configuration,
)
from tests.test_money_management_loss_persistence_contract import NOW, state
from tests.test_money_management_loss_runtime_store import update


def lifecycle(initial_state_missing=True, fail_save=False):
    load_result = (
        LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        if initial_state_missing
        else LossPersistenceLoadResult(LoadStatus.VALID, state())
    )
    persistence = Persistence(load_result)
    if fail_save:
        def failed(value):
            persistence.saves.append(value)
            return LossPersistenceSaveResult(
                SaveStatus.FAILED, SaveFailureCode.WRITE_FAILED, "failed"
            )
        persistence.save = failed
    result = build_loss_limit_application_composition(
        configuration(), persistence_adapter_factory=lambda path: persistence
    )
    return result.lifecycle_adapter, persistence


def startup_request(initial=None):
    return LossLimitRuntimeStartupRequest(
        initial, StartupMode.STARTUP, RecoveryStatus.NOT_REQUIRED, NOW, NOW
    )


class ApplicationLifecycleTests(unittest.TestCase):
    def test_startup_running_and_duplicate_does_not_call_child_twice(self):
        adapter, persistence = lifecycle()
        first = adapter.startup(startup_request(state()))
        second = adapter.startup(startup_request(state()))
        self.assertEqual(first.lifecycle_state, ApplicationLifecycleState.RUNNING)
        self.assertEqual(second.status, LifecycleOperationStatus.IDEMPOTENT)
        self.assertEqual(persistence.loads, 1)
        self.assertEqual(len(persistence.saves), 1)

    def test_update_before_startup_is_rejected_without_snapshot(self):
        adapter, persistence = lifecycle()
        result = adapter.apply_update(update())
        self.assertEqual(result.status, LifecycleOperationStatus.REJECTED)
        self.assertIsNone(adapter.get_snapshot())
        self.assertEqual(persistence.saves, [])

    def test_valid_update_and_durability_pending_keep_running(self):
        adapter, persistence = lifecycle(initial_state_missing=False, fail_save=True)
        adapter.startup(startup_request())
        result = adapter.apply_update(update())
        status = adapter.get_status()
        self.assertEqual(result.status, LifecycleOperationStatus.PARTIAL)
        self.assertEqual(status.lifecycle_state, ApplicationLifecycleState.RUNNING)
        self.assertTrue(status.durability_pending)
        self.assertEqual(status.revision, 2)

    def test_startup_without_initial_state_enters_recovery(self):
        adapter, _ = lifecycle()
        result = adapter.startup(startup_request())
        self.assertEqual(
            result.lifecycle_state, ApplicationLifecycleState.RECOVERY_REQUIRED
        )
        self.assertFalse(adapter.get_status().new_entry_allowed)
        self.assertEqual(
            adapter.apply_update(update()).status, LifecycleOperationStatus.REJECTED
        )

    def test_manual_checkpoint_state_boundary(self):
        adapter, persistence = lifecycle(initial_state_missing=False)
        request = LossLimitRuntimeCheckpointRequest(
            SaveTrigger.MANUAL_CHECKPOINT, 1, 1, NOW, CheckpointMode.MANUAL
        )
        self.assertEqual(
            adapter.manual_checkpoint(request).status,
            LifecycleOperationStatus.REJECTED,
        )
        adapter.startup(startup_request())
        before = adapter.get_snapshot().to_dict()
        self.assertEqual(
            adapter.manual_checkpoint(request).status,
            LifecycleOperationStatus.SUCCEEDED,
        )
        self.assertEqual(adapter.get_snapshot().to_dict(), before)
        self.assertEqual(len(persistence.saves), 0)

    def test_shutdown_running_and_duplicate(self):
        adapter, persistence = lifecycle(initial_state_missing=False)
        adapter.startup(startup_request())
        first = adapter.shutdown(
            LossLimitRuntimeStopRequest(1, 1, NOW + timedelta(seconds=1), NOW)
        )
        second = adapter.shutdown(
            LossLimitRuntimeStopRequest(2, 2, NOW + timedelta(seconds=2), NOW)
        )
        self.assertEqual(first.lifecycle_state, ApplicationLifecycleState.STOPPED)
        self.assertEqual(second.status, LifecycleOperationStatus.IDEMPOTENT)
        self.assertEqual(len(persistence.saves), 1)
        self.assertFalse(adapter.get_status().runtime_available)
        self.assertEqual(
            adapter.apply_update(update(rev=2, seq=3)).status,
            LifecycleOperationStatus.REJECTED,
        )

    def test_shutdown_save_failure_still_stops(self):
        adapter, _ = lifecycle(initial_state_missing=False, fail_save=True)
        adapter.startup(startup_request())
        result = adapter.shutdown(
            LossLimitRuntimeStopRequest(1, 1, NOW + timedelta(seconds=1), NOW)
        )
        self.assertEqual(result.lifecycle_state, ApplicationLifecycleState.STOPPED)
        self.assertEqual(result.status, LifecycleOperationStatus.PARTIAL)
        self.assertTrue(adapter.get_status().durability_pending)

    def test_shutdown_before_startup_is_safe_and_does_not_save(self):
        adapter, persistence = lifecycle()
        result = adapter.shutdown(LossLimitRuntimeStopRequest(1, 1, NOW, NOW))
        self.assertEqual(result.lifecycle_state, ApplicationLifecycleState.STOPPED)
        self.assertEqual(persistence.saves, [])

    def test_concurrent_startup_invokes_runtime_once(self):
        adapter, persistence = lifecycle()
        request = startup_request(state())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: adapter.startup(request), range(4)))
        self.assertEqual(len(persistence.saves), 1)
        self.assertEqual(
            sum(item.status is LifecycleOperationStatus.SUCCEEDED for item in results),
            1,
        )

    def test_status_is_minimal_and_secret_free(self):
        adapter, _ = lifecycle(initial_state_missing=False)
        adapter.startup(startup_request())
        serialized = str(adapter.get_status().to_dict())
        self.assertNotIn("account_scope", serialized)
        self.assertNotIn("persistence_path", serialized)
        self.assertNotIn("fingerprint", serialized)
        self.assertNotIn("digest", serialized)


if __name__ == "__main__":
    unittest.main()
