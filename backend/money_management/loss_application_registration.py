"""MM-4G FastAPI registration helpers with safe application-state projection."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Optional

from .enums import MoneyManagementProfile, TradingMode
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
    resolve_cash_flow_runtime_settings,
    resolve_loss_limit_application_configuration,
)
from .loss_runtime_coordination_models import LossLimitRuntimeStopRequest
from .loss_runtime_integration_models import RecoveryStatus, StartupMode
from .loss_runtime_startup_models import LossLimitRuntimeStartupRequest
from .models import MoneyManagementConfig


class MoneyManagementConfigProvider:
    __slots__ = ("__config", "__lock")

    def __init__(self, config):
        if not isinstance(config, MoneyManagementConfig):
            raise TypeError("Money Management base configuration required")
        self.__config = config
        self.__lock = RLock()

    def get_config(self):
        with self.__lock:
            return self.__config

    def update_total_exposure_pct(self, value):
        with self.__lock:
            candidate = replace(
                self.__config,
                total_exposure_pct=value,
            )
            self.__config = candidate
            return candidate

    def replace_config(self, config):
        if not isinstance(config, MoneyManagementConfig):
            raise TypeError("Money Management base configuration required")
        with self.__lock:
            self.__config = config
            return config


def build_default_money_management_config():
    return MoneyManagementConfig(
        profile=MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
        mode=TradingMode.PAPER,
        initial_reference_equity=Decimal("1000"),
        risk_per_trade_pct=Decimal("0.50"),
        maximum_position_notional=Decimal("100"),
        maximum_drawdown_pct=Decimal("5"),
        total_exposure_pct=Decimal("20"),
        single_symbol_exposure_pct=Decimal("10"),
        maximum_leverage=Decimal("5"),
        multi_bot_enabled=False,
    )


def get_money_management_config(app):
    registration = getattr(
        getattr(app, "state", None),
        "money_management",
        None,
    )
    if not isinstance(registration, MoneyManagementApplicationRegistration):
        return None
    provider = registration.base_config_provider
    return provider.get_config() if provider is not None else None


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
    base_config_provider: Optional[MoneyManagementConfigProvider] = field(
        default=None,
        repr=False,
    )

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
        if self.base_config_provider is not None and not isinstance(
            self.base_config_provider,
            MoneyManagementConfigProvider,
        ):
            raise TypeError("base config provider invalid")

    def to_dict(self):
        return {
            "compositionStatus": self.composition_status.value,
            "lifecycleAdapterAvailable": self.lifecycle_adapter is not None,
            "startupStatus": self.startup_status.value if self.startup_status else None,
            "shutdownStatus": self.shutdown_status.value if self.shutdown_status else None,
            "safeStatus": self.safe_status.to_dict(),
            "baseConfigAvailable": self.base_config_provider is not None,
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
    base_configuration=None,
    base_configuration_factory=build_default_money_management_config,
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
        base_config = (
            base_configuration
            if base_configuration is not None
            else base_configuration_factory()
        )
        base_config_provider = MoneyManagementConfigProvider(base_config)
    except Exception:
        base_config_provider = None
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
            base_config_provider,
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
            base_config_provider,
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
            base_config_provider,
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
            base_config_provider,
        )
        app.state.money_management = registration
        _safe_log(logger, "warning", "Startup Failed")
        return registration
    registration = MoneyManagementApplicationRegistration(
        composition.status,
        adapter,
        startup_status,
        None,
        safe_status,
        base_config_provider,
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
    cash_flow_runtime = getattr(adapter, "cash_flow_runtime", None) if adapter else None
    if cash_flow_runtime is not None:
        try:
            cash_flow_runtime.stop()
        except Exception:
            _safe_log(logger, "warning", "Cash Flow Scheduler Stop Failed")
    if adapter is None:
        registration = MoneyManagementApplicationRegistration(
            existing.composition_status,
            None,
            existing.startup_status,
            LifecycleOperationStatus.IDEMPOTENT,
            existing.safe_status,
            existing.base_config_provider,
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
        existing.base_config_provider,
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


def start_money_management_cash_flow_runtime(
    app, *, client=None, client_factory=None, settings=None, logger=None,
):
    """Start the sole production cash-flow owner after MM lifecycle startup."""
    registration = getattr(app.state, "money_management", None)
    if not isinstance(registration, MoneyManagementApplicationRegistration):
        return None
    adapter = registration.lifecycle_adapter
    coordinator = getattr(adapter, "cash_flow_transaction_coordinator", None) if adapter else None
    if adapter is None or coordinator is None or registration.safe_status.lifecycle_state is not ApplicationLifecycleState.RUNNING:
        return None
    existing = getattr(adapter, "cash_flow_runtime", None)
    if existing is not None:
        return existing
    try:
        enabled, interval, freshness = resolve_cash_flow_runtime_settings(settings)
        from .cash_flow_runtime import CashFlowAuthorityReader, CashFlowSyncRuntime
        if not enabled:
            runtime = CashFlowSyncRuntime(
                persistence_directory=coordinator._base_directory,
                reader=None, equity_source=None,
                transaction_coordinator=coordinator, enabled=False,
                poll_interval_seconds=interval, freshness_seconds=freshness,
            )
            adapter.cash_flow_runtime = runtime
            runtime.start(immediate=False)
            return runtime
        if client is None:
            if client_factory is None:
                from backend.execution.kucoin_trade import KucoinTradeClient
                client_factory = KucoinTradeClient
            client = client_factory()
        def current_equity():
            overview = client.get_account_overview() or {}
            return {
                "sourceAuthority": "REAL_LIVE_ACCOUNT",
                "equity": overview.get("equity", overview.get("accountEquity")),
            }

        runtime = CashFlowSyncRuntime(
            persistence_directory=coordinator._base_directory,
            reader=CashFlowAuthorityReader(client), equity_source=current_equity,
            transaction_coordinator=coordinator, enabled=enabled,
            poll_interval_seconds=interval, freshness_seconds=freshness,
        )
        adapter.cash_flow_runtime = runtime
        runtime.start(immediate=True)
        return runtime
    except Exception:
        _safe_log(logger, "warning", "Cash Flow Scheduler Initialization Failed")
        return None


def get_money_management_cash_flow_status(app):
    registration = getattr(app.state, "money_management", None)
    adapter = registration.lifecycle_adapter if isinstance(registration, MoneyManagementApplicationRegistration) else None
    runtime = getattr(adapter, "cash_flow_runtime", None) if adapter else None
    return runtime.read_model() if runtime is not None else {
        "cashFlowAuthority": "DISABLED", "cashFlowFresh": False,
        "lastSuccessfulSyncAt": None, "lastAttemptAt": None,
        "syncState": "STOPPED", "lastErrorReason": None,
        "checkpointRevision": 0,
    }
