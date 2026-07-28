"""MM-5A3 safe HTTP-facing status, configuration, and recovery boundary."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from threading import RLock
from typing import Optional, Tuple

from .enums import RiskState
from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
)
from .loss_application_registration import (
    MoneyManagementApplicationRegistration,
    MoneyManagementConfigProvider,
    MoneyManagementSafeApplicationStatus,
)
from .loss_governance_projection_dispatcher import (
    LossGovernanceProjectionDispatcher,
    dispatch_money_management_governance_projection,
    get_money_management_governance_projection,
)
from .loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernancePublicSnapshot,
)
from .loss_models import LossLimitConfig
from .loss_reason_models import LossReasonContract
from .loss_runtime_event_models import LossRuntimeEventType
from .loss_runtime_hook import (
    APPLICATION_STATE_ATTRIBUTE as RUNTIME_HOOK_STATE_ATTRIBUTE,
    MoneyManagementRuntimeHookRegistration,
)
from .loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetrics,
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
)
from .loss_runtime_store_models import LossLimitRuntimeSnapshot
from .loss_runtime_update_dispatcher import (
    LossRuntimeDispatchResult,
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)


APPLICATION_STATE_ATTRIBUTE = "money_management_http_boundary"
HTTP_BOUNDARY_SCHEMA_VERSION = "money-management-http/v1"
DEFAULT_MAXIMUM_METRICS_AGE = timedelta(seconds=90)


def _utc(name, value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _serialize(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    return value


def _values(items):
    return tuple(item.value for item in items)


@dataclass(frozen=True)
class MoneyManagementApiError:
    status_code: int
    code: str
    message: str
    retryable: bool
    timestamp: datetime

    def __post_init__(self):
        if type(self.status_code) is not int or self.status_code < 400:
            raise ValueError("error status code invalid")
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("error code required")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("safe message required")
        if type(self.retryable) is not bool:
            raise TypeError("retryable must be bool")
        object.__setattr__(self, "timestamp", _utc("timestamp", self.timestamp))

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "timestamp": _serialize(self.timestamp),
        }


class MoneyManagementApiBoundaryException(Exception):
    def __init__(self, error):
        if not isinstance(error, MoneyManagementApiError):
            raise TypeError("safe API error required")
        super().__init__(error.code)
        self.error = error


@dataclass(frozen=True)
class MoneyManagementMetricsResponse:
    status: str
    equity: Optional[Decimal]
    available_capital: Optional[Decimal]
    peak_equity: Optional[Decimal]
    drawdown_amount: Optional[Decimal]
    drawdown_percent: Optional[Decimal]
    daily_pnl: Optional[Decimal]
    weekly_pnl: Optional[Decimal]
    monthly_pnl: Optional[Decimal]
    daily_trade_count: Optional[int]
    weekly_trade_count: Optional[int]
    monthly_trade_count: Optional[int]
    open_exposure: Optional[Decimal]
    exposure_limit: Optional[Decimal]
    generated_at: Optional[datetime]

    def to_dict(self):
        return {
            "status": self.status,
            "equity": _serialize(self.equity),
            "availableCapital": _serialize(self.available_capital),
            "peakEquity": _serialize(self.peak_equity),
            "drawdownAmount": _serialize(self.drawdown_amount),
            "drawdownPercent": _serialize(self.drawdown_percent),
            "dailyPnl": _serialize(self.daily_pnl),
            "weeklyPnl": _serialize(self.weekly_pnl),
            "monthlyPnl": _serialize(self.monthly_pnl),
            "dailyTradeCount": self.daily_trade_count,
            "weeklyTradeCount": self.weekly_trade_count,
            "monthlyTradeCount": self.monthly_trade_count,
            "openExposure": _serialize(self.open_exposure),
            "exposureLimit": _serialize(self.exposure_limit),
            "metricsGeneratedAt": _serialize(self.generated_at),
        }


@dataclass(frozen=True)
class MoneyManagementConfigurationResponse:
    available: bool
    enabled: bool
    daily_warning_percent: Decimal
    daily_block_percent: Decimal
    weekly_warning_percent: Decimal
    weekly_block_percent: Decimal
    monthly_warning_percent: Decimal
    monthly_block_percent: Decimal
    maximum_drawdown_percent: Decimal
    total_exposure_percent: Optional[Decimal]
    revision: int
    source: str
    updated_at: datetime

    def to_dict(self):
        return {
            "available": self.available,
            "enabled": self.enabled,
            "dailyWarningPercent": _serialize(self.daily_warning_percent),
            "dailyBlockPercent": _serialize(self.daily_block_percent),
            "weeklyWarningPercent": _serialize(self.weekly_warning_percent),
            "weeklyBlockPercent": _serialize(self.weekly_block_percent),
            "monthlyWarningPercent": _serialize(self.monthly_warning_percent),
            "monthlyBlockPercent": _serialize(self.monthly_block_percent),
            "maximumDrawdownPercent": _serialize(
                self.maximum_drawdown_percent
            ),
            "totalExposurePercent": _serialize(
                self.total_exposure_percent
            ),
            "revision": self.revision,
            "source": self.source,
            "updatedAt": _serialize(self.updated_at),
        }


@dataclass(frozen=True)
class MoneyManagementStatusResponse:
    available: bool
    enabled: bool
    lifecycle_state: str
    risk_state: str
    recommended_action: str
    execution_entry_allowed: bool
    warning_reasons: Tuple[str, ...]
    hold_reasons: Tuple[str, ...]
    block_reasons: Tuple[str, ...]
    diagnostic_reasons: Tuple[str, ...]
    metrics_status: str
    projection_status: str
    recovery_required: bool
    safe_reason: Optional[str]
    generated_at: datetime
    revision: Optional[int]
    sequence: Optional[int]
    configuration_revision: int
    metrics: MoneyManagementMetricsResponse
    configuration: MoneyManagementConfigurationResponse

    def to_dict(self):
        return {
            "schemaVersion": HTTP_BOUNDARY_SCHEMA_VERSION,
            "available": self.available,
            "enabled": self.enabled,
            "lifecycleState": self.lifecycle_state,
            "riskState": self.risk_state,
            "recommendedAction": self.recommended_action,
            "executionEntryAllowed": self.execution_entry_allowed,
            "warningReasons": list(self.warning_reasons),
            "holdReasons": list(self.hold_reasons),
            "blockReasons": list(self.block_reasons),
            "diagnosticReasons": list(self.diagnostic_reasons),
            "metricsStatus": self.metrics_status,
            "projectionStatus": self.projection_status,
            "recoveryRequired": self.recovery_required,
            "safeReason": self.safe_reason,
            "generatedAt": _serialize(self.generated_at),
            "revision": self.revision,
            "sequence": self.sequence,
            "configurationRevision": self.configuration_revision,
            "metrics": self.metrics.to_dict(),
            "configuration": self.configuration.to_dict(),
        }


@dataclass(frozen=True)
class MoneyManagementConfigurationUpdateResponse:
    applied: bool
    reevaluated: bool
    safe_reason: str
    configuration: MoneyManagementConfigurationResponse
    status: MoneyManagementStatusResponse

    def to_dict(self):
        return {
            "applied": self.applied,
            "reevaluated": self.reevaluated,
            "safeReason": self.safe_reason,
            "configuration": self.configuration.to_dict(),
            "status": self.status.to_dict(),
        }


@dataclass(frozen=True)
class MoneyManagementRecoveryResponse:
    accepted: bool
    recovered: bool
    previous_state: str
    current_state: str
    recommended_action: str
    execution_entry_allowed: bool
    safe_reason: str
    generated_at: datetime
    revision: Optional[int]
    sequence: Optional[int]

    def to_dict(self):
        return {
            "accepted": self.accepted,
            "recovered": self.recovered,
            "previousState": self.previous_state,
            "currentState": self.current_state,
            "recommendedAction": self.recommended_action,
            "executionEntryAllowed": self.execution_entry_allowed,
            "safeReason": self.safe_reason,
            "generatedAt": _serialize(self.generated_at),
            "revision": self.revision,
            "sequence": self.sequence,
        }


_CONFIG_FIELDS = {
    "dailyWarningPercent": "daily_warning_pct",
    "dailyBlockPercent": "daily_block_pct",
    "weeklyWarningPercent": "weekly_warning_pct",
    "weeklyBlockPercent": "weekly_block_pct",
    "monthlyWarningPercent": "monthly_warning_pct",
    "monthlyBlockPercent": "monthly_block_pct",
    "maximumDrawdownPercent": "maximum_drawdown_pct",
}
_BASE_CONFIG_FIELD = "totalExposurePercent"
_REQUEST_FIELDS = frozenset((
    *_CONFIG_FIELDS,
    _BASE_CONFIG_FIELD,
    "enabled",
    "expectedRevision",
))


def _strict_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError(f"{name} must be a decimal string")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{name} must be a decimal string")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a valid decimal") from None
    if not result.is_finite() or result <= 0 or result > Decimal("100"):
        raise ValueError(f"{name} is outside the supported percentage range")
    return result


class MoneyManagementHttpBoundary:
    """Application-scoped HTTP service with no network or filesystem access."""

    def __init__(
        self,
        app,
        dispatcher=None,
        timestamp_source=None,
        maximum_metrics_age=DEFAULT_MAXIMUM_METRICS_AGE,
    ):
        if dispatcher is not None and not isinstance(
            dispatcher, LossRuntimeUpdateDispatcher
        ):
            raise TypeError("runtime dispatcher invalid")
        if (
            not isinstance(maximum_metrics_age, timedelta)
            or maximum_metrics_age.total_seconds() <= 0
        ):
            raise ValueError("maximum metrics age must be positive")
        self._app = app
        self._dispatcher = dispatcher
        self._timestamp_source = timestamp_source or (
            lambda: datetime.now(timezone.utc)
        )
        if not callable(self._timestamp_source):
            raise TypeError("timestamp source required")
        self._maximum_metrics_age = maximum_metrics_age
        self._projection_dispatcher = LossGovernanceProjectionDispatcher(
            timestamp_source=self._timestamp_source
        )
        registration = getattr(
            getattr(app, "state", None), "money_management", None
        )
        self._base_registration = (
            registration
            if isinstance(registration, MoneyManagementApplicationRegistration)
            else None
        )
        self._enabled = bool(
            self._base_registration is not None
            and self._base_registration.safe_status.enabled
        )
        self._base_config_provider = (
            self._base_registration.base_config_provider
            if self._base_registration is not None
            and isinstance(
                self._base_registration.base_config_provider,
                MoneyManagementConfigProvider,
            )
            else None
        )
        self._configuration = (
            dispatcher.get_configuration()
            if dispatcher is not None
            else LossLimitConfig()
        )
        self._configuration_revision = 1
        self._configuration_source = "DEFAULT"
        self._configuration_updated_at = self._now()
        self._recovery_in_progress = False
        self._lock = RLock()

    def _now(self):
        return _utc("timestamp", self._timestamp_source())

    def _error(self, status_code, code, message, retryable=False):
        raise MoneyManagementApiBoundaryException(
            MoneyManagementApiError(
                status_code,
                code,
                message,
                retryable,
                self._now(),
            )
        )

    def _hook_registration(self):
        value = getattr(
            getattr(self._app, "state", None),
            RUNTIME_HOOK_STATE_ATTRIBUTE,
            None,
        )
        return (
            value
            if isinstance(value, MoneyManagementRuntimeHookRegistration)
            else None
        )

    def _configuration_response(
        self,
        configuration,
        enabled,
        revision,
        source,
        updated_at,
    ):
        base_config = (
            self._base_config_provider.get_config()
            if self._base_config_provider is not None
            else None
        )
        return MoneyManagementConfigurationResponse(
            self._dispatcher is not None and self._base_registration is not None,
            enabled,
            configuration.daily_warning_pct,
            configuration.daily_block_pct,
            configuration.weekly_warning_pct,
            configuration.weekly_block_pct,
            configuration.monthly_warning_pct,
            configuration.monthly_block_pct,
            configuration.maximum_drawdown_pct,
            base_config.total_exposure_pct
            if base_config is not None
            else None,
            revision,
            source,
            updated_at,
        )

    def get_configuration(self):
        with self._lock:
            return self._configuration_response(
                self._configuration,
                self._enabled,
                self._configuration_revision,
                self._configuration_source,
                self._configuration_updated_at,
            )

    @staticmethod
    def _metrics_response(result, exposure_limit=None):
        status = (
            result.status.value
            if isinstance(result, LossRuntimeMetricsReadResult)
            else LossRuntimeMetricsReadStatus.UNAVAILABLE.value
        )
        metrics = (
            result.metrics
            if isinstance(result, LossRuntimeMetricsReadResult)
            and isinstance(result.metrics, LossRuntimeMetrics)
            else None
        )
        return MoneyManagementMetricsResponse(
            status,
            metrics.equity if metrics else None,
            metrics.available_balance if metrics else None,
            metrics.peak_equity if metrics else None,
            (
                metrics.peak_equity - metrics.equity
                if metrics
                and metrics.peak_equity is not None
                and metrics.equity is not None
                else None
            ),
            metrics.drawdown if metrics else None,
            metrics.daily_pnl if metrics else None,
            metrics.weekly_pnl if metrics else None,
            metrics.monthly_pnl if metrics else None,
            metrics.trade_count_daily if metrics else None,
            metrics.trade_count_weekly if metrics else None,
            metrics.trade_count_monthly if metrics else None,
            metrics.open_exposure if metrics else None,
            exposure_limit,
            metrics.captured_at if metrics else None,
        )

    def get_status(self):
        now = self._now()
        with self._lock:
            enabled = self._enabled
            config = self._configuration
            config_revision = self._configuration_revision
            config_source = self._configuration_source
            config_updated = self._configuration_updated_at
            dispatcher = self._dispatcher
        configuration = self._configuration_response(
            config,
            enabled,
            config_revision,
            config_source,
            config_updated,
        )
        registration = getattr(
            getattr(self._app, "state", None), "money_management", None
        )
        hook_registration = self._hook_registration()
        hook_healthy = bool(
            hook_registration is not None
            and hook_registration.hook.last_dispatch_status
            in (
                LossRuntimeDispatchStatus.APPLIED,
                LossRuntimeDispatchStatus.IDEMPOTENT,
            )
        )
        lifecycle_status = None
        runtime_snapshot = None
        if (
            isinstance(registration, MoneyManagementApplicationRegistration)
            and registration.lifecycle_adapter is not None
        ):
            try:
                lifecycle_status = registration.lifecycle_adapter.get_status()
                runtime_snapshot = registration.lifecycle_adapter.get_snapshot()
            except Exception:
                lifecycle_status = None
                runtime_snapshot = None
        metrics_result = (
            dispatcher.get_last_metrics_result()
            if dispatcher is not None
            else None
        )
        metrics = (
            metrics_result.metrics
            if isinstance(metrics_result, LossRuntimeMetricsReadResult)
            else None
        )
        base_config = (
            self._base_config_provider.get_config()
            if self._base_config_provider is not None
            else None
        )
        metrics_fresh = bool(
            isinstance(metrics, LossRuntimeMetrics)
            and metrics.data_quality is LossRuntimeDataQuality.COMPLETE
            and metrics.captured_at <= now
            and now - metrics.captured_at <= self._maximum_metrics_age
        )
        public = get_money_management_governance_projection(self._app)
        projection_fresh = bool(
            isinstance(public, LossGovernancePublicSnapshot)
            and public.generated_at <= now
            and now - public.generated_at <= self._maximum_metrics_age
        )
        revisions_match = bool(
            isinstance(public, LossGovernancePublicSnapshot)
            and isinstance(runtime_snapshot, LossLimitRuntimeSnapshot)
            and public.revision == runtime_snapshot.revision
            and public.sequence == runtime_snapshot.sequence
        )
        lifecycle_running = bool(
            lifecycle_status is not None
            and lifecycle_status.lifecycle_state
            is ApplicationLifecycleState.RUNNING
        )
        registration_ready = bool(
            isinstance(registration, MoneyManagementApplicationRegistration)
            and registration.composition_status
            is CompositionReadinessStatus.READY
        )
        available = bool(
            enabled
            and registration_ready
            and lifecycle_running
            and hook_healthy
            and metrics_fresh
            and projection_fresh
            and revisions_match
            and base_config is not None
        )
        decision = (
            runtime_snapshot.state.last_decision
            if isinstance(runtime_snapshot, LossLimitRuntimeSnapshot)
            and runtime_snapshot.state is not None
            and isinstance(
                runtime_snapshot.state.last_decision, LossReasonContract
            )
            else None
        )
        projection = public.projection if isinstance(
            public, LossGovernancePublicSnapshot
        ) else None
        execution_allowed = bool(
            available
            and projection is not None
            and projection.entry_permission is LossEntryPermission.ALLOW
            and projection.new_entry_allowed is True
        )
        safe_reason = None
        if not enabled:
            safe_reason = "MONEY_MANAGEMENT_DISABLED"
        elif not registration_ready:
            safe_reason = "MONEY_MANAGEMENT_NOT_REGISTERED"
        elif not lifecycle_running:
            safe_reason = "MONEY_MANAGEMENT_UNAVAILABLE"
        elif not hook_healthy:
            safe_reason = "AUTHORITATIVE_METRICS_INCOMPLETE"
        elif not metrics_fresh:
            safe_reason = "AUTHORITATIVE_METRICS_INCOMPLETE"
        elif not projection_fresh or not revisions_match:
            safe_reason = "INTERNAL_STATE_UNAVAILABLE"
        elif base_config is None:
            safe_reason = "INTERNAL_STATE_UNAVAILABLE"
        risk_state = (
            decision.decision_state.value
            if decision is not None and available
            else "UNKNOWN"
        )
        recommended_action = (
            decision.recommended_action.value
            if decision is not None and available
            else "UNKNOWN"
        )
        diagnostics = list(
            _values(projection.diagnostic_reasons)
            if projection is not None
            else ()
        )
        if safe_reason is not None and safe_reason not in diagnostics:
            diagnostics.append(safe_reason)
        blocks = list(
            _values(decision.block_reasons) if decision is not None else ()
        )
        if not execution_allowed and safe_reason is not None:
            blocks.append("UNKNOWN_STATE")
        generated_at = (
            public.generated_at
            if isinstance(public, LossGovernancePublicSnapshot)
            else now
        )
        return MoneyManagementStatusResponse(
            available,
            enabled,
            lifecycle_status.lifecycle_state.value
            if lifecycle_status is not None
            else "UNAVAILABLE",
            risk_state,
            recommended_action,
            execution_allowed,
            _values(decision.warning_reasons) if decision is not None else (),
            _values(decision.hold_reasons) if decision is not None else (),
            tuple(blocks),
            tuple(diagnostics),
            metrics_result.status.value
            if isinstance(metrics_result, LossRuntimeMetricsReadResult)
            else LossRuntimeMetricsReadStatus.UNAVAILABLE.value,
            projection.entry_permission.value
            if projection is not None
            else LossEntryPermission.UNKNOWN.value,
            bool(
                not available
                or (
                    projection is not None
                    and projection.recovery_required
                )
            ),
            safe_reason,
            generated_at,
            public.revision
            if isinstance(public, LossGovernancePublicSnapshot)
            else None,
            public.sequence
            if isinstance(public, LossGovernancePublicSnapshot)
            else None,
            config_revision,
            self._metrics_response(
                metrics_result,
                base_config.total_exposure_pct
                if base_config is not None
                else None,
            ),
            configuration,
        )

    def _normalize_update(self, payload):
        if not isinstance(payload, Mapping):
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Configuration request must be a JSON object.",
            )
        keys = set(payload)
        if not keys:
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Configuration request must include an update.",
            )
        if any(not isinstance(key, str) for key in keys) or not keys <= _REQUEST_FIELDS:
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Configuration request contains unsupported fields.",
            )
        expected = payload.get("expectedRevision")
        if expected is not None and (
            type(expected) is not int or expected < 1
        ):
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Expected revision must be a positive integer.",
            )
        enabled = payload.get("enabled")
        if "enabled" in payload and type(enabled) is not bool:
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Enabled must be a strict boolean.",
            )
        normalized = {}
        try:
            for external, internal in _CONFIG_FIELDS.items():
                if external in payload:
                    normalized[internal] = _strict_decimal(
                        external, payload[external]
                    )
        except ValueError:
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Configuration percentage is invalid.",
            )
        base_update = None
        if _BASE_CONFIG_FIELD in payload:
            try:
                base_update = _strict_decimal(
                    _BASE_CONFIG_FIELD,
                    payload[_BASE_CONFIG_FIELD],
                )
            except ValueError:
                self._error(
                    422,
                    "CONFIGURATION_INVALID",
                    "Configuration percentage is invalid.",
                )
        return (
            expected,
            enabled if "enabled" in payload else None,
            normalized,
            base_update,
        )

    def _set_application_enabled(self, enabled):
        state = getattr(self._app, "state", None)
        if state is None:
            return False
        if enabled:
            if self._base_registration is None:
                return False
            setattr(state, "money_management", self._base_registration)
            return True
        current = getattr(state, "money_management", None)
        source = (
            current
            if isinstance(current, MoneyManagementApplicationRegistration)
            else self._base_registration
        )
        if source is None:
            return False
        disabled = MoneyManagementApplicationRegistration(
            CompositionReadinessStatus.DISABLED,
            source.lifecycle_adapter,
            source.startup_status,
            source.shutdown_status,
            MoneyManagementSafeApplicationStatus(
                False,
                CompositionReadinessStatus.DISABLED,
                None,
                False,
                None,
                False,
                False,
                False,
                None,
                None,
                None,
            ),
            source.base_config_provider,
        )
        setattr(state, "money_management", disabled)
        return True

    def _reevaluate(self, token, now):
        dispatcher = self._dispatcher
        hook_registration = self._hook_registration()
        if dispatcher is None or hook_registration is None:
            return None
        request = LossRuntimeMetricsReadRequest(
            "money-management-http",
            now,
            self._maximum_metrics_age,
        )
        result = dispatcher.reevaluate(
            self._app,
            request,
            LossRuntimeEventType.BALANCE_UPDATE,
            token,
        )
        if isinstance(result, LossRuntimeDispatchResult):
            hook_registration.hook.record_evaluation_status(result.status)
        projected = dispatch_money_management_governance_projection(
            self._app,
            self._projection_dispatcher,
        )
        return result, projected

    def update_configuration(self, payload):
        (
            expected,
            enabled_update,
            normalized,
            base_update,
        ) = self._normalize_update(payload)
        now = self._now()
        with self._lock:
            if (
                expected is not None
                and expected != self._configuration_revision
            ):
                self._error(
                    409,
                    "CONFIGURATION_REVISION_CONFLICT",
                    "Configuration revision does not match.",
                    True,
                )
            if self._recovery_in_progress:
                self._error(
                    409,
                    "RECOVERY_ALREADY_RUNNING",
                    "Recovery is already running.",
                    True,
                )
            if self._dispatcher is None:
                self._error(
                    503,
                    "MONEY_MANAGEMENT_UNAVAILABLE",
                    "Money Management runtime is unavailable.",
                    True,
                )
            target_enabled = (
                self._enabled if enabled_update is None else enabled_update
            )
            if target_enabled and self._base_registration is None:
                self._error(
                    503,
                    "MONEY_MANAGEMENT_NOT_REGISTERED",
                    "Money Management is not registered.",
                    True,
                )
            values = {
                "daily_warning_pct": self._configuration.daily_warning_pct,
                "daily_block_pct": self._configuration.daily_block_pct,
                "weekly_warning_pct": self._configuration.weekly_warning_pct,
                "weekly_block_pct": self._configuration.weekly_block_pct,
                "monthly_warning_pct": self._configuration.monthly_warning_pct,
                "monthly_block_pct": self._configuration.monthly_block_pct,
                "maximum_drawdown_pct":
                    self._configuration.maximum_drawdown_pct,
            }
            values.update(normalized)
            try:
                candidate = LossLimitConfig(**values)
            except (TypeError, ValueError):
                self._error(
                    422,
                    "CONFIGURATION_INVALID",
                    "Configuration thresholds are inconsistent.",
                )
            current_base_config = (
                self._base_config_provider.get_config()
                if self._base_config_provider is not None
                else None
            )
            if base_update is not None and current_base_config is None:
                self._error(
                    503,
                    "MONEY_MANAGEMENT_NOT_REGISTERED",
                    "Money Management base configuration is unavailable.",
                    True,
                )
            try:
                base_candidate = (
                    replace(
                        current_base_config,
                        total_exposure_pct=base_update,
                    )
                    if base_update is not None
                    else current_base_config
                )
            except (TypeError, ValueError):
                self._error(
                    422,
                    "CONFIGURATION_INVALID",
                    "Base configuration is inconsistent.",
                )
            if (
                candidate == self._configuration
                and target_enabled == self._enabled
                and base_candidate == current_base_config
            ):
                status = self.get_status()
                return MoneyManagementConfigurationUpdateResponse(
                    False,
                    False,
                    "CONFIGURATION_UNCHANGED",
                    status.configuration,
                    status,
                )
            hook_registration = self._hook_registration()
            if hook_registration is not None:
                hook_registration.hook.invalidate_evaluation()
            self._dispatcher.replace_configuration(candidate)
            if not self._set_application_enabled(target_enabled):
                self._dispatcher.replace_configuration(self._configuration)
                self._error(
                    503,
                    "MONEY_MANAGEMENT_NOT_REGISTERED",
                    "Money Management registration is unavailable.",
                    True,
                )
            self._configuration = candidate
            if (
                base_update is not None
                and self._base_config_provider is not None
            ):
                self._base_config_provider.update_total_exposure_pct(
                    base_update
                )
            self._enabled = target_enabled
            self._configuration_revision += 1
            revision = self._configuration_revision
            self._configuration_source = "RUNTIME_OVERRIDE"
            self._configuration_updated_at = now
        reevaluation = (
            self._reevaluate(f"configuration-{revision}", now)
            if target_enabled
            else None
        )
        reevaluated = bool(
            reevaluation is not None
            and reevaluation[0].status
            in (
                LossRuntimeDispatchStatus.APPLIED,
                LossRuntimeDispatchStatus.IDEMPOTENT,
            )
        )
        status = self.get_status()
        return MoneyManagementConfigurationUpdateResponse(
            True,
            reevaluated,
            "CONFIGURATION_APPLIED"
            if reevaluated or not target_enabled
            else "CONFIGURATION_APPLIED_REEVALUATION_PENDING",
            status.configuration,
            status,
        )

    def recover(self):
        now = self._now()
        previous = self.get_status()
        with self._lock:
            if self._recovery_in_progress:
                self._error(
                    409,
                    "RECOVERY_ALREADY_RUNNING",
                    "Recovery is already running.",
                    True,
                )
            self._recovery_in_progress = True
            enabled = self._enabled
            revision = self._configuration_revision
        try:
            if not enabled:
                return MoneyManagementRecoveryResponse(
                    True,
                    False,
                    previous.risk_state,
                    previous.risk_state,
                    previous.recommended_action,
                    False,
                    "MONEY_MANAGEMENT_DISABLED",
                    now,
                    previous.revision,
                    previous.sequence,
                )
            dispatcher = self._dispatcher
            hook_registration = self._hook_registration()
            if dispatcher is None or hook_registration is None:
                return MoneyManagementRecoveryResponse(
                    False,
                    False,
                    previous.risk_state,
                    "UNKNOWN",
                    "UNKNOWN",
                    False,
                    "MONEY_MANAGEMENT_NOT_REGISTERED",
                    now,
                    previous.revision,
                    previous.sequence,
                )
            metrics_result = dispatcher.get_last_metrics_result()
            metrics = (
                metrics_result.metrics
                if isinstance(metrics_result, LossRuntimeMetricsReadResult)
                else None
            )
            complete = bool(
                isinstance(metrics, LossRuntimeMetrics)
                and metrics_result.status
                is LossRuntimeMetricsReadStatus.AVAILABLE
                and metrics.data_quality is LossRuntimeDataQuality.COMPLETE
                and metrics.captured_at <= now
                and now - metrics.captured_at <= self._maximum_metrics_age
            )
            if not complete:
                return MoneyManagementRecoveryResponse(
                    True,
                    False,
                    previous.risk_state,
                    "UNKNOWN",
                    "UNKNOWN",
                    False,
                    "AUTHORITATIVE_METRICS_INCOMPLETE",
                    now,
                    previous.revision,
                    previous.sequence,
                )
            if previous.available and previous.execution_entry_allowed:
                return MoneyManagementRecoveryResponse(
                    True,
                    True,
                    previous.risk_state,
                    previous.risk_state,
                    previous.recommended_action,
                    True,
                    "ALREADY_EVALUATED",
                    previous.generated_at,
                    previous.revision,
                    previous.sequence,
                )
            hook_registration.hook.invalidate_evaluation()
            source_revision = str(metrics.source_revision).replace(":", "-")
            reevaluation = self._reevaluate(
                f"recovery-{revision}-{source_revision}",
                now,
            )
            current = self.get_status()
            succeeded = bool(
                reevaluation is not None
                and reevaluation[0].status
                in (
                    LossRuntimeDispatchStatus.APPLIED,
                    LossRuntimeDispatchStatus.IDEMPOTENT,
                )
            )
            recovered = bool(
                succeeded and current.execution_entry_allowed
            )
            return MoneyManagementRecoveryResponse(
                True,
                recovered,
                previous.risk_state,
                current.risk_state,
                current.recommended_action,
                current.execution_entry_allowed,
                "RECOVERY_COMPLETED"
                if recovered
                else "RECOVERY_NOT_COMPLETED",
                current.generated_at,
                current.revision,
                current.sequence,
            )
        finally:
            with self._lock:
                self._recovery_in_progress = False


def register_money_management_http_boundary(
    app,
    timestamp_source=None,
):
    state = getattr(app, "state", None)
    if state is None:
        return None
    existing = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    if isinstance(existing, MoneyManagementHttpBoundary):
        return existing
    hook_registration = getattr(
        state, RUNTIME_HOOK_STATE_ATTRIBUTE, None
    )
    dispatcher = (
        hook_registration.hook.dispatcher
        if isinstance(
            hook_registration, MoneyManagementRuntimeHookRegistration
        )
        else None
    )
    try:
        boundary = MoneyManagementHttpBoundary(
            app,
            dispatcher,
            timestamp_source=timestamp_source,
        )
    except Exception:
        return None
    setattr(state, APPLICATION_STATE_ATTRIBUTE, boundary)
    return boundary


def unregister_money_management_http_boundary(app):
    state = getattr(app, "state", None)
    if state is None:
        return False
    existing = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    if not isinstance(existing, MoneyManagementHttpBoundary):
        return False
    setattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    return True
