"""MM-5A1 application integration for existing bot runtime events."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Optional, Tuple

from .enums import TradingMode
from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
)
from .loss_application_registration import MoneyManagementApplicationRegistration
from .loss_runtime_event_models import LossRuntimeEventType
from .loss_governance_projection_dispatcher import (
    LossGovernanceProjectionDispatcher,
)
from .loss_runtime_evaluation_bridge import LossRuntimeEvaluationBridge
from .loss_runtime_metrics_models import LossRuntimeMetricsReadRequest
from .loss_runtime_metrics_source import BotManagerLossRuntimeMetricsSource
from .loss_runtime_update_dispatcher import (
    LossRuntimeDispatchResult,
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
    dispatch_money_management_runtime_update,
)


APPLICATION_STATE_ATTRIBUTE = "money_management_runtime_hook"


class MoneyManagementRuntimeHookStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    DUPLICATE = "DUPLICATE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class MoneyManagementRuntimeHookResult:
    status: MoneyManagementRuntimeHookStatus
    event_type: Optional[LossRuntimeEventType]
    event_key: Optional[str] = field(repr=False)
    runtime_dispatch_status: Optional[LossRuntimeDispatchStatus]
    safe_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self, "status", MoneyManagementRuntimeHookStatus(self.status)
        )
        if self.event_type is not None:
            object.__setattr__(
                self, "event_type", LossRuntimeEventType(self.event_type)
            )
        if self.event_key is not None and (
            not isinstance(self.event_key, str) or not self.event_key.strip()
        ):
            raise ValueError("event key invalid")
        if self.runtime_dispatch_status is not None:
            object.__setattr__(
                self,
                "runtime_dispatch_status",
                LossRuntimeDispatchStatus(self.runtime_dispatch_status),
            )
        object.__setattr__(
            self, "safe_reasons", tuple(str(item) for item in self.safe_reasons)
        )

    def to_dict(self):
        return {
            "status": self.status.value,
            "eventType": self.event_type.value if self.event_type else None,
            "eventKeyConfigured": self.event_key is not None,
            "runtimeDispatchStatus": self.runtime_dispatch_status.value
            if self.runtime_dispatch_status
            else None,
            "safeReasons": list(self.safe_reasons),
        }


@dataclass(frozen=True)
class MoneyManagementRuntimeHookRegistration:
    hook: object = field(repr=False)
    bot_manager: object = field(repr=False)
    registered_at: datetime

    def __post_init__(self):
        if not isinstance(self.hook, MoneyManagementRuntimeHook):
            raise TypeError("runtime hook required")
        if not callable(
            getattr(self.bot_manager, "set_money_management_runtime_hook", None)
        ):
            raise TypeError("bot runtime hook boundary required")
        value = self.registered_at
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise TypeError("registered_at must be timezone-aware")
        object.__setattr__(
            self, "registered_at", value.astimezone(timezone.utc)
        )


def _safe_log(logger, level, event):
    method = getattr(logger, level, None) if logger is not None else None
    if callable(method):
        method("Money Management runtime hook: %s", event)


class MoneyManagementRuntimeHook:
    """Serializes and safely dispatches one application's runtime events."""

    def __init__(
        self,
        app,
        dispatcher,
        timestamp_source=None,
        maximum_age=timedelta(seconds=90),
        logger=None,
    ):
        if not isinstance(dispatcher, LossRuntimeUpdateDispatcher):
            raise TypeError("runtime update dispatcher required")
        if not isinstance(maximum_age, timedelta) or maximum_age.total_seconds() <= 0:
            raise ValueError("maximum_age must be positive")
        self._app = app
        self._dispatcher = dispatcher
        self._timestamp_source = timestamp_source or (
            lambda: datetime.now(timezone.utc)
        )
        if not callable(self._timestamp_source):
            raise TypeError("timestamp source required")
        self._maximum_age = maximum_age
        self._logger = logger
        self._active = True
        self._last_event_key = None
        self._last_dispatch_status = None
        self._last_dispatch_safe_reasons = ()
        self._timeline_recorder = None
        self._timeline_configuration_version_source = None
        self._lock = RLock()

    @property
    def active(self):
        with self._lock:
            return self._active

    @property
    def last_dispatch_status(self):
        with self._lock:
            return self._last_dispatch_status

    @property
    def last_dispatch_safe_reasons(self):
        with self._lock:
            return self._last_dispatch_safe_reasons

    @property
    def dispatcher(self):
        return self._dispatcher

    def invalidate_evaluation(self):
        with self._lock:
            self._last_dispatch_status = None
            self._last_dispatch_safe_reasons = ()

    def record_evaluation_status(self, status):
        if not isinstance(status, LossRuntimeDispatchStatus):
            raise TypeError("runtime dispatch status required")
        with self._lock:
            self._last_dispatch_status = status
            self._last_dispatch_safe_reasons = ()

    def record_evaluation_result(self, result):
        if not isinstance(result, LossRuntimeDispatchResult):
            raise TypeError("runtime dispatch result required")
        with self._lock:
            self._record_dispatch_result(result)

    def _record_dispatch_result(self, result):
        self._last_dispatch_status = result.status
        self._last_dispatch_safe_reasons = tuple(result.safe_reasons)
        if result.status not in (
            LossRuntimeDispatchStatus.APPLIED,
            LossRuntimeDispatchStatus.IDEMPOTENT,
        ):
            LossGovernanceProjectionDispatcher(
                timestamp_source=self._timestamp_source
            ).invalidate_runtime_authority(
                self._app,
                result.status,
                result.safe_reasons,
                result.runtime_revision,
                result.runtime_sequence,
            )

    def _record_dispatch_failure(self, reason):
        registration = getattr(
            getattr(self._app, "state", None), "money_management", None
        )
        snapshot = None
        if isinstance(registration, MoneyManagementApplicationRegistration):
            reader = getattr(registration.lifecycle_adapter, "get_snapshot", None)
            try:
                snapshot = reader() if callable(reader) else None
            except Exception:
                snapshot = None
        result = LossRuntimeDispatchResult(
            LossRuntimeDispatchStatus.FAILED,
            None,
            None,
            getattr(snapshot, "revision", None),
            getattr(snapshot, "sequence", None),
            False,
            (reason,),
            False,
            False,
        )
        self._record_dispatch_result(result)

    def attach_timeline_recorder(
        self, recorder, configuration_version_source=None
    ):
        if not callable(getattr(recorder, "record_runtime", None)):
            raise TypeError("timeline recorder required")
        if (
            configuration_version_source is not None
            and not callable(configuration_version_source)
        ):
            raise TypeError("configuration version source invalid")
        with self._lock:
            self._timeline_recorder = recorder
            self._timeline_configuration_version_source = (
                configuration_version_source
            )
            return recorder

    def stop(self):
        with self._lock:
            already_stopped = not self._active
            self._active = False
            return already_stopped

    def refresh_authority(self):
        """Refresh entry authority from the current authoritative metrics."""

        with self._lock:
            registration = getattr(
                getattr(self._app, "state", None), "money_management", None
            )
            if (
                not self._active
                or not isinstance(
                    registration, MoneyManagementApplicationRegistration
                )
                or registration.composition_status
                is not CompositionReadinessStatus.READY
                or registration.safe_status.lifecycle_state
                is not ApplicationLifecycleState.RUNNING
                or not registration.safe_status.runtime_available
            ):
                self._last_dispatch_status = None
                return False
            try:
                now = self._timestamp_source()
                if (
                    not isinstance(now, datetime)
                    or now.tzinfo is None
                    or now.utcoffset() is None
                ):
                    self._last_dispatch_status = None
                    return False
                request = LossRuntimeMetricsReadRequest(
                    "bot-manager",
                    now.astimezone(timezone.utc),
                    self._maximum_age,
                )
                result = dispatch_money_management_runtime_update(
                    self._app,
                    self._dispatcher,
                    request,
                    LossRuntimeEventType.BALANCE_UPDATE,
                )
            except Exception:
                self._record_dispatch_failure("authority refresh failed")
                _safe_log(self._logger, "warning", "Authority Refresh Failed")
                return False
            if not isinstance(result, LossRuntimeDispatchResult):
                self._record_dispatch_failure("authority refresh result invalid")
                return False
            self._record_dispatch_result(result)
            authoritative = result.status in (
                LossRuntimeDispatchStatus.APPLIED,
                LossRuntimeDispatchStatus.IDEMPOTENT,
            )
            if not authoritative:
                _safe_log(self._logger, "warning", "Authority Refresh Rejected")
            return authoritative

    def handle(self, event_type, event_key):
        try:
            event_type = LossRuntimeEventType(event_type)
        except (TypeError, ValueError):
            return MoneyManagementRuntimeHookResult(
                MoneyManagementRuntimeHookStatus.FAILED,
                None,
                None,
                None,
                ("runtime hook event invalid",),
            )
        if event_type not in (
            LossRuntimeEventType.TRADE_CLOSE,
            LossRuntimeEventType.BALANCE_UPDATE,
            LossRuntimeEventType.POSITION_UPDATE,
        ):
            return MoneyManagementRuntimeHookResult(
                MoneyManagementRuntimeHookStatus.SKIPPED,
                event_type,
                str(event_key) if event_key is not None else None,
                None,
                ("runtime hook event not registered",),
            )
        if not isinstance(event_key, str) or not event_key.strip():
            return MoneyManagementRuntimeHookResult(
                MoneyManagementRuntimeHookStatus.FAILED,
                event_type,
                None,
                None,
                ("runtime hook event key invalid",),
            )
        with self._lock:
            registration = getattr(
                getattr(self._app, "state", None), "money_management", None
            )
            if not self._active:
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.SKIPPED,
                    event_type,
                    event_key,
                    None,
                    ("runtime hook stopped",),
                )
            if (
                not isinstance(
                    registration, MoneyManagementApplicationRegistration
                )
                or registration.composition_status
                is not CompositionReadinessStatus.READY
                or registration.safe_status.lifecycle_state
                is not ApplicationLifecycleState.RUNNING
                or not registration.safe_status.runtime_available
            ):
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.SKIPPED,
                    event_type,
                    event_key,
                    None,
                    ("money management lifecycle not running",),
                )
            if event_key == self._last_event_key:
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.DUPLICATE,
                    event_type,
                    event_key,
                    self._last_dispatch_status,
                    ("runtime hook duplicate",),
                )
            self._last_event_key = event_key
            now = self._timestamp_source()
            if (
                not isinstance(now, datetime)
                or now.tzinfo is None
                or now.utcoffset() is None
            ):
                self._last_dispatch_status = None
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.FAILED,
                    event_type,
                    event_key,
                    None,
                    ("runtime hook timestamp invalid",),
                )
            request = LossRuntimeMetricsReadRequest(
                "bot-manager",
                now.astimezone(timezone.utc),
                self._maximum_age,
            )
            try:
                result = dispatch_money_management_runtime_update(
                    self._app,
                    self._dispatcher,
                    request,
                    event_type,
                )
            except Exception:
                _safe_log(self._logger, "warning", "Dispatch Failed")
                self._record_dispatch_failure("runtime hook dispatch failed")
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.FAILED,
                    event_type,
                    event_key,
                    None,
                    ("runtime hook dispatch failed",),
                )
            if not isinstance(result, LossRuntimeDispatchResult):
                _safe_log(self._logger, "warning", "Dispatch Result Invalid")
                self._record_dispatch_failure("runtime hook dispatch result invalid")
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.FAILED,
                    event_type,
                    event_key,
                    None,
                    ("runtime hook dispatch result invalid",),
                )
            self._record_dispatch_result(result)
            if result.status in (
                LossRuntimeDispatchStatus.APPLIED,
                LossRuntimeDispatchStatus.IDEMPOTENT,
            ):
                if (
                    result.status is LossRuntimeDispatchStatus.APPLIED
                    and self._timeline_recorder is not None
                ):
                    try:
                        metrics_result = self._dispatcher.get_last_metrics_result()
                        metrics = getattr(metrics_result, "metrics", None)
                        config_provider = registration.base_config_provider
                        config = (
                            config_provider.get_config()
                            if config_provider is not None else None
                        )
                        snapshot = registration.lifecycle_adapter.get_snapshot()
                        decision = getattr(
                            getattr(snapshot, "state", None),
                            "last_decision",
                            None,
                        )
                        state = getattr(
                            getattr(decision, "decision_state", None),
                            "value",
                            "UNKNOWN",
                        )
                        diagnostics = tuple(
                            item.value for item in getattr(
                                decision, "diagnostic_reasons", ()
                            )
                        )
                        block_reasons = tuple(
                            item.value for item in getattr(
                                decision, "block_reasons", ()
                            )
                        )
                        hold_reasons = tuple(
                            item.value for item in getattr(
                                decision, "hold_reasons", ()
                            )
                        )
                        warning_reasons = tuple(
                            item.value for item in getattr(
                                decision, "warning_reasons", ()
                            )
                        )
                        self._timeline_recorder.record_runtime(
                            metrics,
                            config,
                            state,
                            diagnostics,
                            event_key,
                            configuration_version=(
                                self._timeline_configuration_version_source()
                                if self._timeline_configuration_version_source
                                is not None
                                else 0
                            ),
                            reason_codes=(
                                block_reasons
                                + hold_reasons
                                + warning_reasons
                            ),
                            reason_groups={
                                "block": block_reasons,
                                "hold": hold_reasons,
                                "warning": warning_reasons,
                            },
                        )
                    except Exception:
                        _safe_log(
                            self._logger, "warning", "Timeline Record Failed"
                        )
                _safe_log(self._logger, "debug", "Dispatched")
                return MoneyManagementRuntimeHookResult(
                    MoneyManagementRuntimeHookStatus.DISPATCHED,
                    event_type,
                    event_key,
                    result.status,
                    (),
                )
            _safe_log(self._logger, "warning", "Dispatch Rejected")
            return MoneyManagementRuntimeHookResult(
                MoneyManagementRuntimeHookStatus.FAILED,
                event_type,
                event_key,
                result.status,
                ("runtime hook update not applied",),
            )


def register_money_management_runtime_hook(
    app,
    bot_manager_factory,
    timestamp_source=None,
    logger=None,
):
    state = getattr(app, "state", None)
    existing = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    if isinstance(existing, MoneyManagementRuntimeHookRegistration):
        return existing
    registration = getattr(state, "money_management", None)
    if (
        not isinstance(registration, MoneyManagementApplicationRegistration)
        or registration.composition_status is not CompositionReadinessStatus.READY
        or registration.safe_status.lifecycle_state
        is not ApplicationLifecycleState.RUNNING
        or not registration.safe_status.runtime_available
    ):
        return None
    if not callable(bot_manager_factory):
        return None
    try:
        bot_manager = bot_manager_factory()
        snapshot_reader = getattr(
            registration.lifecycle_adapter,
            "get_snapshot",
            None,
        )
        runtime_snapshot = (
            snapshot_reader()
            if callable(snapshot_reader)
            else None
        )
        initializer = getattr(
            bot_manager,
            "initialize_money_management_runtime_metrics",
            None,
        )
        if callable(initializer) and runtime_snapshot is not None:
            initializer(
                runtime_snapshot.state,
                runtime_snapshot.state_source,
                runtime_snapshot.updated_at,
            )
        source = BotManagerLossRuntimeMetricsSource(
            bot_manager,
            timestamp_source=timestamp_source,
        )
        def runtime_trading_mode():
            mode = getattr(bot_manager, "config", {}).get("mode")
            if not isinstance(mode, str) or not mode.strip():
                mode = getattr(
                    getattr(bot_manager, "engine", None), "mode", None
                )
            if not isinstance(mode, str) or not mode.strip():
                raise ValueError("runtime trading mode unavailable")
            return TradingMode(mode.strip().upper())

        evaluation_bridge = LossRuntimeEvaluationBridge(
            trading_mode_provider=runtime_trading_mode
        )
        dispatcher = LossRuntimeUpdateDispatcher(
            source, evaluation_bridge=evaluation_bridge
        )
        hook = MoneyManagementRuntimeHook(
            app,
            dispatcher,
            timestamp_source=timestamp_source,
            logger=logger,
        )
        now = (
            timestamp_source()
            if timestamp_source is not None
            else datetime.now(timezone.utc)
        )
        hook_registration = MoneyManagementRuntimeHookRegistration(
            hook, bot_manager, now
        )
        installed = bot_manager.set_money_management_runtime_hook(hook.handle)
        if installed is not True:
            hook.stop()
            return None
        setattr(state, APPLICATION_STATE_ATTRIBUTE, hook_registration)
        current_metrics = getattr(
            bot_manager, "get_runtime_metrics_snapshot", lambda: {}
        )()
        if (
            current_metrics.get("sourceState")
            == "STOPPED_PAPER_MAINTENANCE"
        ):
            hook.handle(
                LossRuntimeEventType.BALANCE_UPDATE,
                (
                    "stopped-paper-maintenance:"
                    f"{current_metrics.get('runtimeInstanceId')}:"
                    f"{current_metrics.get('metricsRevision')}"
                ),
            )
        _safe_log(
            logger,
            "info",
            (
                f"Registered runtimeIdentity={getattr(bot_manager, 'runtime_instance_id', None)} "
                f"botIdentity={id(bot_manager)} hookIdentity={id(hook)} "
                f"authoritySource={type(registration.lifecycle_adapter).__name__} "
                f"registeredAt={hook_registration.registered_at.isoformat()}"
            ),
        )
        return hook_registration
    except Exception:
        _safe_log(logger, "warning", "Registration Failed")
        return None


def unregister_money_management_runtime_hook(app, logger=None):
    state = getattr(app, "state", None)
    registration = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    if not isinstance(registration, MoneyManagementRuntimeHookRegistration):
        return False
    registration.hook.stop()
    try:
        registration.bot_manager.set_money_management_runtime_hook(None)
    except Exception:
        _safe_log(logger, "warning", "Unregistration Failed")
        return False
    setattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    _safe_log(logger, "debug", "Unregistered")
    return True
