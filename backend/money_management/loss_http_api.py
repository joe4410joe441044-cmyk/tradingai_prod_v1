"""MM-5A3 safe HTTP-facing status, configuration, and recovery boundary."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from threading import RLock
from typing import Optional, Tuple
from pathlib import Path

from .enums import RiskState
from .loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
)
from .loss_application_registration import (
    get_money_management_cash_flow_status,
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
from .loss_accounting_rebase import (
    AccountingRebaseAuthorization,
    AccountingRebaseStatus,
    build_accounting_rebase_update,
)
from .loss_persistence_models import (
    AccountingRebaseAuthoritySource,
    AccountingRebaseAuthorizationState,
    AccountingRebaseReason,
)
from .enums import TradingMode
from .loss_runtime_update_dispatcher import (
    LossRuntimeDispatchResult,
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)
from .position_risk import (
    PositionSizingInput,
    calculate_position_size,
    calculate_risk_budget,
)
from .capital_eligibility import (
    CapitalEligibilityContract,
    build_capital_eligibility_contract,
)
from .simulation import (
    MAX_SIMULATION_TRADES,
    MoneyManagementSimulationInput,
    SimulationScenario,
    run_simulation,
)
from .timeline import (
    MoneyManagementHistoryResult,
    MoneyManagementTimelineRecorder,
    MoneyManagementTimelineStore,
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
    total_exposure_percent: Optional[Decimal]
    max_total_exposure_amount: Optional[Decimal]
    remaining_exposure_amount: Optional[Decimal]
    exposure_utilization: Optional[Decimal]
    open_position_state: str
    risk_utilization: Optional[Decimal]
    risk_limit_amount: Optional[Decimal]
    current_risk_amount: Optional[Decimal]
    reserved_risk_amount: Optional[Decimal]
    risk_budget_remaining: Optional[Decimal]
    recommended_position_notional: Optional[Decimal]
    recommended_position_quantity: Optional[Decimal]
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
            "totalExposurePercent": _serialize(self.total_exposure_percent),
            "maxTotalExposureAmount": _serialize(self.max_total_exposure_amount),
            "remainingExposureAmount": _serialize(self.remaining_exposure_amount),
            "exposureUtilization": _serialize(self.exposure_utilization),
            "openPositionState": self.open_position_state,
            "riskUtilization": _serialize(self.risk_utilization),
            "riskLimitAmount": _serialize(self.risk_limit_amount),
            "currentRiskAmount": _serialize(self.current_risk_amount),
            "reservedRiskAmount": _serialize(self.reserved_risk_amount),
            "riskBudgetRemaining": _serialize(self.risk_budget_remaining),
            "recommendedPositionNotional": _serialize(
                self.recommended_position_notional
            ),
            "recommendedPositionQuantity": _serialize(
                self.recommended_position_quantity
            ),
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
    risk_per_trade_percent: Optional[Decimal]
    maximum_position_notional: Optional[Decimal]
    single_symbol_exposure_percent: Optional[Decimal]
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
            "riskPerTradePercent": _serialize(
                self.risk_per_trade_percent
            ),
            "maximumPositionNotional": _serialize(
                self.maximum_position_notional
            ),
            "singleSymbolExposurePercent": _serialize(
                self.single_symbol_exposure_percent
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
    capital_eligibility: object
    cash_flow_authority: object
    capital_authority_status: str = "UNAVAILABLE"
    runtime_trading_metrics_status: str = "UNAVAILABLE"

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
            "capitalAuthorityStatus": self.capital_authority_status,
            "runtimeTradingMetricsStatus": self.runtime_trading_metrics_status,
            "safeReason": self.safe_reason,
            "generatedAt": _serialize(self.generated_at),
            "revision": self.revision,
            "sequence": self.sequence,
            "configurationRevision": self.configuration_revision,
            "metrics": self.metrics.to_dict(),
            "configuration": self.configuration.to_dict(),
            "capitalEligibility": self.capital_eligibility.to_dict(),
            "cashFlowAuthority": self.cash_flow_authority,
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
_BASE_CONFIG_FIELDS = {
    "totalExposurePercent": "total_exposure_pct",
    "riskPerTradePercent": "risk_per_trade_pct",
    "maximumPositionNotional": "maximum_position_notional",
    "singleSymbolExposurePercent": "single_symbol_exposure_pct",
}
_REQUEST_FIELDS = frozenset((
    *_CONFIG_FIELDS,
    *_BASE_CONFIG_FIELDS,
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


def _strict_positive_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError(f"{name} must be a decimal string")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a valid decimal") from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _strict_nonnegative_percentage(name, value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError(f"{name} must be a decimal string")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a valid decimal") from None
    if not result.is_finite() or result < 0 or result > Decimal("100"):
        raise ValueError(f"{name} must be between 0 and 100")
    return result


class MoneyManagementHttpBoundary:
    """Application-scoped HTTP service with no network or filesystem access."""

    def __init__(
        self,
        app,
        dispatcher=None,
        timestamp_source=None,
        maximum_metrics_age=DEFAULT_MAXIMUM_METRICS_AGE,
        timeline_recorder=None,
        capital_authority_provider=None,
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
        if timeline_recorder is not None and not isinstance(
            timeline_recorder, MoneyManagementTimelineRecorder
        ):
            raise TypeError("timeline recorder invalid")
        self._timeline_recorder = timeline_recorder
        if capital_authority_provider is not None and not callable(
            capital_authority_provider
        ):
            raise TypeError("capital authority provider must be callable")
        self._capital_authority_provider = capital_authority_provider
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

    def get_history(self, **query):
        if self._timeline_recorder is None:
            return MoneyManagementHistoryResult((), False, None)
        try:
            return self._timeline_recorder.store.query(**query)
        except (TypeError, ValueError):
            self._error(
                422,
                "HISTORY_QUERY_INVALID",
                "History query is invalid.",
            )

    @property
    def configuration_revision(self):
        with self._lock:
            return self._configuration_revision

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
            base_config.risk_per_trade_pct
            if base_config is not None
            else None,
            base_config.maximum_position_notional
            if base_config is not None
            else None,
            base_config.single_symbol_exposure_pct
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

    def preview_position_size(self, payload):
        if not isinstance(payload, Mapping):
            self._error(
                422,
                "POSITION_SIZE_INPUT_INVALID",
                "Position size request must be a JSON object.",
            )
        allowed = frozenset((
            "entryPrice",
            "stopLossPercent",
            "effectiveCostPercent",
            "riskPercent",
            "quantityStep",
            "contractMultiplier",
            "symbol",
        ))
        if set(payload) - allowed:
            self._error(
                422,
                "POSITION_SIZE_INPUT_INVALID",
                "Position size request contains unsupported fields.",
            )
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            self._error(
                422,
                "POSITION_SIZE_INPUT_INVALID",
                "Symbol is required.",
            )
        try:
            entry_price = _strict_positive_decimal(
                "entryPrice", payload.get("entryPrice")
            )
            stop_loss = _strict_decimal(
                "stopLossPercent", payload.get("stopLossPercent")
            )
            effective_cost = _strict_positive_decimal(
                "effectiveCostPercent",
                payload.get("effectiveCostPercent"),
            )
            quantity_step = _strict_positive_decimal(
                "quantityStep", payload.get("quantityStep")
            )
            contract_multiplier = _strict_positive_decimal(
                "contractMultiplier", payload.get("contractMultiplier")
            )
        except ValueError:
            self._error(
                422,
                "POSITION_SIZE_INPUT_INVALID",
                "Position size inputs are invalid.",
            )
        config = (
            self._base_config_provider.get_config()
            if self._base_config_provider is not None
            else None
        )
        dispatcher = self._dispatcher
        metrics_result = (
            dispatcher.get_last_metrics_result()
            if dispatcher is not None
            else None
        )
        metrics = (
            metrics_result.metrics
            if isinstance(metrics_result, LossRuntimeMetricsReadResult)
            and isinstance(metrics_result.metrics, LossRuntimeMetrics)
            else None
        )
        if config is None or metrics is None:
            self._error(
                503,
                "POSITION_SIZE_INPUT_INCOMPLETE",
                "Authoritative position size inputs are unavailable.",
                True,
            )
        risk_percent = config.risk_per_trade_pct
        if "riskPercent" in payload:
            try:
                risk_percent = _strict_decimal(
                    "riskPercent", payload["riskPercent"]
                )
            except ValueError:
                self._error(
                    422,
                    "POSITION_SIZE_INPUT_INVALID",
                    "Risk percent is invalid.",
                )
        if risk_percent > config.risk_per_trade_pct:
            self._error(
                422,
                "POSITION_SIZE_INPUT_INVALID",
                "Risk percent exceeds active configuration.",
            )
        capital = metrics.available_balance
        exposure = metrics.open_exposure
        risk_budget = calculate_risk_budget(
            capital,
            config.risk_per_trade_pct,
            Decimal("0") if metrics.position_count == 0 else None,
            Decimal("0") if metrics.pending_order_count == 0 else None,
        )
        if (
            capital is None
            or exposure is None
            or risk_budget.risk_budget_remaining is None
        ):
            self._error(
                503,
                "POSITION_SIZE_INPUT_INCOMPLETE",
                "Authoritative capital or risk budget is unavailable.",
                True,
            )
        total_limit = (
            metrics.equity * config.total_exposure_pct / Decimal("100")
            if metrics.equity is not None
            else None
        )
        if total_limit is None:
            self._error(
                503,
                "POSITION_SIZE_INPUT_INCOMPLETE",
                "Authoritative exposure limit is unavailable.",
                True,
            )
        result = calculate_position_size(PositionSizingInput(
            entry_price=entry_price,
            stop_loss_percent=stop_loss,
            effective_cost_percent=effective_cost,
            risk_percent=risk_percent,
            risk_base_capital=capital,
            maximum_position_notional=config.maximum_position_notional,
            total_exposure_remaining=max(
                total_limit - exposure, Decimal("0")
            ),
            available_capital=capital,
            quantity_step=quantity_step,
            contract_multiplier=contract_multiplier,
            risk_budget_remaining=risk_budget.risk_budget_remaining,
        ))
        return {
            **result.to_dict(),
            "symbol": symbol.strip(),
            "orderCreated": False,
        }

    def simulate(self, payload):
        if not isinstance(payload, Mapping):
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Simulation request must be a JSON object.",
            )
        allowed = frozenset((
            "initialCapital",
            "numberOfTrades",
            "winRatePercent",
            "averageWinPercent",
            "averageLossPercent",
            "riskPerTradePercent",
            "maximumDrawdownPercent",
            "compoundingEnabled",
            "feesPercent",
            "slippagePercent",
            "scenario",
            "customSequence",
        ))
        if set(payload) - allowed:
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Simulation request contains unsupported fields.",
            )
        count = payload.get("numberOfTrades")
        if type(count) is not int or count <= 0:
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Number of trades must be a positive integer.",
            )
        if count > MAX_SIMULATION_TRADES:
            self._error(
                422,
                "SIMULATION_TRADE_LIMIT_EXCEEDED",
                "Simulation trade limit exceeded.",
            )
        compounding = payload.get("compoundingEnabled")
        if type(compounding) is not bool:
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Compounding must be a strict boolean.",
            )
        try:
            decimals = {
                "initial_capital": _strict_positive_decimal(
                    "initialCapital", payload.get("initialCapital")
                ),
                "win_rate_percent": _strict_nonnegative_percentage(
                    "winRatePercent", payload.get("winRatePercent")
                ),
                "average_win_percent": _strict_nonnegative_percentage(
                    "averageWinPercent", payload.get("averageWinPercent")
                ),
                "average_loss_percent": _strict_decimal(
                    "averageLossPercent", payload.get("averageLossPercent")
                ),
                "risk_per_trade_percent": _strict_decimal(
                    "riskPerTradePercent",
                    payload.get("riskPerTradePercent"),
                ),
                "maximum_drawdown_percent": _strict_decimal(
                    "maximumDrawdownPercent",
                    payload.get("maximumDrawdownPercent"),
                ),
                "fees_percent": _strict_nonnegative_percentage(
                    "feesPercent", payload.get("feesPercent")
                ),
                "slippage_percent": _strict_nonnegative_percentage(
                    "slippagePercent", payload.get("slippagePercent")
                ),
            }
            scenario = SimulationScenario(payload.get("scenario"))
        except (TypeError, ValueError):
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Simulation inputs are invalid.",
            )
        config = (
            self._base_config_provider.get_config()
            if self._base_config_provider is not None
            else None
        )
        if config is None:
            self._error(
                503,
                "MONEY_MANAGEMENT_UNAVAILABLE",
                "Money Management configuration is unavailable.",
                True,
            )
        if decimals["risk_per_trade_percent"] > config.risk_per_trade_pct:
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Risk per trade exceeds active configuration.",
            )
        custom = payload.get("customSequence", ())
        if not isinstance(custom, (list, tuple)):
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Custom sequence must be an array.",
            )
        try:
            value = MoneyManagementSimulationInput(
                number_of_trades=count,
                compounding_enabled=compounding,
                maximum_position_notional=config.maximum_position_notional,
                total_exposure_percent=config.total_exposure_pct,
                single_symbol_exposure_percent=(
                    config.single_symbol_exposure_pct
                ),
                scenario=scenario,
                custom_sequence=tuple(custom),
                **decimals,
            )
            result = run_simulation(value)
        except (TypeError, ValueError):
            self._error(
                422,
                "SIMULATION_INPUT_INVALID",
                "Simulation inputs are inconsistent.",
            )
        return {
            **result.to_dict(),
            "runtimeMutated": False,
            "orderCreated": False,
        }

    @staticmethod
    def _metrics_response(
        result, exposure_limit=None, risk_per_trade_percent=None
    ):
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
        exposure_limit_amount = (
            metrics.equity * exposure_limit / Decimal("100")
            if metrics is not None
            and metrics.equity is not None
            and exposure_limit is not None
            else None
        )
        exposure_utilization = (
            metrics.open_exposure / exposure_limit_amount * Decimal("100")
            if metrics is not None
            and metrics.open_exposure is not None
            and exposure_limit_amount is not None
            and exposure_limit_amount > 0
            else None
        )
        open_position_state = (
            "FLAT"
            if metrics is not None and metrics.position_count == 0
            else metrics.position_side
            if metrics is not None
            and metrics.position_count is not None
            and metrics.position_count > 0
            and metrics.position_side in ("LONG", "SHORT", "OPEN")
            else "OPEN"
            if metrics is not None
            and metrics.position_count is not None
            and metrics.position_count > 0
            else "UNKNOWN"
        )
        current_risk = (
            Decimal("0")
            if metrics is not None and metrics.position_count == 0
            else metrics.current_risk_amount
            if metrics is not None
            else None
        )
        reserved_risk = (
            Decimal("0")
            if metrics is not None and metrics.pending_order_count == 0
            else metrics.reserved_risk_amount
            if metrics is not None
            else None
        )
        risk_budget = calculate_risk_budget(
            metrics.available_balance if metrics is not None else None,
            risk_per_trade_percent,
            current_risk,
            reserved_risk,
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
            exposure_limit,
            exposure_limit_amount,
            (
                max(exposure_limit_amount - metrics.open_exposure, Decimal("0"))
                if metrics is not None and metrics.open_exposure is not None
                and exposure_limit_amount is not None else None
            ),
            exposure_utilization,
            open_position_state,
            risk_budget.risk_utilization,
            risk_budget.risk_limit_amount,
            risk_budget.current_risk_amount,
            risk_budget.reserved_risk_amount,
            risk_budget.risk_budget_remaining,
            None,
            None,
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
        cash_flow_authority = get_money_management_cash_flow_status(self._app)
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
        monitoring_capital = None
        if self._capital_authority_provider is not None:
            try:
                candidate = self._capital_authority_provider()
                if isinstance(candidate, CapitalEligibilityContract):
                    monitoring_capital = candidate
            except Exception:
                monitoring_capital = None
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
        runtime_metrics_available = bool(
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
        cash_flow_ready = bool(
            isinstance(cash_flow_authority, dict)
            and cash_flow_authority.get("cashFlowAuthority") == "READY"
            and cash_flow_authority.get("cashFlowFresh") is True
        )
        live_capital_complete = bool(
            isinstance(monitoring_capital, CapitalEligibilityContract)
            and monitoring_capital.capital_authority == "MONEY_MANAGEMENT"
            and monitoring_capital.input_authority == "REAL_LIVE_ACCOUNT"
            and monitoring_capital.authority_fresh
            and monitoring_capital.equity is not None
            and monitoring_capital.available_capital is not None
            and monitoring_capital.risk_budget is not None
            and monitoring_capital.remaining_exposure is not None
            and monitoring_capital.remaining_position_capacity is not None
        )
        live_equity_matches_mm_state = bool(
            live_capital_complete
            and runtime_snapshot is not None
            and runtime_snapshot.state is not None
            and monitoring_capital.equity
            == runtime_snapshot.state.drawdown_state.current_equity
        )
        live_projection_valid = bool(
            projection is not None
            and projection.entry_permission is not LossEntryPermission.UNKNOWN
            and revisions_match
        )
        live_authority_available = bool(
            enabled
            and registration_ready
            and lifecycle_running
            and live_equity_matches_mm_state
            and cash_flow_ready
            and live_projection_valid
            and base_config is not None
        )
        available = bool(runtime_metrics_available or live_authority_available)
        execution_allowed = bool(
            available
            and projection is not None
            and projection.entry_permission is LossEntryPermission.ALLOW
            and projection.new_entry_allowed is True
            and (
                runtime_metrics_available
                or monitoring_capital.execution_entry_allowed is True
            )
        )
        safe_reason = None
        if not enabled:
            safe_reason = "MONEY_MANAGEMENT_DISABLED"
        elif not registration_ready:
            safe_reason = "MONEY_MANAGEMENT_NOT_REGISTERED"
        elif not lifecycle_running:
            safe_reason = "MONEY_MANAGEMENT_UNAVAILABLE"
        elif not hook_healthy and not live_capital_complete:
            safe_reason = "AUTHORITATIVE_METRICS_INCOMPLETE"
        elif not metrics_fresh and not live_capital_complete:
            safe_reason = "AUTHORITATIVE_METRICS_INCOMPLETE"
        elif live_capital_complete and not cash_flow_ready:
            safe_reason = "CASH_FLOW_AUTHORITY_UNAVAILABLE"
        elif live_capital_complete and not live_equity_matches_mm_state:
            safe_reason = "LIVE_MM_EQUITY_NOT_RECONCILED"
        elif live_capital_complete and not live_projection_valid:
            safe_reason = "INTERNAL_STATE_UNAVAILABLE"
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
        metrics_response = self._metrics_response(
            metrics_result,
            base_config.total_exposure_pct
            if base_config is not None
            else None,
            base_config.risk_per_trade_pct
            if base_config is not None
            else None,
        )
        if metrics_response.exposure_utilization is None:
            diagnostics.append("EXPOSURE_METRICS_INCOMPLETE")
        if metrics_response.open_position_state == "UNKNOWN":
            diagnostics.append("POSITION_STATE_UNAVAILABLE")
        risk_budget = calculate_risk_budget(
            metrics.available_balance
            if isinstance(metrics, LossRuntimeMetrics)
            else None,
            base_config.risk_per_trade_pct
            if base_config is not None
            else None,
            Decimal("0")
            if isinstance(metrics, LossRuntimeMetrics)
            and metrics.position_count == 0
            else None,
            Decimal("0")
            if isinstance(metrics, LossRuntimeMetrics)
            and metrics.pending_order_count == 0
            else None,
        )
        diagnostics.extend(
            reason for reason in risk_budget.diagnostics
            if reason not in diagnostics
        )
        diagnostics.append("POSITION_SIZE_INPUT_INCOMPLETE")
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
        runtime_capital = build_capital_eligibility_contract(
            equity=metrics.equity if isinstance(metrics, LossRuntimeMetrics) else None,
            available_capital=(
                metrics.available_balance if isinstance(metrics, LossRuntimeMetrics) else None
            ),
            risk_budget=risk_budget.risk_budget_remaining,
            max_position_notional=(
                base_config.maximum_position_notional if base_config is not None else None
            ),
            total_exposure_percent=(
                base_config.total_exposure_pct if base_config is not None else None
            ),
            open_exposure=(
                metrics.open_exposure if isinstance(metrics, LossRuntimeMetrics) else None
            ),
            position_count=(
                metrics.position_count if isinstance(metrics, LossRuntimeMetrics) else None
            ),
            pending_order_count=(
                metrics.pending_order_count if isinstance(metrics, LossRuntimeMetrics) else None
            ),
            mm_regime=risk_state,
            policy_version=f"{HTTP_BOUNDARY_SCHEMA_VERSION}:{config_revision}",
            evaluated_at=generated_at,
            authority_fresh=bool(metrics_fresh and projection_fresh and revisions_match),
            execution_entry_allowed=execution_allowed,
        )
        capital = monitoring_capital or runtime_capital
        capital_authority_available = bool(
            capital.authority_fresh
            and capital.equity is not None
            and capital.available_capital is not None
            and capital.risk_budget is not None
            and capital.remaining_exposure is not None
            and capital.remaining_position_capacity is not None
        )
        if capital_authority_available and not available:
            blocks = [item for item in blocks if item != "UNKNOWN_STATE"]
            blocks.append("TRADING_RUNTIME_METRICS_UNAVAILABLE")
        recovery_required = bool(
            projection is not None and projection.recovery_required
        )
        if (
            capital_authority_available
            and not available
            and not isinstance(metrics_result, LossRuntimeMetricsReadResult)
        ):
            recovery_required = False
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
            (
                LossRuntimeMetricsReadStatus.AVAILABLE.value
                if live_authority_available
                else metrics_result.status.value
                if isinstance(metrics_result, LossRuntimeMetricsReadResult)
                else LossRuntimeMetricsReadStatus.UNAVAILABLE.value
            ),
            projection.entry_permission.value
            if projection is not None
            else LossEntryPermission.UNKNOWN.value,
            recovery_required,
            safe_reason,
            generated_at,
            public.revision
            if isinstance(public, LossGovernancePublicSnapshot)
            else None,
            public.sequence
            if isinstance(public, LossGovernancePublicSnapshot)
            else None,
            config_revision,
            metrics_response,
            configuration,
            capital,
            cash_flow_authority,
            "AVAILABLE" if capital_authority_available else "UNAVAILABLE",
            metrics_result.status.value
            if isinstance(metrics_result, LossRuntimeMetricsReadResult)
            else LossRuntimeMetricsReadStatus.UNAVAILABLE.value,
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
        base_update = {}
        try:
            for external, internal in _BASE_CONFIG_FIELDS.items():
                if external in payload:
                    parser = (
                        _strict_positive_decimal
                        if external == "maximumPositionNotional"
                        else _strict_decimal
                    )
                    base_update[internal] = parser(
                        external, payload[external]
                    )
        except ValueError:
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Base configuration value is invalid.",
            )
        if base_update.get("risk_per_trade_pct", Decimal("0")) > Decimal("1"):
            self._error(
                422,
                "CONFIGURATION_INVALID",
                "Risk per trade must not exceed 1 percent.",
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
            previous_configuration = self._configuration
            if base_update and current_base_config is None:
                self._error(
                    503,
                    "MONEY_MANAGEMENT_NOT_REGISTERED",
                    "Money Management base configuration is unavailable.",
                    True,
                )
            try:
                base_candidate = (
                    replace(current_base_config, **base_update)
                    if base_update
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
                base_update
                and self._base_config_provider is not None
            ):
                self._base_config_provider.replace_config(base_candidate)
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
        if self._timeline_recorder is not None:
            try:
                self._timeline_recorder.record_configuration(
                    before=previous_configuration,
                    after=candidate,
                    base_before=current_base_config,
                    base_after=base_candidate,
                    version=revision,
                    correlation_id=f"configuration-{revision}",
                )
            except Exception:
                pass
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
            if (
                self._timeline_recorder is not None
                and previous.risk_state != current.risk_state
            ):
                try:
                    self._timeline_recorder.record_recovery(
                        previous_state=previous.risk_state,
                        current_state=current.risk_state,
                        version=current.configuration_revision,
                        correlation_id=f"recovery-{revision}",
                    )
                except Exception:
                    pass
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

    def rebase_accounting(self, payload):
        """Execute an explicitly authorized PAPER accounting rebase."""
        now = self._now()
        if not isinstance(payload, Mapping):
            self._error(422, "ACCOUNTING_REBASE_INVALID", "Accounting rebase request must be a JSON object.")
        allowed = {"rebaseId", "accountScope", "runtimeInstanceId", "authoritySource", "reason", "authorizationState"}
        if set(payload) != allowed:
            self._error(422, "ACCOUNTING_REBASE_INVALID", "Explicit accounting rebase authorization is incomplete.")
        try:
            authorization = AccountingRebaseAuthorization(
                payload["rebaseId"], payload["accountScope"], payload["runtimeInstanceId"],
                AccountingRebaseAuthoritySource(payload["authoritySource"]),
                AccountingRebaseReason(payload["reason"]),
                AccountingRebaseAuthorizationState(payload["authorizationState"]),
            )
        except (KeyError, TypeError, ValueError):
            self._error(422, "ACCOUNTING_REBASE_INVALID", "Explicit accounting rebase authorization is invalid.")
        dispatcher = self._dispatcher
        registration = self._base_registration
        lifecycle = registration.lifecycle_adapter if registration is not None else None
        metrics_result = dispatcher.get_last_metrics_result() if dispatcher is not None else None
        metrics = metrics_result.metrics if isinstance(metrics_result, LossRuntimeMetricsReadResult) else None
        snapshot = lifecycle.get_snapshot() if lifecycle is not None else None
        base_config = self._base_config_provider.get_config() if self._base_config_provider is not None else None
        mode = base_config.mode if base_config is not None else TradingMode.LIVE
        result = build_accounting_rebase_update(
            authorization, metrics, snapshot, now,
            self._maximum_metrics_age, mode,
        )
        if result.status is AccountingRebaseStatus.REJECTED:
            return {"accepted": False, "persisted": False, "status": "REBASE_REJECTED", "safeReasons": list(result.safe_reasons), "revision": snapshot.revision if snapshot else None, "sequence": snapshot.sequence if snapshot else None}
        if result.status is AccountingRebaseStatus.IDEMPOTENT:
            return {"accepted": True, "persisted": True, "status": "IDEMPOTENT", "rebase": result.record.to_dict(), "revision": snapshot.revision, "sequence": snapshot.sequence}
        hook_registration = self._hook_registration()
        if hook_registration is not None:
            # Admission remains UNKNOWN until the mandatory checkpoint and a
            # subsequent real dispatcher evaluation both succeed.
            hook_registration.hook.invalidate_evaluation()
        lifecycle_result = lifecycle.apply_update(result.update)
        coordination = lifecycle_result.coordination_result
        persisted = bool(coordination is not None and coordination.checkpoint_succeeded and not coordination.durability_pending)
        if not persisted:
            return {"accepted": False, "persisted": False, "status": "REBASE_PERSISTENCE_FAILED", "safeReasons": ["accounting rebase persistence failed"], "revision": None, "sequence": None}
        dispatch, _ = self._reevaluate(f"accounting-rebase-{authorization.rebase_id}", now)
        return {
            "accepted": True, "persisted": True, "status": "REBASE_ACCEPTED",
            "rebase": result.record.to_dict(), "dispatchStatus": dispatch.status.value,
            "revision": dispatch.runtime_revision, "sequence": dispatch.runtime_sequence,
            "newEntryAllowed": dispatch.new_entry_allowed,
        }


def register_money_management_http_boundary(
    app,
    timestamp_source=None,
    timeline_directory=None,
    capital_authority_provider=None,
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
        timeline_directory = timeline_directory or (
            Path(__file__).resolve().parents[2] / "logs" / "runtime"
        )
        timeline_store = MoneyManagementTimelineStore(timeline_directory)
        timeline_recorder = MoneyManagementTimelineRecorder(
            timeline_store,
            timestamp_source=timestamp_source,
        )
        boundary = MoneyManagementHttpBoundary(
            app,
            dispatcher,
            timestamp_source=timestamp_source,
            timeline_recorder=timeline_recorder,
            capital_authority_provider=capital_authority_provider,
        )
        # Publish the existing official lifecycle snapshot at registration;
        # startup health must not wait for an unrelated bot-runtime event.
        dispatch_money_management_governance_projection(
            app, boundary._projection_dispatcher,
        )
        lifecycle_state = getattr(
            getattr(
                getattr(state, "money_management", None),
                "safe_status",
                None,
            ),
            "lifecycle_state",
            None,
        )
        timeline_recorder.record_started(
            lifecycle_state.value
            if lifecycle_state is not None
            else "UNAVAILABLE"
        )
        if isinstance(
            hook_registration, MoneyManagementRuntimeHookRegistration
        ):
            hook_registration.hook.attach_timeline_recorder(
                timeline_recorder,
                lambda: boundary.configuration_revision,
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
