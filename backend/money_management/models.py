"""Strict, side-effect-free MM-1A data contracts."""
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple
from .enums import *

def _dec(name, value, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, Decimal): raise TypeError(f"{name} must be Decimal")
    if not value.is_finite(): raise ValueError(f"{name} must be finite")
    if positive and value <= 0: raise ValueError(f"{name} must be > 0")
    if nonnegative and value < 0: raise ValueError(f"{name} must be >= 0")
    return value
def _pct(name,value,positive=False):
    value=_dec(name,value,positive=positive)
    if value>Decimal("100"): raise ValueError(f"{name} must be <= 100")
    return value
def _dt(name,value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None: raise TypeError(f"{name} must be timezone-aware datetime")
    return value.astimezone(timezone.utc)
def _enum(cls,value):
    if isinstance(value,cls): return value
    if not isinstance(value,str): raise TypeError(f"{cls.__name__} must be an exact string")
    try: return cls(value)
    except ValueError as exc: raise ValueError(f"invalid {cls.__name__}: {value}") from exc

@dataclass(frozen=True)
class MoneyManagementConfig:
    profile: MoneyManagementProfile
    mode: TradingMode
    initial_reference_equity: Decimal
    risk_per_trade_pct: Decimal
    maximum_position_notional: Decimal
    maximum_drawdown_pct: Decimal
    total_exposure_pct: Decimal
    single_symbol_exposure_pct: Decimal
    maximum_leverage: Decimal
    multi_bot_enabled: bool
    daily_loss_warning_pct: Decimal=Decimal("1.00")
    daily_loss_block_pct: Decimal=Decimal("1.50")
    weekly_loss_warning_pct: Decimal=Decimal("2.00")
    weekly_loss_block_pct: Decimal=Decimal("3.00")
    monthly_loss_warning_pct: Decimal=Decimal("3.00")
    monthly_loss_block_pct: Decimal=Decimal("4.00")
    profit_lock_start_pct: Decimal=Decimal("1.00")
    initial_cooldown_minutes: Decimal=Decimal("30")
    extended_cooldown_hours: Decimal=Decimal("12")
    recovery_25_multiplier: Decimal=Decimal("0.25")
    recovery_50_multiplier: Decimal=Decimal("0.50")
    compounding_enabled: bool=False
    def __post_init__(self):
        object.__setattr__(self,"profile",_enum(MoneyManagementProfile,self.profile)); object.__setattr__(self,"mode",_enum(TradingMode,self.mode))
        if type(self.multi_bot_enabled) is not bool: raise TypeError("multi_bot_enabled must be bool")
        if type(self.compounding_enabled) is not bool: raise TypeError("compounding_enabled must be bool")
        for n in ("initial_reference_equity","maximum_position_notional"): _dec(n,getattr(self,n),positive=True)
        for n in ("risk_per_trade_pct","maximum_drawdown_pct","total_exposure_pct","single_symbol_exposure_pct","daily_loss_warning_pct","daily_loss_block_pct","weekly_loss_warning_pct","weekly_loss_block_pct","monthly_loss_warning_pct","monthly_loss_block_pct","profit_lock_start_pct"): _pct(n,getattr(self,n),positive=True)
        _dec("maximum_leverage",self.maximum_leverage,positive=True)
        if self.maximum_leverage>Decimal("5"): raise ValueError("maximum_leverage must be <= 5")
        if self.single_symbol_exposure_pct>self.total_exposure_pct: raise ValueError("single-symbol exposure exceeds total")
        if self.maximum_position_notional>self.initial_reference_equity*self.single_symbol_exposure_pct/100: raise ValueError("position exceeds reference symbol exposure")
        if self.daily_loss_warning_pct>=self.daily_loss_block_pct or self.weekly_loss_warning_pct>=self.weekly_loss_block_pct or self.monthly_loss_warning_pct>=self.monthly_loss_block_pct: raise ValueError("warning must be below block")
        if self.daily_loss_block_pct>=self.weekly_loss_block_pct or self.weekly_loss_block_pct>self.monthly_loss_block_pct or self.monthly_loss_block_pct>=self.maximum_drawdown_pct: raise ValueError("loss-limit order invalid")
        if self.recovery_25_multiplier>=self.recovery_50_multiplier or self.recovery_50_multiplier>=1: raise ValueError("recovery order invalid")
        for n in ("initial_cooldown_minutes","extended_cooldown_hours"): _dec(n,getattr(self,n),nonnegative=True)
    def to_dict(self): return _serialize(self)

@dataclass(frozen=True)
class MoneyManagementDecisionInput:
    request_id: str
    evaluated_at: datetime
    symbol: str
    requested_size: Decimal
    requested_notional: Decimal
    entry_price: Decimal
    stop_loss_price: Decimal
    account_equity: Decimal
    eligible_equity: Decimal
    governance_allowed: bool
    side: Optional[str]=None
    requested_leverage: Optional[Decimal]=None
    current_drawdown_pct: Optional[Decimal]=None
    period_loss_pct: Optional[Decimal]=None
    current_total_exposure: Optional[Decimal]=None
    current_symbol_exposure: Optional[Decimal]=None
    def __post_init__(self):
        if not isinstance(self.request_id,str) or not self.request_id: raise ValueError("request_id required")
        if not isinstance(self.symbol,str) or not self.symbol: raise ValueError("symbol required")
        object.__setattr__(self,"evaluated_at",_dt("evaluated_at",self.evaluated_at))
        if type(self.governance_allowed) is not bool: raise TypeError("governance_allowed must be bool")
        for n in ("requested_size","requested_notional","entry_price","stop_loss_price","account_equity","eligible_equity"): _dec(n,getattr(self,n),nonnegative=n.startswith("requested"))
        if self.entry_price<=0: raise ValueError("entry_price must be > 0")
        if self.stop_loss_price<=0 or self.stop_loss_price==self.entry_price: raise ValueError("invalid stop_loss_price")
        for n in ("requested_leverage","current_drawdown_pct","period_loss_pct","current_total_exposure","current_symbol_exposure"):
            if getattr(self,n) is not None: _dec(n,getattr(self,n),nonnegative=True)
        if self.side is not None and self.side not in ("BUY","SELL","HOLD"): raise ValueError("invalid side")
    def to_dict(self): return _serialize(self)

@dataclass(frozen=True)
class MoneyManagementDecisionOutput:
    schema_version: str
    decision_id: str
    request_id: str
    evaluated_at: datetime
    approved_size: Decimal
    approved_notional: Decimal
    risk_amount: Decimal
    risk_allowed: bool
    risk_block_reason: RiskBlockReason
    risk_state: RiskState
    warnings: Tuple[str,...]=()
    def __post_init__(self):
        if not self.schema_version or not isinstance(self.decision_id,str) or not isinstance(self.request_id,str): raise ValueError("schema and ids required")
        object.__setattr__(self,"evaluated_at",_dt("evaluated_at",self.evaluated_at))
        for n in ("approved_size","approved_notional","risk_amount"): _dec(n,getattr(self,n),nonnegative=True)
        if type(self.risk_allowed) is not bool: raise TypeError("risk_allowed must be bool")
        object.__setattr__(self,"risk_block_reason",_enum(RiskBlockReason,self.risk_block_reason)); object.__setattr__(self,"risk_state",_enum(RiskState,self.risk_state))
        if not self.risk_allowed and (self.approved_size!=0 or self.approved_notional!=0): raise ValueError("blocked output must be zero-sized")
        if self.risk_allowed and self.risk_block_reason!=RiskBlockReason.NONE: raise ValueError("allowed output cannot have block reason")
    def to_dict(self): return _serialize(self)

@dataclass(frozen=True)
class MoneyManagementRuntimeState:
    schema_version: str
    profile: MoneyManagementProfile
    reference_equity: Decimal
    high_water_mark: Decimal
    current_drawdown_pct: Decimal
    risk_state: RiskState
    updated_at: datetime
    period_start: Optional[datetime]=None
    period_realized_pnl: Optional[Decimal]=None
    cooldown_state: CooldownState=CooldownState.INACTIVE
    recovery_state: RecoveryState=RecoveryState.NOT_REQUIRED
    cooldown_started_at: Optional[datetime]=None
    cooldown_ends_at: Optional[datetime]=None
    last_decision_id: Optional[str]=None
    def __post_init__(self):
        if not self.schema_version: raise ValueError("schema_version required")
        object.__setattr__(self,"profile",_enum(MoneyManagementProfile,self.profile)); object.__setattr__(self,"risk_state",_enum(RiskState,self.risk_state)); object.__setattr__(self,"cooldown_state",_enum(CooldownState,self.cooldown_state)); object.__setattr__(self,"recovery_state",_enum(RecoveryState,self.recovery_state))
        for n in ("reference_equity","high_water_mark"): _dec(n,getattr(self,n),positive=True)
        _pct("current_drawdown_pct",self.current_drawdown_pct)
        object.__setattr__(self,"updated_at",_dt("updated_at",self.updated_at))
        for n in ("period_start","cooldown_started_at","cooldown_ends_at"):
            if getattr(self,n) is not None: object.__setattr__(self,n,_dt(n,getattr(self,n)))
        if self.cooldown_state is CooldownState.ACTIVE and self.cooldown_ends_at is None: raise ValueError("active cooldown requires end")
    def to_dict(self): return _serialize(self)

def _serialize(value):
    if isinstance(value,Enum): return value.value
    if isinstance(value,Decimal): return format(value,"f")
    if isinstance(value,datetime): return value.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    if isinstance(value,tuple): return [_serialize(v) for v in value]
    if hasattr(value,"__dataclass_fields__"): return {f.name:_serialize(getattr(value,f.name)) for f in fields(value)}
    return value
