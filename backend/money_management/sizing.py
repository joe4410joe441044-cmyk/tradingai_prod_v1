"""Pure Decimal sizing primitives. No I/O, state mutation, or engine integration."""
from decimal import Decimal, InvalidOperation
from .models import MoneyManagementConfig, MoneyManagementDecisionInput
from .enums import RiskBlockReason
def _zero(): return Decimal("0")
def _fail(reason): return (None, reason)
def stop_distance(inp):
    if inp.side == "BUY": return inp.entry_price - inp.stop_loss_price
    if inp.side == "SELL": return inp.stop_loss_price - inp.entry_price
    return None
def evaluate_sizing(inp: MoneyManagementDecisionInput, cfg: MoneyManagementConfig):
    """Return (risk_amount, approved_size, approved_notional, allowed, reason, state)."""
    from .enums import RiskState
    zero=_zero()
    if not isinstance(inp, MoneyManagementDecisionInput) or not isinstance(cfg, MoneyManagementConfig):
        return zero,zero,zero,False,RiskBlockReason.INSUFFICIENT_DATA,RiskState.LOCKED
    if not inp.governance_allowed:
        return zero,zero,zero,False,RiskBlockReason.INSUFFICIENT_DATA,RiskState.LOCKED
    if inp.side == "HOLD":
        return zero,zero,zero,False,RiskBlockReason.INSUFFICIENT_DATA,RiskState.LOCKED
    equity=inp.eligible_equity
    if equity <= 0: return zero,zero,zero,False,RiskBlockReason.INVALID_EQUITY,RiskState.LOCKED
    if cfg.risk_per_trade_pct <= 0: return zero,zero,zero,False,RiskBlockReason.INSUFFICIENT_DATA,RiskState.LOCKED
    if inp.requested_leverage is not None and (inp.requested_leverage <= 0 or inp.requested_leverage > cfg.maximum_leverage):
        return zero,zero,zero,False,RiskBlockReason.MAXIMUM_LEVERAGE,RiskState.LOCKED
    distance=stop_distance(inp)
    if distance is None or distance <= 0:
        return zero,zero,zero,False,RiskBlockReason.INVALID_STOP,RiskState.LOCKED
    risk_amount=equity*cfg.risk_per_trade_pct/Decimal("100")
    raw_size=risk_amount/distance
    raw_notional=raw_size*inp.entry_price
    symbol_limit=equity*cfg.single_symbol_exposure_pct/Decimal("100")
    total_limit=equity*cfg.total_exposure_pct/Decimal("100")
    symbol_capacity=symbol_limit-(inp.current_symbol_exposure or zero)
    total_capacity=total_limit-(inp.current_total_exposure or zero)
    if symbol_capacity <= 0: return risk_amount,zero,zero,False,RiskBlockReason.SYMBOL_EXPOSURE_LIMIT,RiskState.LOCKED
    if total_capacity <= 0: return risk_amount,zero,zero,False,RiskBlockReason.TOTAL_EXPOSURE_LIMIT,RiskState.LOCKED
    approved_notional=min(raw_notional,cfg.maximum_position_notional,symbol_capacity,total_capacity,inp.requested_notional)
    if approved_notional <= 0: return risk_amount,zero,zero,False,RiskBlockReason.MAXIMUM_POSITION,RiskState.LOCKED
    approved_size=approved_notional/inp.entry_price
    if approved_notional < raw_notional:
        return risk_amount,approved_size,approved_notional,True,RiskBlockReason.NONE,RiskState.DEFENSIVE
    return risk_amount,approved_size,approved_notional,True,RiskBlockReason.NONE,RiskState.NORMAL
