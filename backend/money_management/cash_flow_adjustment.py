"""Canonical cash-flow-adjusted equity math for Money Management."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CashFlowAdjustedEquity:
    current_equity: Decimal
    net_external_cash_flow: Decimal
    trading_pnl: Decimal
    adjusted_equity: Decimal
    adjusted_high_water_mark: Decimal
    drawdown_amount: Decimal
    drawdown_percent: Decimal


def reconcile_equity_change(*, previous_equity, current_equity, net_external_cash_flow,
                            previous_adjusted_equity, previous_adjusted_high_water_mark):
    values = (previous_equity, current_equity, net_external_cash_flow,
              previous_adjusted_equity, previous_adjusted_high_water_mark)
    if any(isinstance(v, bool) or not isinstance(v, Decimal) or not v.is_finite() for v in values):
        raise TypeError("finite Decimal inputs required")
    if previous_equity < 0 or current_equity < 0 or previous_adjusted_high_water_mark <= 0:
        raise ValueError("invalid equity input")
    trading_pnl = current_equity - previous_equity - net_external_cash_flow
    adjusted = previous_adjusted_equity + trading_pnl
    high = max(previous_adjusted_high_water_mark, adjusted)
    drawdown = max(Decimal("0"), high - adjusted)
    return CashFlowAdjustedEquity(current_equity, net_external_cash_flow, trading_pnl,
                                  adjusted, high, drawdown, drawdown / high * Decimal("100"))
