import unittest
from hashlib import sha256
from pathlib import Path

from backend.money_management.loss_application_composition import (
    build_loss_limit_application_composition,
)
from backend.money_management.loss_application_models import *
from backend.money_management.loss_persistence_adapter import *
from backend.money_management.loss_persistence_serialization import (
    build_canonical_loss_state_json,
)
from tests.test_money_management_loss_persistence_contract import NOW, state


class Persistence:
    def __init__(self, load_result):
        self.load_result = load_result
        self.loads = 0
        self.saves = []

    def load(self):
        self.loads += 1
        return self.load_result

    def save(self, value):
        self.saves.append(value)
        return LossPersistenceSaveResult(SaveStatus.SAVED)


def configuration(**values):
    defaults = dict(
        enabled=True,
        persistence_enabled=True,
        persistence_path=Path("/explicit/money-management"),
        startup_occurred_at=NOW,
        instance_id="test-instance",
    )
    defaults.update(values)
    return LossLimitApplicationConfiguration(**defaults)


class ApplicationCompositionTests(unittest.TestCase):
    def test_default_is_disabled_without_factory_call(self):
        calls = []
        result = build_loss_limit_application_composition(
            persistence_adapter_factory=lambda path: calls.append(path)
        )
        self.assertEqual(result.status, CompositionReadinessStatus.DISABLED)
        self.assertIsNone(result.lifecycle_adapter)
        self.assertEqual(calls, [])

    def test_valid_composition_uses_one_store_and_coordinator_graph(self):
        persistence = Persistence(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        result = build_loss_limit_application_composition(
            configuration(), persistence_adapter_factory=lambda path: persistence
        )
        self.assertEqual(result.status, CompositionReadinessStatus.READY)
        lifecycle = result.lifecycle_adapter
        runtime = lifecycle._runtime_coordinator
        self.assertIs(lifecycle._runtime_store, runtime._store)
        self.assertIs(runtime._startup._store, runtime._store)
        self.assertIs(runtime._checkpoint._store, runtime._store)
        self.assertIs(runtime._checkpoint, runtime._checkpoint)
        self.assertEqual(persistence.loads, 1)

    def test_invalid_configuration_returns_no_partial_graph(self):
        result = build_loss_limit_application_composition(
            LossLimitApplicationConfiguration(enabled=True)
        )
        self.assertEqual(
            result.status, CompositionReadinessStatus.CONFIGURATION_INVALID
        )
        self.assertIsNone(result.lifecycle_adapter)
        self.assertFalse(result.readiness.startup_allowed)

    def test_missing_persistence_bootstraps_zero_metadata(self):
        persistence = Persistence(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        result = build_loss_limit_application_composition(
            configuration(), persistence_adapter_factory=lambda path: persistence
        )
        checkpoint = result.lifecycle_adapter._runtime_coordinator._checkpoint
        self.assertIsNone(checkpoint.last_saved_revision)
        self.assertIsNone(checkpoint.last_saved_sequence)

    def test_valid_persisted_metadata_is_injected_into_store_and_checkpoint(self):
        persisted = state()
        fingerprint = sha256(build_canonical_loss_state_json(persisted)).hexdigest()
        metadata = LossLimitCheckpointMetadata(7, 9, fingerprint)
        persistence = Persistence(
            LossPersistenceLoadResult(LoadStatus.VALID, persisted)
        )
        result = build_loss_limit_application_composition(
            configuration(checkpoint_metadata=metadata),
            persistence_adapter_factory=lambda path: persistence,
        )
        lifecycle = result.lifecycle_adapter
        from backend.money_management.loss_runtime_startup_models import (
            LossLimitRuntimeStartupRequest,
        )
        from backend.money_management.loss_runtime_integration_models import (
            RecoveryStatus,
            StartupMode,
        )

        lifecycle.startup(
            LossLimitRuntimeStartupRequest(
                None, StartupMode.STARTUP, RecoveryStatus.NOT_REQUIRED, NOW, NOW
            )
        )
        snapshot = lifecycle.get_snapshot()
        checkpoint = lifecycle._runtime_coordinator._checkpoint
        self.assertEqual((snapshot.revision, snapshot.sequence), (7, 9))
        self.assertEqual(
            (checkpoint.last_saved_revision, checkpoint.last_saved_sequence), (7, 9)
        )
        self.assertEqual(persistence.saves, [])

    def test_metadata_mismatch_requires_recovery_without_save(self):
        persisted = state()
        metadata = LossLimitCheckpointMetadata(2, 2, "0" * 64)
        persistence = Persistence(
            LossPersistenceLoadResult(LoadStatus.VALID, persisted)
        )
        result = build_loss_limit_application_composition(
            configuration(checkpoint_metadata=metadata),
            persistence_adapter_factory=lambda path: persistence,
        )
        self.assertEqual(
            result.status, CompositionReadinessStatus.RECOVERY_REQUIRED
        )
        self.assertIsNone(result.lifecycle_adapter)
        self.assertEqual(persistence.saves, [])

    def test_multiple_compositions_are_isolated(self):
        first = Persistence(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        second = Persistence(
            LossPersistenceLoadResult(LoadStatus.MISSING, None, "MISSING", "missing")
        )
        one = build_loss_limit_application_composition(
            configuration(instance_id="one"),
            persistence_adapter_factory=lambda path: first,
        )
        two = build_loss_limit_application_composition(
            configuration(instance_id="two"),
            persistence_adapter_factory=lambda path: second,
        )
        self.assertIsNot(
            one.lifecycle_adapter._runtime_store,
            two.lifecycle_adapter._runtime_store,
        )
        self.assertIsNot(
            one.lifecycle_adapter._runtime_coordinator,
            two.lifecycle_adapter._runtime_coordinator,
        )

    def test_factory_exception_is_secret_safe(self):
        def factory(path):
            raise RuntimeError(
                "/home/private/money.json raw-payload-secret digest-secret"
            )

        result = build_loss_limit_application_composition(
            configuration(), persistence_adapter_factory=factory
        )
        serialized = str(result.to_dict())
        self.assertEqual(
            result.status, CompositionReadinessStatus.PERSISTENCE_UNAVAILABLE
        )
        self.assertNotIn("private", serialized)
        self.assertNotIn("secret", serialized)

    def test_configuration_and_metadata_repr_hide_path_and_fingerprint(self):
        metadata = LossLimitCheckpointMetadata(1, 1, "a" * 64)
        configured = configuration(checkpoint_metadata=metadata)
        rendered = repr(configured) + repr(metadata)
        self.assertNotIn("explicit/money-management", rendered)
        self.assertNotIn("a" * 64, rendered)


if __name__ == "__main__":
    unittest.main()
