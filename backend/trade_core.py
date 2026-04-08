# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import List
import datetime
import logging
import time

from Bot.utils.safety import safe_run


@dataclass
class Position:
    entry_price: float
    trade_type: str
    sl: float
    tp: float
    volume: float
    entry_time: datetime.datetime
    symbol: str = "BTCUSDT"
    status: str = "open"
    close_price: float = None
    partial_closed_volume: float = 0


@dataclass
class StrategyContext:
    strategy_name: str
    trade_type: str
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    volume: float = 0.001
    fvg_signal: bool = False
    partial_close_pct: float = 0.5


class TradeCore:

    def __init__(self, execution_engine=None, logger=None):
        print(">>> TradeCore INIT CALLED")

        self.logger = logger or logging.getLogger("TradeCore")
        self.execution_engine = execution_engine
        self.positions: List[Position] = []

        self.max_concurrent_positions = 2
        self.last_entry_time = {}
        self.entry_cooldown = 5

    @safe_run
    def try_enter(self, ctx: StrategyContext = None, **kwargs):
        # 🔥 ここが今回の修正ポイント
        if ctx is None:
            ctx = StrategyContext(**kwargs)

        now = time.time()
        last_time = self.last_entry_time.get(ctx.strategy_name, 0)
        if now - last_time < self.entry_cooldown:
            return

        open_positions = [
            p for p in self.positions
            if p.symbol == "BTCUSDT" and p.trade_type == ctx.trade_type and p.status == "open"
        ]
        if len(open_positions) >= self.max_concurrent_positions:
            print("[TradeCore] Max positions reached → skip")
            return

        adjusted_entry = ctx.entry_price
        if ctx.fvg_signal:
            adjusted_entry *= 0.999 if ctx.trade_type == "SELL" else 1.001

        signal = {
            "symbol": "BTCUSDT",
            "side": ctx.trade_type,
            "qty": ctx.volume,
            "price": adjusted_entry,
            "sl": ctx.stop_loss_price,
            "tp": ctx.take_profit_price
        }

        if self.execution_engine:
            self.execution_engine.execute_order(signal)

        pos = Position(
            entry_price=adjusted_entry,
            trade_type=ctx.trade_type,
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            volume=ctx.volume,
            entry_time=datetime.datetime.now()
        )

        self.positions.append(pos)
        self.last_entry_time[ctx.strategy_name] = time.time()
        print(f"ENTRY {pos.trade_type} @ {pos.entry_price}")

    @safe_run
    def check_orders(self, price_dict):
        for pos in self.positions:
            if pos.status != "open":
                continue

            price = price_dict.get(pos.symbol)
            if price is None:
                continue

            if pos.trade_type == "BUY":
                if price <= pos.sl:
                    self._close_position(pos, price)
                elif price >= pos.tp:
                    self._partial_or_full_close(pos, price)
            elif pos.trade_type == "SELL":
                if price >= pos.sl:
                    self._close_position(pos, price)
                elif price <= pos.tp:
                    self._partial_or_full_close(pos, price)

    def _partial_or_full_close(self, pos: Position, price: float):
        if pos.volume > 0.001:
            partial_vol = pos.volume * 0.5
            pos.partial_closed_volume += partial_vol
            pos.volume -= partial_vol
            print(f"[PARTIAL CLOSE] {partial_vol} @ {price}, remaining vol={pos.volume}")
        else:
            self._close_position(pos, price)

    def _close_position(self, pos: Position, price: float):
        pos.close_price = price
        pos.status = "closed"
        print(f"[CLOSED] {pos.trade_type} @ {price}")

    def calc_pnl(self, price_dict):
        total_pnl = 0
        for pos in self.positions:
            current_price = price_dict.get(pos.symbol, pos.entry_price)
            if pos.status == "closed":
                pnl = (pos.close_price - pos.entry_price) * pos.volume
                if pos.trade_type == "SELL":
                    pnl *= -1
            else:
                pnl = (current_price - pos.entry_price) * pos.volume
                if pos.trade_type == "SELL":
                    pnl *= -1
            total_pnl += pnl
        return total_pnl

    def summary(self, price_dict):
        print("\n===== POSITION SUMMARY =====")
        for pos in self.positions:
            current_price = price_dict.get(pos.symbol, pos.entry_price)
            pnl = (pos.close_price - pos.entry_price) * pos.volume if pos.status == "closed" else (current_price - pos.entry_price) * pos.volume
            if pos.trade_type == "SELL":
                pnl *= -1
            print(f"{pos.symbol} {pos.trade_type} | Entry={pos.entry_price} | Cur={current_price} | Vol={pos.volume} | Status={pos.status} | PnL={pnl:.6f}")
        print("============================\n")