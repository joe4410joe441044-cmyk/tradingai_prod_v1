"""Explicit MM-owned authority for starting a new PAPER accounting epoch."""

from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from .enums import TradingMode
from .loss_persistence_models import (
    AccountingContinuityStatus,
    AccountingRebaseAuditMarker,
    AccountingRebaseAuthoritySource,
    AccountingRebaseAuthorizationState,
    AccountingRebaseReason,
    LossBaselineType,
    PeriodCode,
    PersistedAccountingRebaseRecord,
    PersistedLossPeriodState,
    PersistedLossState,
)
from .loss_reason_models import RecommendedAction
from .loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    SaveTrigger,
)
from .loss_runtime_metrics_models import LossRuntimeDataQuality, LossRuntimeMetrics
from .loss_runtime_store_models import LossLimitRuntimeSnapshot, LossLimitRuntimeUpdate
from .period_aggregation import period_for
from .period_models import PeriodType


class AccountingRebaseStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    IDEMPOTENT = "IDEMPOTENT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AccountingRebaseAuthorization:
    rebase_id: str
    account_scope: str
    runtime_instance_id: str
    authority_source: AccountingRebaseAuthoritySource
    reason: AccountingRebaseReason
    authorization_state: AccountingRebaseAuthorizationState

    def __post_init__(self):
        for name in ("rebase_id", "account_scope", "runtime_instance_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} required")
        object.__setattr__(self, "authority_source", AccountingRebaseAuthoritySource(self.authority_source))
        object.__setattr__(self, "reason", AccountingRebaseReason(self.reason))
        object.__setattr__(self, "authorization_state", AccountingRebaseAuthorizationState(self.authorization_state))


@dataclass(frozen=True)
class AccountingRebaseBuildResult:
    status: AccountingRebaseStatus
    update: Optional[LossLimitRuntimeUpdate]
    record: Optional[PersistedAccountingRebaseRecord]
    safe_reasons: Tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "status", AccountingRebaseStatus(self.status))
        object.__setattr__(self, "safe_reasons", tuple(self.safe_reasons))


def _projection(state):
    action = state.last_decision.recommended_action
    if action is RecommendedAction.BLOCK_EXECUTION:
        return GovernanceProjection.BLOCK_EXECUTION
    if action is RecommendedAction.HOLD_NEW_ENTRIES:
        return GovernanceProjection.HOLD_NEW_ENTRIES
    return GovernanceProjection.CONTINUE


def _rejected(reason):
    return AccountingRebaseBuildResult(AccountingRebaseStatus.REJECTED, None, None, (reason,))


def _rebased_period(code, period_type, observed_at, equity):
    period = period_for(observed_at, period_type)
    return PersistedLossPeriodState(
        code, period.period_key, period.start_at, period.end_at, equity,
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), observed_at,
        LossBaselineType.ACCOUNTING_REBASE_BASELINE, observed_at,
    )


def build_accounting_rebase_update(
    authorization,
    metrics,
    runtime_snapshot,
    requested_at,
    maximum_age=timedelta(seconds=90),
    trading_mode=TradingMode.PAPER,
):
    """Validate explicit authority and build, but never apply, a durable rebase."""
    if not isinstance(authorization, AccountingRebaseAuthorization):
        return _rejected("explicit accounting rebase authorization required")
    if not isinstance(metrics, LossRuntimeMetrics) or metrics.data_quality is not LossRuntimeDataQuality.COMPLETE:
        return _rejected("authoritative PAPER equity unknown")
    if not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot) or not isinstance(runtime_snapshot.state, PersistedLossState):
        return _rejected("loss runtime state unavailable")
    if not isinstance(requested_at, datetime) or requested_at.tzinfo is None or requested_at.utcoffset() is None:
        return _rejected("rebase request timestamp invalid")
    requested_at = requested_at.astimezone(timezone.utc)
    if not isinstance(maximum_age, timedelta) or maximum_age.total_seconds() <= 0:
        return _rejected("rebase freshness policy invalid")
    if TradingMode(trading_mode) is not TradingMode.PAPER:
        return _rejected("PAPER accounting authority required")
    if authorization.authority_source is not AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY:
        return _rejected("PAPER accounting authority required")
    if authorization.authorization_state is not AccountingRebaseAuthorizationState.EXPLICITLY_AUTHORIZED:
        return _rejected("explicit accounting rebase authorization required")
    if authorization.reason is not AccountingRebaseReason.HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE:
        return _rejected("accounting rebase reason invalid")
    state = runtime_snapshot.state
    if metrics.captured_at < state.captured_at:
        return _rejected("authoritative PAPER equity predates persisted state")
    if authorization.account_scope != state.account_scope:
        return _rejected("account scope mismatch")
    if metrics.runtime_instance_id is None or authorization.runtime_instance_id != metrics.runtime_instance_id:
        return _rejected("runtime scope mismatch")
    if metrics.equity is None or metrics.equity <= 0:
        return _rejected("authoritative PAPER equity must be positive")
    if metrics.captured_at > requested_at or requested_at - metrics.captured_at > maximum_age:
        return _rejected("authoritative PAPER equity is stale")
    if any(item.rebase_id == authorization.rebase_id for item in state.accounting_rebases):
        item = next(item for item in state.accounting_rebases if item.rebase_id == authorization.rebase_id)
        return AccountingRebaseBuildResult(AccountingRebaseStatus.IDEMPOTENT, None, item, ())

    current = {
        PeriodCode.DAILY: period_for(metrics.captured_at, PeriodType.DAILY),
        PeriodCode.WEEKLY: period_for(metrics.captured_at, PeriodType.WEEKLY),
        PeriodCode.MONTHLY: period_for(metrics.captured_at, PeriodType.MONTHLY),
    }
    previous = {
        PeriodCode.DAILY: state.daily_state,
        PeriodCode.WEEKLY: state.weekly_state,
        PeriodCode.MONTHLY: state.monthly_state,
    }
    affected = tuple(code for code in PeriodCode if previous[code].period_id != current[code].period_key)
    if not affected:
        return _rejected("no accounting period mismatch")
    pnl = {
        PeriodCode.DAILY: metrics.daily_pnl,
        PeriodCode.WEEKLY: metrics.weekly_pnl,
        PeriodCode.MONTHLY: metrics.monthly_pnl,
    }
    if any(pnl[code] is None for code in affected):
        return _rejected("authoritative period PnL unavailable")
    record = PersistedAccountingRebaseRecord(
        authorization.rebase_id, metrics.captured_at, metrics.equity,
        authorization.authority_source, state.account_scope,
        authorization.runtime_instance_id, affected,
        tuple(previous[code].period_id for code in affected),
        tuple(current[code].period_key for code in affected),
        tuple(pnl[code] for code in affected), authorization.reason,
        AccountingContinuityStatus.UNAVAILABLE_REBASED,
        authorization.authorization_state,
        AccountingRebaseAuditMarker.DURABLE_CHECKPOINT_REQUIRED,
    )
    period_states = dict(previous)
    types = {PeriodCode.DAILY: PeriodType.DAILY, PeriodCode.WEEKLY: PeriodType.WEEKLY, PeriodCode.MONTHLY: PeriodType.MONTHLY}
    for code in affected:
        period_states[code] = _rebased_period(code, types[code], metrics.captured_at, metrics.equity)
    next_state = replace(
        state,
        daily_state=period_states[PeriodCode.DAILY],
        weekly_state=period_states[PeriodCode.WEEKLY],
        monthly_state=period_states[PeriodCode.MONTHLY],
        captured_at=metrics.captured_at,
        accounting_rebases=state.accounting_rebases + (record,),
    )
    recovery = LossLimitRecoveryRequirement(False, (), False, False, False, "recovery not required")
    update = LossLimitRuntimeUpdate(
        next_state, _projection(next_state), recovery,
        (SaveTrigger.ACCOUNTING_REBASE,), runtime_snapshot.revision,
        runtime_snapshot.sequence + 1, requested_at,
        "EXPLICIT_ACCOUNTING_REBASE",
    )
    return AccountingRebaseBuildResult(AccountingRebaseStatus.ACCEPTED, update, record, ())
