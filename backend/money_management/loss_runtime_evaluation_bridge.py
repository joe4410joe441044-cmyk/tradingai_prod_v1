"""MM-4I bridge from normalized runtime metrics to existing loss evaluation."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from threading import RLock
from typing import Optional, Tuple

from .enums import RiskState
from .loss_decision import evaluate_loss_decision
from .loss_models import (
    CashFlowAdjustmentState,
    LossLimitConfig,
    MoneyManagementLossDecisionInput,
)
from .loss_persistence_models import (
    FreshnessStatus,
    PERSISTENCE_SCHEMA_VERSION,
    PeriodCode,
    PersistedDrawdownState,
    PersistedLossPeriodState,
    PersistedLossState,
)
from .loss_reason_models import RecommendedAction, build_reason_contract
from .loss_runtime_event_models import LossRuntimeUpdateBuildContext
from .loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    SaveTrigger,
)
from .loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetrics,
)
from .loss_runtime_store_models import LossLimitRuntimeSnapshot
from .period_aggregation import period_for
from .period_models import (
    PERIOD_SCHEMA_VERSION,
    MoneyManagementEquitySnapshot,
    MoneyManagementPeriodAggregate,
    EquitySource,
    PeriodType,
)


class LossRuntimeEvaluationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class LossRuntimeEvaluationResult:
    status: LossRuntimeEvaluationStatus
    build_context: Optional[LossRuntimeUpdateBuildContext]
    safe_reasons: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(
            self, "status", LossRuntimeEvaluationStatus(self.status)
        )
        if self.build_context is not None and not isinstance(
            self.build_context, LossRuntimeUpdateBuildContext
        ):
            raise TypeError("build context invalid")
        object.__setattr__(
            self, "safe_reasons", tuple(str(item) for item in self.safe_reasons)
        )
        if (
            self.status is LossRuntimeEvaluationStatus.SUCCEEDED
        ) != (self.build_context is not None):
            raise ValueError("evaluation result context mismatch")


def _failure(status, reason):
    return LossRuntimeEvaluationResult(status, None, (reason,))


def _aggregate(metrics, period_type, sequence):
    pnl = {
        PeriodType.DAILY: metrics.daily_pnl,
        PeriodType.WEEKLY: metrics.weekly_pnl,
        PeriodType.MONTHLY: metrics.monthly_pnl,
    }[period_type]
    period = period_for(metrics.captured_at, period_type)
    event_id = f"runtime-metrics-{sequence}-{period_type.value}"
    return MoneyManagementPeriodAggregate(
        PERIOD_SCHEMA_VERSION,
        period,
        "USDT",
        1,
        pnl,
        Decimal("0"),
        Decimal("0"),
        pnl,
        max(Decimal("0"), pnl),
        max(Decimal("0"), -pnl),
        1 if pnl > 0 else 0,
        1 if pnl < 0 else 0,
        metrics.captured_at,
        metrics.captured_at,
        sequence,
        (event_id,),
        metrics.captured_at,
    )


def _period_state(code, aggregate, starting_equity, cash_flow_amount, captured_at):
    pnl = aggregate.net_realized_pnl
    loss = max(Decimal("0"), -pnl)
    return PersistedLossPeriodState(
        code,
        aggregate.period.period_key,
        aggregate.period.start_at,
        aggregate.period.end_at,
        starting_equity,
        pnl,
        loss,
        loss / starting_equity * Decimal("100"),
        cash_flow_amount,
        captured_at,
    )


def _governance(reason_contract):
    if reason_contract.recommended_action is RecommendedAction.BLOCK_EXECUTION:
        return GovernanceProjection.BLOCK_EXECUTION
    if reason_contract.recommended_action is RecommendedAction.HOLD_NEW_ENTRIES:
        return GovernanceProjection.HOLD_NEW_ENTRIES
    return GovernanceProjection.CONTINUE


def _cash_flow_adjustment(state):
    if not state.has_unresolved_cash_flow:
        return CashFlowAdjustmentState.NONE
    if not state.cash_flow_types:
        return CashFlowAdjustmentState.UNKNOWN
    return CashFlowAdjustmentState(state.cash_flow_types[0].value)


def _periods_match(current, daily, weekly, monthly):
    return (
        current.daily_state.period_id == daily.period.period_key
        and current.weekly_state.period_id == weekly.period.period_key
        and current.monthly_state.period_id == monthly.period.period_key
    )


def _save_triggers(previous, next_state):
    triggers = []
    if previous.risk_state is not next_state.risk_state:
        triggers.append(SaveTrigger.STATE_TRANSITION)
    if previous.last_decision.to_dict() != next_state.last_decision.to_dict():
        triggers.append(SaveTrigger.REASON_CHANGED)
    previous_metrics = (
        previous.daily_state.net_realized_pnl,
        previous.weekly_state.net_realized_pnl,
        previous.monthly_state.net_realized_pnl,
        previous.drawdown_state.current_equity,
        previous.drawdown_state.high_water_mark,
    )
    next_metrics = (
        next_state.daily_state.net_realized_pnl,
        next_state.weekly_state.net_realized_pnl,
        next_state.monthly_state.net_realized_pnl,
        next_state.drawdown_state.current_equity,
        next_state.drawdown_state.high_water_mark,
    )
    if previous_metrics != next_metrics:
        triggers.append(SaveTrigger.METRIC_CHANGED)
    if next_state.risk_state is RiskState.LOCKED:
        triggers.append(SaveTrigger.LOCKED)
    return tuple(triggers)


class LossRuntimeEvaluationBridge:
    """Calls existing domain evaluation and reason-building services."""

    def __init__(
        self,
        config=None,
        domain_evaluator=evaluate_loss_decision,
        reason_builder=build_reason_contract,
    ):
        self._config = config or LossLimitConfig()
        if not isinstance(self._config, LossLimitConfig):
            raise TypeError("loss limit config required")
        if not callable(domain_evaluator) or not callable(reason_builder):
            raise TypeError("domain services required")
        self._domain_evaluator = domain_evaluator
        self._reason_builder = reason_builder
        self._lock = RLock()

    def get_configuration(self):
        with self._lock:
            return self._config

    def replace_configuration(self, config):
        if not isinstance(config, LossLimitConfig):
            raise TypeError("loss limit config required")
        with self._lock:
            previous = self._config
            self._config = config
            return previous

    def evaluate(self, metrics, runtime_snapshot, event_id):
        if (
            not isinstance(metrics, LossRuntimeMetrics)
            or metrics.data_quality is not LossRuntimeDataQuality.COMPLETE
            or not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot)
            or not isinstance(event_id, str)
            or not event_id
        ):
            return _failure(
                LossRuntimeEvaluationStatus.FAILED,
                "runtime evaluation input invalid",
            )
        previous = runtime_snapshot.state
        if not isinstance(previous, PersistedLossState):
            return _failure(
                LossRuntimeEvaluationStatus.RECOVERY_REQUIRED,
                "loss runtime state unavailable",
            )
        with self._lock:
            config = self._config
        try:
            sequence = runtime_snapshot.sequence + 1
            daily = _aggregate(metrics, PeriodType.DAILY, sequence)
            weekly = _aggregate(metrics, PeriodType.WEEKLY, sequence)
            monthly = _aggregate(metrics, PeriodType.MONTHLY, sequence)
            if not _periods_match(previous, daily, weekly, monthly):
                return _failure(
                    LossRuntimeEvaluationStatus.RECOVERY_REQUIRED,
                    "period rollover requires authoritative starting equity",
                )
            if metrics.peak_equity <= 0:
                return _failure(
                    LossRuntimeEvaluationStatus.RECOVERY_REQUIRED,
                    "peak equity unavailable for persisted state",
                )
            equity_snapshot = MoneyManagementEquitySnapshot(
                PERIOD_SCHEMA_VERSION,
                metrics.captured_at,
                "USDT",
                previous.daily_state.starting_equity,
                metrics.equity,
                metrics.peak_equity,
                metrics.peak_equity - metrics.equity,
                metrics.drawdown,
                EquitySource.NORMALIZED_EQUITY,
            )
            decision_input = MoneyManagementLossDecisionInput(
                PERIOD_SCHEMA_VERSION,
                metrics.captured_at,
                "USDT",
                daily,
                weekly,
                monthly,
                previous.daily_state.starting_equity,
                previous.weekly_state.starting_equity,
                previous.monthly_state.starting_equity,
                equity_snapshot,
                config,
                _cash_flow_adjustment(previous.cash_flow_state),
            )
            decision = self._domain_evaluator(decision_input)
            reason = self._reason_builder(decision)
            next_state = PersistedLossState(
                PERSISTENCE_SCHEMA_VERSION,
                previous.account_scope,
                previous.valuation_currency,
                _period_state(
                    PeriodCode.DAILY,
                    daily,
                    previous.daily_state.starting_equity,
                    previous.daily_state.cash_flow_amount,
                    metrics.captured_at,
                ),
                _period_state(
                    PeriodCode.WEEKLY,
                    weekly,
                    previous.weekly_state.starting_equity,
                    previous.weekly_state.cash_flow_amount,
                    metrics.captured_at,
                ),
                _period_state(
                    PeriodCode.MONTHLY,
                    monthly,
                    previous.monthly_state.starting_equity,
                    previous.monthly_state.cash_flow_amount,
                    metrics.captured_at,
                ),
                PersistedDrawdownState(
                    metrics.peak_equity,
                    metrics.equity,
                    metrics.peak_equity - metrics.equity,
                    metrics.drawdown,
                    metrics.captured_at,
                ),
                previous.cash_flow_state,
                reason,
                metrics.captured_at,
                freshness=FreshnessStatus.VALID,
            )
            governance = _governance(reason)
            recovery = LossLimitRecoveryRequirement(
                False,
                (),
                False,
                False,
                False,
                "recovery not required",
            )
            context = LossRuntimeUpdateBuildContext(
                event_id,
                next_state,
                governance,
                recovery,
                _save_triggers(previous, next_state),
                f"runtime metrics evaluated: {reason.primary_reason.value}",
            )
            return LossRuntimeEvaluationResult(
                LossRuntimeEvaluationStatus.SUCCEEDED,
                context,
                (),
            )
        except (TypeError, ValueError, ArithmeticError):
            return _failure(
                LossRuntimeEvaluationStatus.FAILED,
                "runtime evaluation failed",
            )
        except Exception:
            return _failure(
                LossRuntimeEvaluationStatus.FAILED,
                "runtime evaluation service failed",
            )
