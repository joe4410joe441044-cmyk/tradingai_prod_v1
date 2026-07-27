"""MM-2E typed reason/action contract adapter."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Tuple
from .enums import RiskState
from .loss_models import LossReason, MoneyManagementLossDecision
from .period_models import PeriodType
class RecommendedAction(str,Enum):
    CONTINUE="CONTINUE"; REDUCE_RISK="REDUCE_RISK"; HOLD_NEW_ENTRIES="HOLD_NEW_ENTRIES"; BLOCK_EXECUTION="BLOCK_EXECUTION"
class WarningReason(str,Enum):
    DAILY_LOSS_WARNING="DAILY_LOSS_WARNING"; WEEKLY_LOSS_WARNING="WEEKLY_LOSS_WARNING"; MONTHLY_LOSS_WARNING="MONTHLY_LOSS_WARNING"; DRAWDOWN_WARNING="DRAWDOWN_WARNING"
class HoldReason(str,Enum):
    MULTIPLE_LOSS_WARNINGS="MULTIPLE_LOSS_WARNINGS"; LOSS_LIMIT_DEFENSIVE_STATE="LOSS_LIMIT_DEFENSIVE_STATE"
class BlockReason(str,Enum):
    DAILY_LOSS_BLOCK="DAILY_LOSS_BLOCK"; WEEKLY_LOSS_BLOCK="WEEKLY_LOSS_BLOCK"; MONTHLY_LOSS_BLOCK="MONTHLY_LOSS_BLOCK"; DRAWDOWN_BLOCK="DRAWDOWN_BLOCK"; NEGATIVE_EQUITY="NEGATIVE_EQUITY"; DRAWDOWN_PERCENT_UNKNOWN="DRAWDOWN_PERCENT_UNKNOWN"; CASH_FLOW_DETECTED="CASH_FLOW_DETECTED"; INCOMPLETE_INPUT="INCOMPLETE_INPUT"; UNSAFE_STATE="UNSAFE_STATE"
class DiagnosticReason(str,Enum):
    STARTING_EQUITY_ZERO="STARTING_EQUITY_ZERO"; HIGH_WATER_MARK_ZERO="HIGH_WATER_MARK_ZERO"; CASH_FLOW_PRESENT="CASH_FLOW_PRESENT"; METRIC_UNAVAILABLE="METRIC_UNAVAILABLE"
class PeriodCode(str,Enum):
    DAILY="DAILY"; WEEKLY="WEEKLY"; MONTHLY="MONTHLY"; DRAWDOWN="DRAWDOWN"; ACCOUNT="ACCOUNT"; NOT_APPLICABLE="NOT_APPLICABLE"
class ReasonCode(str,Enum):
    NONE="NONE"; DAILY_LOSS_WARNING="DAILY_LOSS_WARNING"; WEEKLY_LOSS_WARNING="WEEKLY_LOSS_WARNING"; MONTHLY_LOSS_WARNING="MONTHLY_LOSS_WARNING"; DRAWDOWN_WARNING="DRAWDOWN_WARNING"; DAILY_LOSS_BLOCK="DAILY_LOSS_BLOCK"; WEEKLY_LOSS_BLOCK="WEEKLY_LOSS_BLOCK"; MONTHLY_LOSS_BLOCK="MONTHLY_LOSS_BLOCK"; DRAWDOWN_BLOCK="DRAWDOWN_BLOCK"; NEGATIVE_EQUITY="NEGATIVE_EQUITY"; DRAWDOWN_PERCENT_UNKNOWN="DRAWDOWN_PERCENT_UNKNOWN"; CASH_FLOW_DETECTED="CASH_FLOW_DETECTED"; MULTIPLE_LOSS_WARNINGS="MULTIPLE_LOSS_WARNINGS"; LOSS_LIMIT_DEFENSIVE_STATE="LOSS_LIMIT_DEFENSIVE_STATE"
@dataclass(frozen=True)
class LossMetric:
    period: PeriodCode
    net_loss: Decimal
    loss_percent: Decimal
    def to_dict(self): return {"period":self.period.value,"net_loss":format(self.net_loss,"f"),"loss_percent":format(self.loss_percent,"f")}
@dataclass(frozen=True)
class LossReasonContract:
    schema_version: str
    evaluated_at: datetime
    decision_state: RiskState
    recommended_action: RecommendedAction
    primary_reason: ReasonCode
    warning_reasons: Tuple[WarningReason,...]
    hold_reasons: Tuple[HoldReason,...]
    block_reasons: Tuple[BlockReason,...]
    diagnostic_reasons: Tuple[DiagnosticReason,...]
    triggered_periods: Tuple[PeriodCode,...]
    metrics: Tuple[LossMetric,...]
    fail_closed: bool
    def __post_init__(self):
        if self.schema_version!="money-management-loss-reason/v1": raise ValueError("unsupported schema")
        if not isinstance(self.evaluated_at,datetime) or self.evaluated_at.tzinfo is None: raise TypeError("timezone-aware evaluated_at required")
        object.__setattr__(self,"evaluated_at",self.evaluated_at.astimezone(timezone.utc))
        object.__setattr__(self,"decision_state",RiskState(self.decision_state)); object.__setattr__(self,"recommended_action",RecommendedAction(self.recommended_action)); object.__setattr__(self,"primary_reason",ReasonCode(self.primary_reason))
        for attr,typ in (("warning_reasons",WarningReason),("hold_reasons",HoldReason),("block_reasons",BlockReason),("diagnostic_reasons",DiagnosticReason),("triggered_periods",PeriodCode)):
            vals=tuple(typ(x) for x in getattr(self,attr))
            if len(vals)!=len(set(vals)): raise ValueError(f"{attr} must be unique")
            object.__setattr__(self,attr,vals)
        if len({m.period for m in self.metrics})!=len(self.metrics): raise ValueError("metrics periods must be unique")
        if self.decision_state is RiskState.LOCKED:
            if not self.block_reasons or self.recommended_action is not RecommendedAction.BLOCK_EXECUTION: raise ValueError("LOCKED requires block execution and block reason")
        elif self.decision_state is RiskState.DEFENSIVE:
            if self.block_reasons or len(self.warning_reasons)<2 or not self.hold_reasons or self.recommended_action is not RecommendedAction.HOLD_NEW_ENTRIES: raise ValueError("invalid DEFENSIVE contract")
        elif self.decision_state is RiskState.CAUTION:
            if self.block_reasons or not self.warning_reasons or self.recommended_action is RecommendedAction.BLOCK_EXECUTION: raise ValueError("invalid CAUTION contract")
        elif self.decision_state is RiskState.NORMAL:
            if self.block_reasons or self.hold_reasons or self.warning_reasons or self.recommended_action is not RecommendedAction.CONTINUE: raise ValueError("invalid NORMAL contract")
    def to_dict(self):
        def s(v):
            if isinstance(v,Enum): return v.value
            if isinstance(v,Decimal): return format(v,"f")
            if isinstance(v,datetime): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
            if isinstance(v,tuple): return [s(x) for x in v]
            if hasattr(v,"to_dict"): return v.to_dict()
            return v
        return {f.name:s(getattr(self,f.name)) for f in fields(self)}
def _warning(value):
    return {"DAILY_LOSS_WARNING":WarningReason.DAILY_LOSS_WARNING,"WEEKLY_LOSS_WARNING":WarningReason.WEEKLY_LOSS_WARNING,"MONTHLY_LOSS_WARNING":WarningReason.MONTHLY_LOSS_WARNING}.get(value)
def _block(value):
    return {"DAILY_LOSS_BLOCK":BlockReason.DAILY_LOSS_BLOCK,"WEEKLY_LOSS_BLOCK":BlockReason.WEEKLY_LOSS_BLOCK,"MONTHLY_LOSS_BLOCK":BlockReason.MONTHLY_LOSS_BLOCK,"MAX_DRAWDOWN_BLOCK":BlockReason.DRAWDOWN_BLOCK,"NEGATIVE_EQUITY":BlockReason.NEGATIVE_EQUITY,"DRAWDOWN_PERCENT_UNKNOWN":BlockReason.DRAWDOWN_PERCENT_UNKNOWN,"CASH_FLOW_ADJUSTMENT_UNRESOLVED":BlockReason.CASH_FLOW_DETECTED}.get(value)
def build_reason_contract(decision: MoneyManagementLossDecision) -> LossReasonContract:
    if not isinstance(decision,MoneyManagementLossDecision): raise TypeError("typed loss decision required")
    warnings=tuple(x for x in (_warning(e.reason.value) for e in (decision.daily_evaluation,decision.weekly_evaluation,decision.monthly_evaluation)) if x)
    holds=(HoldReason.MULTIPLE_LOSS_WARNINGS,) if decision.risk_state is RiskState.DEFENSIVE else ()
    blocks=tuple(x for x in (_block(r.value) for r in decision.reasons) if x)
    diagnostics=(DiagnosticReason.HIGH_WATER_MARK_ZERO,) if decision.drawdown_percent is None else ()
    if decision.risk_state is RiskState.LOCKED and not blocks: blocks=(BlockReason.UNSAFE_STATE,)
    action=RecommendedAction.BLOCK_EXECUTION if decision.risk_state is RiskState.LOCKED else RecommendedAction.HOLD_NEW_ENTRIES if decision.risk_state is RiskState.DEFENSIVE else RecommendedAction.CONTINUE
    state=decision.risk_state
    primary=ReasonCode.MULTIPLE_LOSS_WARNINGS if decision.primary_reason is LossReason.MULTIPLE_WARNINGS else ReasonCode(decision.primary_reason.value if decision.primary_reason.value in {x.value for x in ReasonCode} else "NONE")
    periods=tuple(x for x in (PeriodCode.DAILY if warnings and warnings[0] is WarningReason.DAILY_LOSS_WARNING else None,PeriodCode.WEEKLY if any(x is WarningReason.WEEKLY_LOSS_WARNING for x in warnings) else None,PeriodCode.MONTHLY if any(x is WarningReason.MONTHLY_LOSS_WARNING for x in warnings) else None,PeriodCode.DRAWDOWN if decision.drawdown_percent is not None and decision.primary_reason is LossReason.MAX_DRAWDOWN_BLOCK else None) if x)
    metrics=tuple(LossMetric(PeriodCode[e.period_type.value],e.loss_amount,e.loss_percent) for e in (decision.daily_evaluation,decision.weekly_evaluation,decision.monthly_evaluation))
    return LossReasonContract("money-management-loss-reason/v1",decision.evaluated_at,state,action,primary,warnings,holds,blocks,diagnostics,periods,metrics,decision.fail_closed)
