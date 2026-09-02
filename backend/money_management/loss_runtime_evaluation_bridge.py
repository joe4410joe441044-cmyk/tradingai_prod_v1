"""MM-4I bridge from normalized runtime metrics to existing loss evaluation."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from threading import RLock
from typing import Optional, Tuple

from .enums import RiskState, TradingMode
from .loss_accounting_rebase import (
    AccountingRebaseAuthorization,
    AccountingRebaseStatus,
    build_accounting_rebase_update,
)
from .loss_decision import evaluate_loss_decision
from .loss_models import (
    CashFlowAdjustmentState,
    LossLimitConfig,
    MoneyManagementLossDecisionInput,
)
from .loss_persistence_models import (
    AccountingRebaseAuthoritySource,
    AccountingRebaseAuthorizationState,
    AccountingRebaseReason,
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


def _apply_rebase_pnl_baseline(previous, aggregate, code):
    for record in reversed(previous.accounting_rebases):
        if code not in record.affected_periods:
            continue
        index = record.affected_periods.index(code)
        if record.new_period_ids[index] != aggregate.period.period_key:
            continue
        pnl = aggregate.net_realized_pnl - record.observed_period_pnl[index]
        return MoneyManagementPeriodAggregate(
            aggregate.schema_version, aggregate.period, aggregate.currency,
            aggregate.event_count, pnl, aggregate.fees,
            aggregate.funding, pnl, max(Decimal("0"), pnl),
            max(Decimal("0"), -pnl), aggregate.winning_event_count,
            aggregate.losing_event_count, aggregate.first_event_at,
            aggregate.last_event_at, aggregate.last_sequence,
            aggregate.processed_event_ids, aggregate.updated_at,
        )
    return aggregate


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


def _attempt_period_rollover(metrics, runtime_snapshot, trading_mode):
    """Roll expired accounting periods forward using authoritative equity.

    Reuses the existing accounting-rebase contract for every validation and
    state-construction step. Returns the rebased ``PersistedLossState`` when
    the current runtime observation carries the authoritative starting equity
    required to establish a new accounting period, otherwise ``None``.

    Fail-closed: authority is never established when the authoritative equity
    is absent, non-positive, stale, predates persisted state, belongs to a
    different runtime/account scope, lacks authoritative period PnL, or when
    the trading mode is not PAPER.
    """
    state = (
        runtime_snapshot.state
        if isinstance(runtime_snapshot, LossLimitRuntimeSnapshot)
        else None
    )
    if not isinstance(state, PersistedLossState):
        return None
    runtime_instance_id = metrics.runtime_instance_id
    if (
        not isinstance(runtime_instance_id, str)
        or not runtime_instance_id.strip()
        or not isinstance(state.account_scope, str)
        or not state.account_scope.strip()
    ):
        return None
    rebase_id = (
        f"runtime-rollover:{runtime_instance_id}:"
        f"{metrics.captured_at.isoformat()}"
    )
    authorization = AccountingRebaseAuthorization(
        rebase_id,
        state.account_scope,
        runtime_instance_id,
        AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY,
        AccountingRebaseReason.HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE,
        AccountingRebaseAuthorizationState.EXPLICITLY_AUTHORIZED,
    )
    result = build_accounting_rebase_update(
        authorization,
        metrics,
        runtime_snapshot,
        metrics.captured_at,
        trading_mode=trading_mode,
    )
    if result.status is not AccountingRebaseStatus.ACCEPTED:
        return None
    update = result.update
    if update is None or not isinstance(update.next_state, PersistedLossState):
        return None
    return update.next_state


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
        trading_mode=TradingMode.PAPER,
        trading_mode_provider=None,
    ):
        self._config = config or LossLimitConfig()
        if not isinstance(self._config, LossLimitConfig):
            raise TypeError("loss limit config required")
        if not callable(domain_evaluator) or not callable(reason_builder):
            raise TypeError("domain services required")
        self._domain_evaluator = domain_evaluator
        self._reason_builder = reason_builder
        self._trading_mode = TradingMode(trading_mode)
        if trading_mode_provider is not None and not callable(
            trading_mode_provider
        ):
            raise TypeError("trading mode provider must be callable")
        self._trading_mode_provider = trading_mode_provider
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
            trading_mode = (
                TradingMode(self._trading_mode_provider())
                if self._trading_mode_provider is not None
                else self._trading_mode
            )
            sequence = runtime_snapshot.sequence + 1
            daily = _aggregate(metrics, PeriodType.DAILY, sequence)
            weekly = _aggregate(metrics, PeriodType.WEEKLY, sequence)
            monthly = _aggregate(metrics, PeriodType.MONTHLY, sequence)
            period_rollover = False
            if not _periods_match(previous, daily, weekly, monthly):
                rebased = _attempt_period_rollover(
                    metrics, runtime_snapshot, trading_mode
                )
                if rebased is None:
                    return _failure(
                        LossRuntimeEvaluationStatus.RECOVERY_REQUIRED,
                        "period rollover requires authoritative starting equity",
                    )
                previous = rebased
                period_rollover = True
            daily = _apply_rebase_pnl_baseline(previous, daily, PeriodCode.DAILY)
            weekly = _apply_rebase_pnl_baseline(previous, weekly, PeriodCode.WEEKLY)
            monthly = _apply_rebase_pnl_baseline(previous, monthly, PeriodCode.MONTHLY)
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
                accounting_rebases=previous.accounting_rebases,
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
            triggers = _save_triggers(previous, next_state)
            if period_rollover and SaveTrigger.PERIOD_ROLLOVER not in triggers:
                triggers = (SaveTrigger.PERIOD_ROLLOVER,) + triggers
            context = LossRuntimeUpdateBuildContext(
                event_id,
                next_state,
                governance,
                recovery,
                triggers,
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
