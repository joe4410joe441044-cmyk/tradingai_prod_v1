"""MM-2C typed loss decision contracts."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple
from .enums import RiskState
from .period_models import PeriodType, MoneyManagementPeriodAggregate, MoneyManagementEquitySnapshot, PERIOD_SCHEMA_VERSION
class ActionDecision(str,Enum):
    ALLOW="ALLOW"; WARN="WARN"; BLOCK="BLOCK"
class ThresholdState(str,Enum):
    BELOW_WARNING="BELOW_WARNING"; WARNING="WARNING"; BLOCK="BLOCK"
class CashFlowAdjustmentState(str,Enum):
    NONE="NONE"; DEPOSIT="DEPOSIT"; WITHDRAWAL="WITHDRAWAL"; TRANSFER="TRANSFER"; MANUAL_ADJUSTMENT="MANUAL_ADJUSTMENT"; UNKNOWN="UNKNOWN"
class LossReason(str,Enum):
    NONE="NONE"; DAILY_LOSS_WARNING="DAILY_LOSS_WARNING"; DAILY_LOSS_BLOCK="DAILY_LOSS_BLOCK"; WEEKLY_LOSS_WARNING="WEEKLY_LOSS_WARNING"; WEEKLY_LOSS_BLOCK="WEEKLY_LOSS_BLOCK"; MONTHLY_LOSS_WARNING="MONTHLY_LOSS_WARNING"; MONTHLY_LOSS_BLOCK="MONTHLY_LOSS_BLOCK"; MAX_DRAWDOWN_BLOCK="MAX_DRAWDOWN_BLOCK"; NEGATIVE_EQUITY="NEGATIVE_EQUITY"; DRAWDOWN_PERCENT_UNKNOWN="DRAWDOWN_PERCENT_UNKNOWN"; CASH_FLOW_ADJUSTMENT_UNRESOLVED="CASH_FLOW_ADJUSTMENT_UNRESOLVED"; MULTIPLE_WARNINGS="MULTIPLE_WARNINGS"; BASE_EQUITY_INVALID="BASE_EQUITY_INVALID"; PERIOD_DATA_MISSING="PERIOD_DATA_MISSING"; PERIOD_DATA_MISMATCH="PERIOD_DATA_MISMATCH"; CURRENCY_MISMATCH="CURRENCY_MISMATCH"; CONFIG_INVALID="CONFIG_INVALID"; INPUT_UNKNOWN="INPUT_UNKNOWN"
def _d(name,v,positive=False):
    if isinstance(v,bool) or not isinstance(v,Decimal): raise TypeError(f"{name} must be Decimal")
    if not v.is_finite(): raise ValueError(f"{name} must be finite")
    if positive and v<=0: raise ValueError(f"{name} must be > 0")
    return v
def _dt(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise TypeError("timezone-aware datetime required")
    return v.astimezone(timezone.utc)
def _ser(v):
    if isinstance(v,Enum): return v.value
    if isinstance(v,Decimal): return format(v,"f")
    if isinstance(v,datetime): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    if isinstance(v,tuple): return [_ser(x) for x in v]
    if hasattr(v,"__dataclass_fields__"): return {f.name:_ser(getattr(v,f.name)) for f in fields(v)}
    return v
@dataclass(frozen=True)
class LossLimitConfig:
    daily_warning_pct: Decimal=Decimal("1.00")
    daily_block_pct: Decimal=Decimal("1.50")
    weekly_warning_pct: Decimal=Decimal("2.00")
    weekly_block_pct: Decimal=Decimal("3.00")
    monthly_warning_pct: Decimal=Decimal("3.00")
    monthly_block_pct: Decimal=Decimal("4.00")
    maximum_drawdown_pct: Decimal=Decimal("5.00")
    def __post_init__(self):
        vals=("daily_warning_pct","daily_block_pct","weekly_warning_pct","weekly_block_pct","monthly_warning_pct","monthly_block_pct","maximum_drawdown_pct")
        for n in vals: _d(n,getattr(self,n),True)
        if self.daily_warning_pct>=self.daily_block_pct or self.weekly_warning_pct>=self.weekly_block_pct or self.monthly_warning_pct>=self.monthly_block_pct: raise ValueError("warning must be below block")
        if self.daily_block_pct>=self.weekly_block_pct or self.weekly_block_pct>self.monthly_block_pct or self.monthly_block_pct>=self.maximum_drawdown_pct: raise ValueError("loss threshold order invalid")
        if self.maximum_drawdown_pct>Decimal("100"): raise ValueError("maximum drawdown invalid")
    def to_dict(self): return _ser(self)
@dataclass(frozen=True)
class MoneyManagementLossDecisionInput:
    schema_version: str
    evaluated_at: datetime
    currency: str
    daily_aggregate: MoneyManagementPeriodAggregate
    weekly_aggregate: MoneyManagementPeriodAggregate
    monthly_aggregate: MoneyManagementPeriodAggregate
    daily_starting_equity: Decimal
    weekly_starting_equity: Decimal
    monthly_starting_equity: Decimal
    equity_snapshot: MoneyManagementEquitySnapshot
    config: LossLimitConfig
    cash_flow_adjustment_state: CashFlowAdjustmentState=CashFlowAdjustmentState.NONE
    def __post_init__(self):
        if self.schema_version!=PERIOD_SCHEMA_VERSION: raise ValueError("unsupported schema")
        object.__setattr__(self,"evaluated_at",_dt(self.evaluated_at))
        if self.currency!="USDT": raise ValueError("unsupported currency")
        if not isinstance(self.config,LossLimitConfig): raise TypeError("config required")
        if not isinstance(self.equity_snapshot,MoneyManagementEquitySnapshot): raise TypeError("equity snapshot required")
        for n in ("daily_starting_equity","weekly_starting_equity","monthly_starting_equity"): _d(n,getattr(self,n),True)
        for n,typ in (("daily_aggregate",PeriodType.DAILY),("weekly_aggregate",PeriodType.WEEKLY),("monthly_aggregate",PeriodType.MONTHLY)):
            a=getattr(self,n)
            if not isinstance(a,MoneyManagementPeriodAggregate): raise TypeError(f"{n} required")
            if a.period.period_type is not typ or a.currency!=self.currency or a.period.timezone_name!="UTC": raise ValueError("period aggregate mismatch")
            if not a.period.contains(self.evaluated_at): raise ValueError("evaluated_at outside period")
        if self.equity_snapshot.currency!=self.currency: raise ValueError("currency mismatch")
        object.__setattr__(self,"cash_flow_adjustment_state",CashFlowAdjustmentState(self.cash_flow_adjustment_state))
    def to_dict(self): return _ser(self)
@dataclass(frozen=True)
class MoneyManagementPeriodLossEvaluation:
    period_type: PeriodType
    period_key: str
    starting_equity: Decimal
    net_realized_pnl: Decimal
    loss_amount: Decimal
    loss_percent: Decimal
    warning_threshold: Decimal
    block_threshold: Decimal
    threshold_state: ThresholdState
    decision: ActionDecision
    reason: LossReason
    evaluated_at: datetime
    def to_dict(self): return _ser(self)
@dataclass(frozen=True)
class MoneyManagementLossDecision:
    schema_version: str
    evaluated_at: datetime
    currency: str
    risk_state: RiskState
    action: ActionDecision
    primary_reason: LossReason
    reasons: Tuple[LossReason,...]
    daily_evaluation: MoneyManagementPeriodLossEvaluation
    weekly_evaluation: MoneyManagementPeriodLossEvaluation
    monthly_evaluation: MoneyManagementPeriodLossEvaluation
    drawdown_percent: Optional[Decimal]
    negative_equity: bool
    cash_flow_adjustment_state: CashFlowAdjustmentState
    fail_closed: bool
    explanation: str
    def __post_init__(self):
        if self.schema_version!="money-management-loss-decision/v1": raise ValueError("unsupported schema")
        object.__setattr__(self,"evaluated_at",_dt(self.evaluated_at))
        object.__setattr__(self,"risk_state",RiskState(self.risk_state)); object.__setattr__(self,"action",ActionDecision(self.action)); object.__setattr__(self,"primary_reason",LossReason(self.primary_reason)); object.__setattr__(self,"cash_flow_adjustment_state",CashFlowAdjustmentState(self.cash_flow_adjustment_state))
        if not self.reasons or len(set(self.reasons))!=len(self.reasons): raise ValueError("reasons must be unique")
        if self.drawdown_percent is not None: _d("drawdown_percent",self.drawdown_percent)
    def to_dict(self): return _ser(self)
