"""MM-4F explicit composition root; importing this module has no side effects."""
from pathlib import Path

from .loss_application_lifecycle import LossLimitApplicationLifecycleAdapter
from .loss_application_models import (
    ApplicationFailureCode,
    CompositionReadinessStatus,
    LossLimitApplicationCompositionResult,
    LossLimitApplicationConfiguration,
    LossLimitApplicationFailure,
    LossLimitCompositionReadiness,
)
from .loss_checkpoint_metadata_bootstrap import (
    CheckpointMetadataBootstrapStatus,
    bootstrap_loss_limit_checkpoint_metadata,
)
from .cash_flow_transaction import CashFlowTransactionCoordinator
from .loss_persistence_adapter import load_loss_state, save_loss_state
from .loss_runtime_checkpoint_coordinator import (
    LossLimitRuntimeCheckpointCoordinator,
)
from .loss_runtime_coordinator import LossLimitRuntimeCoordinator
from .loss_runtime_startup_coordinator import LossLimitRuntimeStartupCoordinator
from .loss_runtime_store import LossLimitRuntimeStateStore


class LossLimitFilesystemPersistenceAdapter:
    def __init__(self, base_directory):
        if not isinstance(base_directory, Path) or not base_directory.is_absolute():
            raise ValueError("absolute persistence directory required")
        self._base_directory = base_directory

    def load(self):
        return load_loss_state(self._base_directory)

    def save(self, state):
        return save_loss_state(state, self._base_directory)


class _BootstrapCachingPersistenceAdapter:
    def __init__(self, delegate, load_result):
        self._delegate = delegate
        self._load_result = load_result

    def load(self):
        return self._load_result

    def save(self, state):
        return self._delegate.save(state)


def _readiness(status, enabled, available, startup, update, shutdown, recovery, reasons=()):
    return LossLimitCompositionReadiness(
        status, enabled, available, startup, update, shutdown, recovery, reasons
    )


def _failed(status, code, message, recovery=False):
    readiness = _readiness(
        status,
        True,
        False,
        False,
        False,
        False,
        recovery,
        (message,),
    )
    return LossLimitApplicationCompositionResult(
        status,
        readiness,
        None,
        LossLimitApplicationFailure(code, message),
    )


def build_loss_limit_application_composition(
    configuration=LossLimitApplicationConfiguration(),
    persistence_adapter_factory=LossLimitFilesystemPersistenceAdapter,
    runtime_store_factory=LossLimitRuntimeStateStore,
    startup_coordinator_factory=LossLimitRuntimeStartupCoordinator,
    checkpoint_coordinator_factory=LossLimitRuntimeCheckpointCoordinator,
    runtime_coordinator_factory=LossLimitRuntimeCoordinator,
    lifecycle_adapter_factory=LossLimitApplicationLifecycleAdapter,
    cash_flow_transaction_factory=CashFlowTransactionCoordinator,
):
    if not isinstance(configuration, LossLimitApplicationConfiguration):
        return _failed(
            CompositionReadinessStatus.CONFIGURATION_INVALID,
            ApplicationFailureCode.LOSS_APPLICATION_CONFIGURATION_INVALID,
            "application configuration invalid",
        )
    if not configuration.enabled:
        readiness = _readiness(
            CompositionReadinessStatus.DISABLED,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        return LossLimitApplicationCompositionResult(
            CompositionReadinessStatus.DISABLED, readiness, None, None
        )
    if (
        not configuration.persistence_enabled
        or configuration.persistence_path is None
    ):
        return _failed(
            CompositionReadinessStatus.CONFIGURATION_INVALID,
            ApplicationFailureCode.LOSS_APPLICATION_CONFIGURATION_INVALID,
            "persistence configuration invalid",
        )
    try:
        persistence = persistence_adapter_factory(configuration.persistence_path)
        cash_flow_transactions = None
        # Custom in-memory persistence adapters used by tests/compositions do
        # not imply a filesystem cash-flow authority. Production's configured
        # runtime directory does, and recovery must precede MM bootstrap.
        if configuration.persistence_path.is_dir():
            cash_flow_transactions = cash_flow_transaction_factory(
                configuration.persistence_path
            )
            cash_flow_transactions.recover()
    except Exception:
        return _failed(
            CompositionReadinessStatus.PERSISTENCE_UNAVAILABLE,
            ApplicationFailureCode.LOSS_APPLICATION_PERSISTENCE_UNAVAILABLE,
            "persistence unavailable",
        )
    try:
        bootstrap = bootstrap_loss_limit_checkpoint_metadata(
            persistence, configuration.checkpoint_metadata
        )
    except Exception:
        return _failed(
            CompositionReadinessStatus.RECOVERY_REQUIRED,
            ApplicationFailureCode.LOSS_APPLICATION_METADATA_INVALID,
            "checkpoint metadata invalid",
            True,
        )
    if bootstrap.status is CheckpointMetadataBootstrapStatus.PERSISTENCE_UNAVAILABLE:
        return _failed(
            CompositionReadinessStatus.PERSISTENCE_UNAVAILABLE,
            ApplicationFailureCode.LOSS_APPLICATION_PERSISTENCE_UNAVAILABLE,
            "persistence unavailable",
        )
    if bootstrap.status is CheckpointMetadataBootstrapStatus.RECOVERY_REQUIRED:
        return _failed(
            CompositionReadinessStatus.RECOVERY_REQUIRED,
            ApplicationFailureCode.LOSS_APPLICATION_METADATA_INVALID,
            "checkpoint metadata requires recovery",
            True,
        )
    metadata = bootstrap.metadata
    if metadata is None or bootstrap.load_result is None:
        return _failed(
            CompositionReadinessStatus.COMPOSITION_FAILED,
            ApplicationFailureCode.LOSS_APPLICATION_COMPOSITION_FAILED,
            "composition failed",
        )
    initial_revision = metadata.last_persisted_revision or 1
    initial_sequence = metadata.last_persisted_sequence or 1
    last_revision = metadata.last_persisted_revision or None
    last_sequence = metadata.last_persisted_sequence or None
    cached_persistence = _BootstrapCachingPersistenceAdapter(
        persistence, bootstrap.load_result
    )
    try:
        store = runtime_store_factory()
        startup = startup_coordinator_factory(
            cached_persistence, store, initial_revision, initial_sequence
        )
        checkpoint = checkpoint_coordinator_factory(
            cached_persistence,
            store,
            last_revision,
            last_sequence,
            bootstrap.canonical_state,
        )
        runtime = runtime_coordinator_factory(startup, store, checkpoint)
        readiness = _readiness(
            CompositionReadinessStatus.READY,
            True,
            True,
            True,
            False,
            True,
            False,
        )
        lifecycle = lifecycle_adapter_factory(runtime, store, readiness)
        lifecycle.cash_flow_transaction_coordinator = cash_flow_transactions
    except Exception:
        return _failed(
            CompositionReadinessStatus.COMPOSITION_FAILED,
            ApplicationFailureCode.LOSS_APPLICATION_COMPOSITION_FAILED,
            "composition failed",
        )
    return LossLimitApplicationCompositionResult(
        CompositionReadinessStatus.READY, readiness, lifecycle, None
    )
