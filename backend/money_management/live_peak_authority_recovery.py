"""Validated recovery of a REAL_LIVE high-water mark contaminated by PAPER equity.

A REAL_LIVE loss state may only carry a high-water mark that was established
by REAL_LIVE equity: the validated epoch baseline (the last authority rebase
into REAL_LIVE) or a later REAL_LIVE observation.  A stopped-PAPER maintenance
observation used to fold the PAPER account equity into that peak without
changing the authority marker, which locked LIVE entry on a fictitious
drawdown.

This module only *builds* a runtime-store update.  It never performs I/O,
never accepts a caller supplied peak and never relaxes a legitimate REAL_LIVE
drawdown.  Every recovered value is derived from authoritative evidence:

* the persisted REAL_LIVE loss state and its accounting rebase history,
* a fresh GET-only REAL_LIVE account proof (FLAT, no pending orders),
* the PAPER account equity (the contaminating domain value),
* the recorded REAL_LIVE observations of the current LIVE epoch.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from .enums import RiskState
from .loss_persistence_models import (
    AccountingContinuityStatus,
    AccountingRebaseAuditMarker,
    AccountingRebaseAuthoritySource,
    AccountingRebaseAuthorizationState,
    AccountingRebaseReason,
    PersistedAccountingRebaseRecord,
    PersistedDrawdownState,
    PersistedLossState,
)
from .loss_reason_models import (
    BlockReason,
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
)
from .loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    SaveTrigger,
)
from .loss_runtime_store_models import LossLimitRuntimeSnapshot, LossLimitRuntimeUpdate


LIVE = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY
RECOVERY_REASON = AccountingRebaseReason.LIVE_PEAK_AUTHORITY_CONTAMINATION_RECOVERY
RECOVERY_OPERATION = "LIVE_PEAK_AUTHORITY_CONTAMINATION_RECOVERY"
RECOVERY_TRANSITION_REASON = "VALIDATED_LIVE_PEAK_AUTHORITY_RECOVERY"
MAXIMUM_LIVE_EVIDENCE_AGE = timedelta(seconds=30)


class LivePeakRecoveryStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


def _decimal_or_none(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:
        return None
    return result if result.is_finite() else None


def _utc_or_none(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        return None
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class LivePeakRecoveryEvidence:
    """Authoritative inputs; built by the application boundary, never by users."""

    bot_stopped: bool
    execution_disabled: bool
    emergency_clear: bool
    internal_pending_order: Optional[bool]
    live_account_ready: bool
    live_capital_authority: Optional[str]
    live_open_position_state: Optional[str]
    live_pending_order_state: Optional[str]
    live_equity: Optional[Decimal]
    live_evaluated_at: Optional[datetime]
    paper_equity: Optional[Decimal]
    live_epoch_history_available: bool
    live_epoch_observations: Tuple[Tuple[Decimal, Decimal], ...] = field(
        default_factory=tuple
    )


@dataclass(frozen=True)
class LivePeakRecoveryResult:
    status: LivePeakRecoveryStatus
    update: Optional[LossLimitRuntimeUpdate]
    record: Optional[PersistedAccountingRebaseRecord]
    safe_reasons: Tuple[str, ...]
    recovered_high_water_mark: Optional[Decimal] = None
    contaminated_high_water_mark: Optional[Decimal] = None
    live_epoch_rebase_id: Optional[str] = None

    def to_dict(self):
        def value(item):
            return format(item, "f") if isinstance(item, Decimal) else item
        return {
            "status": self.status.value,
            "safeReasons": list(self.safe_reasons),
            "recoveredHighWaterMark": value(self.recovered_high_water_mark),
            "contaminatedHighWaterMark": value(self.contaminated_high_water_mark),
            "liveEpochRebaseId": self.live_epoch_rebase_id,
            "rebase": self.record.to_dict() if self.record is not None else None,
        }


def _rejected(reasons, **extra):
    return LivePeakRecoveryResult(
        LivePeakRecoveryStatus.REJECTED, None, None, tuple(reasons), **extra
    )


def live_epoch_record(state):
    """Return the validated rebase that opened the current REAL_LIVE epoch."""

    records = tuple(state.accounting_rebases)
    epoch = None
    for index, record in enumerate(records):
        previous = records[index - 1] if index else None
        if record.authority_source is not LIVE:
            epoch = None
            continue
        if (
            record.reason
            is AccountingRebaseReason.HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE
            and (previous is None or previous.authority_source is not LIVE)
        ):
            epoch = record
    return epoch


def _epoch_live_records(state, epoch):
    records = tuple(state.accounting_rebases)
    return tuple(
        record
        for record in records[records.index(epoch):]
        if record.authority_source is LIVE
    )


def live_epoch_rebase_ids(state):
    """Rebase IDs that REAL_LIVE observations of the current epoch carry."""

    if state.accounting_authority_source is not LIVE:
        return ()
    epoch = live_epoch_record(state)
    if epoch is None:
        return ()
    return tuple(record.rebase_id for record in _epoch_live_records(state, epoch))


def _validated_epoch_peaks(state, epoch):
    """REAL_LIVE equities validated inside the epoch by durable rebase records."""

    return [record.authoritative_equity for record in _epoch_live_records(state, epoch)]


def _period_baseline_mapping(state):
    """Neutral period mapping that keeps every PnL baseline exactly unchanged."""

    affected, previous_ids, new_ids, pnl = [], [], [], []
    periods = (state.daily_state, state.weekly_state, state.monthly_state)
    for period in periods:
        code = period.period_code
        for record in reversed(state.accounting_rebases):
            if code not in record.affected_periods:
                continue
            index = record.affected_periods.index(code)
            if record.new_period_ids[index] == period.period_id:
                affected.append(code)
                previous_ids.append(period.period_id)
                new_ids.append(period.period_id)
                pnl.append(record.observed_period_pnl[index])
            break
    return tuple(affected), tuple(previous_ids), tuple(new_ids), tuple(pnl)


def build_live_peak_authority_recovery(
    runtime_snapshot,
    evidence,
    *,
    requested_at,
    runtime_instance_id,
    maximum_drawdown_pct,
    maximum_evidence_age=MAXIMUM_LIVE_EVIDENCE_AGE,
):
    """Validate the contamination signature and build (never apply) an update."""

    if not isinstance(runtime_snapshot, LossLimitRuntimeSnapshot) or not isinstance(
        runtime_snapshot.state, PersistedLossState
    ):
        return _rejected(("LOSS_RUNTIME_STATE_UNAVAILABLE",))
    if not isinstance(evidence, LivePeakRecoveryEvidence):
        return _rejected(("RECOVERY_EVIDENCE_INVALID",))
    at = _utc_or_none(requested_at)
    if at is None:
        return _rejected(("RECOVERY_REQUEST_TIMESTAMP_INVALID",))
    if not isinstance(runtime_instance_id, str) or not runtime_instance_id.strip():
        return _rejected(("RUNTIME_SCOPE_UNAVAILABLE",))
    limit = _decimal_or_none(maximum_drawdown_pct)
    if limit is None or limit <= 0:
        return _rejected(("DRAWDOWN_POLICY_UNAVAILABLE",))

    state = runtime_snapshot.state
    reasons = []

    # 1. Operational safety: nothing may trade while the peak is repaired.
    if evidence.bot_stopped is not True:
        reasons.append("BOT_NOT_STOPPED")
    if evidence.execution_disabled is not True:
        reasons.append("EXECUTION_NOT_DISABLED")
    if evidence.emergency_clear is not True:
        reasons.append("EMERGENCY_NOT_CLEAR")
    if evidence.internal_pending_order is not False:
        reasons.append("INTERNAL_PENDING_ORDER_NOT_CLEAR")

    # 2. Fresh GET-only REAL_LIVE account proof.
    live_equity = _decimal_or_none(evidence.live_equity)
    live_at = _utc_or_none(evidence.live_evaluated_at)
    if (
        evidence.live_account_ready is not True
        or evidence.live_capital_authority != "REAL_LIVE_ACCOUNT"
    ):
        reasons.append("LIVE_ACCOUNT_AUTHORITY_NOT_READY")
    if evidence.live_open_position_state != "FLAT":
        reasons.append("LIVE_POSITION_NOT_FLAT")
    if evidence.live_pending_order_state != "NONE":
        reasons.append("LIVE_PENDING_ORDER_NOT_CLEAR")
    if live_equity is None or live_equity <= 0:
        reasons.append("LIVE_EQUITY_UNAVAILABLE")
    if (
        live_at is None
        or live_at > at
        or at - live_at > maximum_evidence_age
    ):
        reasons.append("LIVE_EQUITY_NOT_FRESH")
    elif live_at < state.captured_at:
        reasons.append("LIVE_EQUITY_PREDATES_PERSISTED_STATE")

    # 3. The persisted state must be a REAL_LIVE drawdown-only lock.
    decision = state.last_decision
    if state.accounting_authority_source is not LIVE:
        reasons.append("STATE_NOT_REAL_LIVE_AUTHORITY")
    if (
        decision.decision_state is not RiskState.LOCKED
        or tuple(decision.block_reasons) != (BlockReason.DRAWDOWN_BLOCK,)
        or decision.warning_reasons
        or decision.hold_reasons
        or decision.diagnostic_reasons
    ):
        reasons.append("STATE_NOT_DRAWDOWN_ONLY_LOCK")
    if state.cash_flow_state.has_unresolved_cash_flow:
        reasons.append("CASH_FLOW_UNRESOLVED")
    if at < state.captured_at:
        reasons.append("PERSISTED_STATE_NEWER_THAN_REQUEST")

    hwm = state.drawdown_state.high_water_mark
    epoch = live_epoch_record(state) if state.accounting_authority_source is LIVE else None
    if epoch is None:
        reasons.append("LIVE_EPOCH_BASELINE_UNAVAILABLE")
        return _rejected(reasons, contaminated_high_water_mark=hwm)

    # 4. Contamination signature (all conditions required).
    validated_peaks = _validated_epoch_peaks(state, epoch)
    if hwm <= max(validated_peaks):
        reasons.append("HIGH_WATER_MARK_EXPLAINED_BY_LIVE_BASELINE")
    paper_equity = _decimal_or_none(evidence.paper_equity)
    if paper_equity is None or paper_equity <= 0:
        reasons.append("PAPER_EQUITY_UNAVAILABLE")
    elif paper_equity != hwm:
        reasons.append("HIGH_WATER_MARK_NOT_PAPER_DOMAIN_VALUE")
    observations = tuple(evidence.live_epoch_observations or ())
    if evidence.live_epoch_history_available is not True or not observations:
        reasons.append("LIVE_EPOCH_HISTORY_UNAVAILABLE")
        observed_equities = ()
    else:
        try:
            normalized = tuple(
                (_decimal_or_none(equity), _decimal_or_none(peak))
                for equity, peak in observations
            )
        except (TypeError, ValueError):
            normalized = ((None, None),)
        if any(e is None or p is None or e < 0 or p < 0 for e, p in normalized):
            reasons.append("LIVE_EPOCH_HISTORY_INVALID")
            observed_equities = ()
        else:
            observed_equities = tuple(e for e, _ in normalized)
            if any(e >= hwm for e in observed_equities):
                reasons.append("LIVE_EQUITY_REACHED_HIGH_WATER_MARK")
            legit_bound = max(
                list(validated_peaks)
                + list(observed_equities)
                + ([live_equity] if live_equity is not None else [])
            )
            if any(p != hwm and p > legit_bound for _, p in normalized):
                reasons.append("HIGH_WATER_MARK_EVOLUTION_UNEXPLAINED")
    if live_equity is not None and live_equity >= hwm:
        reasons.append("LIVE_EQUITY_REACHED_HIGH_WATER_MARK")

    # 5. The recovered peak is the last validated REAL_LIVE peak; a legitimate
    #    REAL_LIVE drawdown against it is never relaxed.
    candidates = list(validated_peaks) + list(observed_equities)
    if live_equity is not None:
        candidates.append(live_equity)
    recovered = max(candidates)
    drawdown_amount = (
        recovered - live_equity if live_equity is not None else None
    )
    drawdown_pct = (
        drawdown_amount / recovered * Decimal("100")
        if drawdown_amount is not None and recovered > 0
        else None
    )
    if drawdown_pct is None or drawdown_pct >= limit:
        reasons.append("LEGITIMATE_LIVE_DRAWDOWN_PRESENT")

    affected, previous_ids, new_ids, pnl = _period_baseline_mapping(state)
    if not affected:
        reasons.append("PERIOD_BASELINE_MAPPING_UNAVAILABLE")

    unique = tuple(dict.fromkeys(reasons))
    if unique:
        return _rejected(
            unique,
            contaminated_high_water_mark=hwm,
            live_epoch_rebase_id=epoch.rebase_id,
        )

    rebase_id = (
        f"live-peak-authority-recovery:{runtime_instance_id}:"
        f"{live_at.isoformat()}"
    )
    if any(item.rebase_id == rebase_id for item in state.accounting_rebases):
        return _rejected(("RECOVERY_ALREADY_RECORDED",))
    record = PersistedAccountingRebaseRecord(
        rebase_id,
        live_at,
        recovered,
        LIVE,
        state.account_scope,
        runtime_instance_id,
        affected,
        previous_ids,
        new_ids,
        pnl,
        RECOVERY_REASON,
        AccountingContinuityStatus.PEAK_AUTHORITY_REPAIRED,
        AccountingRebaseAuthorizationState.EXPLICITLY_AUTHORIZED,
        AccountingRebaseAuditMarker.DURABLE_CHECKPOINT_REQUIRED,
    )
    reason = LossReasonContract(
        "money-management-loss-reason/v1",
        at,
        RiskState.NORMAL,
        RecommendedAction.CONTINUE,
        ReasonCode.NONE,
        (), (), (), (), (),
        decision.metrics,
        False,
    )
    next_state = replace(
        state,
        drawdown_state=PersistedDrawdownState(
            recovered,
            live_equity,
            drawdown_amount,
            drawdown_pct,
            at,
        ),
        last_decision=reason,
        captured_at=at,
        accounting_rebases=state.accounting_rebases + (record,),
    )
    update = LossLimitRuntimeUpdate(
        next_state,
        GovernanceProjection.CONTINUE,
        LossLimitRecoveryRequirement(
            False, (), False, False, False, "recovery not required"
        ),
        (SaveTrigger.ACCOUNTING_REBASE, SaveTrigger.RECOVERY_COMPLETED),
        runtime_snapshot.revision,
        runtime_snapshot.sequence + 1,
        at,
        RECOVERY_TRANSITION_REASON,
        record.rebase_id,
    )
    return LivePeakRecoveryResult(
        LivePeakRecoveryStatus.ACCEPTED,
        update,
        record,
        (),
        recovered,
        hwm,
        epoch.rebase_id,
    )
