"""MM-4G FastAPI registration helpers with safe application-state projection."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .loss_application_composition import (
    build_loss_limit_application_composition,
)
from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LifecycleOperationStatus,
    LossLimitApplicationConfiguration,
    LossLimitApplicationCompositionResult,
    LossLimitApplicationStatus,
)
from .loss_application_settings import (
    LossLimitApplicationSettingsError,
    resolve_loss_limit_application_configuration,
)
from .loss_runtime_coordination_models import LossLimitRuntimeStopRequest
from .loss_runtime_integration_models import RecoveryStatus, StartupMode
from .loss_runtime_startup_models import LossLimitRuntimeStartupRequest


@dataclass(frozen=True)
class MoneyManagementSafeApplicationStatus:
    enabled: bool
    composition_status: CompositionReadinessStatus
    lifecycle_state: Optional[ApplicationLifecycleState]
    runtime_available: bool
    runtime_state: Optional[str]
    new_entry_allowed: bool
    recovery_required: bool
    durability_pending: bool
    revision: Optional[int]
    sequence: Optional[int]
    last_operation_status: Optional[str]

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "compositionStatus": self.composition_status.value,
            "lifecycleState": self.lifecycle_state.value
            if self.lifecycle_state
            else None,
            "runtimeAvailable": self.runtime_available,
            "runtimeState": self.runtime_state,
            "newEntryAllowed": self.new_entry_allowed,
            "recoveryRequired": self.recovery_required,
            "durabilityPending": self.durability_pending,
            "revision": self.revision,
            "sequence": self.sequence,
            "lastOperationStatus": self.last_operation_status,
        }


@dataclass(frozen=True)
class MoneyManagementApplicationRegistration:
    composition_status: CompositionReadinessStatus
    lifecycle_adapter: Optional[object] = field(repr=False)
    startup_status: Optional[LifecycleOperationStatus]
    shutdown_status: Optional[LifecycleOperationStatus]
    safe_status: MoneyManagementSafeApplicationStatus

    def __post_init__(self):
        object.__setattr__(
            self, "composition_status", CompositionReadinessStatus(self.composition_status)
        )
        if self.startup_status is not None:
            object.__setattr__(
                self, "startup_status", LifecycleOperationStatus(self.startup_status)
            )
        if self.shutdown_status is not None:
            object.__setattr__(
                self, "shutdown_status", LifecycleOperationStatus(self.shutdown_status)
            )
        if not isinstance(self.safe_status, MoneyManagementSafeApplicationStatus):
            raise TypeError("safe status required")

    def to_dict(self):
        return {
            "compositionStatus": self.composition_status.value,
            "lifecycleAdapterAvailable": self.lifecycle_adapter is not None,
            "startupStatus": self.startup_status.value if self.startup_status else None,
            "shutdownStatus": self.shutdown_status.value if self.shutdown_status else None,
            "safeStatus": self.safe_status.to_dict(),
        }


def _disabled_status(status=CompositionReadinessStatus.DISABLED, recovery=False):
    return MoneyManagementSafeApplicationStatus(
        status is not CompositionReadinessStatus.DISABLED,
        status,
        None,
        False,
        None,
        False,
        recovery,
        False,
        None,
        None,
        None,
    )


def _project_status(enabled, composition_status, status):
    if not isinstance(status, LossLimitApplicationStatus):
        return MoneyManagementSafeApplicationStatus(
            enabled,
            composition_status,
            ApplicationLifecycleState.FAILED,
            False,
            None,
            False,
            True,
            False,
            None,
            None,
            LifecycleOperationStatus.FAILED.value,
        )
    running = status.lifecycle_state is ApplicationLifecycleState.RUNNING
    runtime_available = bool(running and status.runtime_available)
    return MoneyManagementSafeApplicationStatus(
        enabled,
        composition_status,
        status.lifecycle_state,
        runtime_available,
        status.runtime_state.value if status.runtime_state else None,
        status.new_entry_allowed if runtime_available else False,
        status.recovery_required,
        status.durability_pending,
        status.revision,
        status.sequence,
        status.last_operation_status,
    )


def _safe_log(logger, level, event):
    if logger is None:
        return
    log_method = getattr(logger, level, None)
    if callable(log_method):
        log_method("Money Management lifecycle: %s", event)


def startup_money_management_application(
    app,
    configuration=None,
    configuration_resolver=resolve_loss_limit_application_configuration,
    composition_factory=build_loss_limit_application_composition,
    timestamp_source=None,
    logger=None,
):
    existing = getattr(app.state, "money_management", None)
    if (
        isinstance(existing, MoneyManagementApplicationRegistration)
        and existing.startup_status is not None
        and existing.shutdown_status is None
    ):
        return existing
    try:
        resolved = configuration or configuration_resolver()
        if not isinstance(resolved, LossLimitApplicationConfiguration):
            raise LossLimitApplicationSettingsError("configuration invalid")
    except Exception:
        registration = MoneyManagementApplicationRegistration(
            CompositionReadinessStatus.CONFIGURATION_INVALID,
            None,
            LifecycleOperationStatus.FAILED,
            None,
            _disabled_status(CompositionReadinessStatus.CONFIGURATION_INVALID, True),
        )
        app.state.money_management = registration
        _safe_log(logger, "warning", "Startup Failed")
        return registration
    try:
        composition = composition_factory(resolved)
        if not isinstance(composition, LossLimitApplicationCompositionResult):
            raise TypeError("composition result invalid")
    except Exception:
        registration = MoneyManagementApplicationRegistration(
            CompositionReadinessStatus.COMPOSITION_FAILED,
            None,
            LifecycleOperationStatus.FAILED,
            None,
            _disabled_status(CompositionReadinessStatus.COMPOSITION_FAILED, True),
        )
        app.state.money_management = registration
        _safe_log(logger, "warning", "Startup Failed")
        return registration
    if composition.status is not CompositionReadinessStatus.READY:
        recovery = composition.status is CompositionReadinessStatus.RECOVERY_REQUIRED
        startup_status = (
            None
            if composition.status is CompositionReadinessStatus.DISABLED
            else LifecycleOperationStatus.RECOVERY_REQUIRED
            if recovery
            else LifecycleOperationStatus.FAILED
        )
        registration = MoneyManagementApplicationRegistration(
            composition.status,
            None,
            startup_status,
            None,
            _disabled_status(composition.status, recovery),
        )
        app.state.money_management = registration
        event = (
            "Disabled"
            if composition.status is CompositionReadinessStatus.DISABLED
            else "Startup Recovery Required"
            if recovery
            else "Startup Failed"
        )
        _safe_log(logger, "debug" if startup_status is None else "warning", event)
        return registration
    adapter = composition.lifecycle_adapter
    try:
        now = (
            timestamp_source()
            if timestamp_source is not None
            else datetime.now(timezone.utc)
        )
        request = LossLimitRuntimeStartupRequest(
            resolved.initial_state,
            StartupMode.STARTUP,
            RecoveryStatus.NOT_REQUIRED,
            now,
            now,
        )
        startup_result = adapter.startup(request)
        safe_status = _project_status(True, composition.status, adapter.get_status())
        startup_status = LifecycleOperationStatus(startup_result.status)
    except Exception:
        registration = MoneyManagementApplicationRegistration(
            composition.status,
            adapter,
            LifecycleOperationStatus.FAILED,
            None,
            MoneyManagementSafeApplicationStatus(
                True,
                composition.status,
                ApplicationLifecycleState.FAILED,
                False,
                None,
                False,
                True,
                False,
                None,
                None,
                LifecycleOperationStatus.FAILED.value,
            ),
        )
        app.state.money_management = registration
        _safe_log(logger, "warning", "Startup Failed")
        return registration
    registration = MoneyManagementApplicationRegistration(
        composition.status, adapter, startup_status, None, safe_status
    )
    app.state.money_management = registration
    event = (
        "Startup Recovery Required"
        if safe_status.recovery_required
        else "Startup Running"
    )
    _safe_log(logger, "debug", event)
    return registration


def shutdown_money_management_application(app, timestamp_source=None, logger=None):
    existing = getattr(app.state, "money_management", None)
    if not isinstance(existing, MoneyManagementApplicationRegistration):
        return None
    if existing.shutdown_status is not None:
        return existing
    adapter = existing.lifecycle_adapter
    if adapter is None:
        registration = MoneyManagementApplicationRegistration(
            existing.composition_status,
            None,
            existing.startup_status,
            LifecycleOperationStatus.IDEMPOTENT,
            existing.safe_status,
        )
        app.state.money_management = registration
        return registration
    try:
        status = adapter.get_status()
        revision = status.revision or 1
        sequence = status.sequence or 1
        now = (
            timestamp_source()
            if timestamp_source is not None
            else datetime.now(timezone.utc)
        )
        shutdown_result = adapter.shutdown(
            LossLimitRuntimeStopRequest(revision, sequence, now, now)
        )
        safe_status = _project_status(
            True, existing.composition_status, adapter.get_status()
        )
        shutdown_status = LifecycleOperationStatus(shutdown_result.status)
    except Exception:
        safe_status = MoneyManagementSafeApplicationStatus(
            True,
            existing.composition_status,
            ApplicationLifecycleState.FAILED,
            False,
            None,
            False,
            True,
            True,
            existing.safe_status.revision,
            existing.safe_status.sequence,
            LifecycleOperationStatus.FAILED.value,
        )
        shutdown_status = LifecycleOperationStatus.FAILED
    registration = MoneyManagementApplicationRegistration(
        existing.composition_status,
        adapter,
        existing.startup_status,
        shutdown_status,
        safe_status,
    )
    app.state.money_management = registration
    event = (
        "Shutdown Durability Pending"
        if safe_status.durability_pending
        else "Shutdown Failed"
        if shutdown_status is LifecycleOperationStatus.FAILED
        else "Shutdown Succeeded"
    )
    _safe_log(
        logger,
        "warning"
        if shutdown_status is LifecycleOperationStatus.FAILED
        else "debug",
        event,
    )
    return registration
