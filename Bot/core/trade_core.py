# -*- coding: utf-8 -*-

from dataclasses import dataclass
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


@dataclass
class StrategyContext:
    # 🔥 kwargs対応のためデフォルト値を必ず付ける
    strategy_name: str = "default"
    trade_type: str = "BUY"
    entry_price: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    volume: float = 0.001


class TradeCore:

    def __init__(self, execution_engine=None, logger=None):
        print(">>> TradeCore INIT CALLED")

        self.logger = logger or logging.getLogger("TradeCore")
        self.execution_engine = execution_engine
        self.positions: List[Position] = []

        self.max_concurrent_positions = 1
        self.last_entry_time = 0
        self.entry_cooldown = 5

    @safe_run
    def try_enter(self, ctx: StrategyContext = None, **kwargs):

        print("[TradeCore] try_enter called")

        # 🔥 kwargs対応（最重要）
        if ctx is None:
            ctx = StrategyContext(**kwargs)

        now = time.time()
        if now - self.last_entry_time < self.entry_cooldown:
            return

        if len(self.positions) >= self.max_concurrent_positions:
            print("[TradeCore] Position exists → skip")
            return

        signal = {
            "symbol": "BTCUSDT",
            "side": ctx.trade_type,
            "qty": ctx.volume,
            "price": ctx.entry_price,
            "sl": ctx.stop_loss_price,
            "tp": ctx.take_profit_price
        }

        print(f"[EXECUTION] Processing signal: {signal}")

        if self.execution_engine:
            self.execution_engine.execute_order(signal)

        # ポジション作成
        pos = Position(
            entry_price=ctx.entry_price,
            trade_type=ctx.trade_type,
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            volume=ctx.volume,
            entry_time=datetime.datetime.now()
        )

        self.positions.append(pos)

        print(f"ENTRY {pos.trade_type} @ {pos.entry_price}")

        self.last_entry_time = time.time()

    # --------------------------
    # 本番用 CLOSE判定
    # --------------------------
    @safe_run
    def check_orders(self, price_dict):

        for pos in self.positions:

            if pos.status != "open":
                continue

            price = price_dict.get(pos.symbol)

            if price is None:
                continue

            print(f"[POSITION] price={price} entry={pos.entry_price} sl={pos.sl} tp={pos.tp}")

            # BUY
            if pos.trade_type == "BUY":

                if price <= pos.sl:
                    print("[CLOSE] SL HIT")
                    pos.close_price = price
                    pos.status = "closed"

                elif price >= pos.tp:
                    print("[CLOSE] TP HIT")
                    pos.close_price = price
                    pos.status = "closed"

            # SELL
            elif pos.trade_type == "SELL":

                if price >= pos.sl:
                    print("[CLOSE] SL HIT")
                    pos.close_price = price
                    pos.status = "closed"

                elif price <= pos.tp:
                    print("[CLOSE] TP HIT")
                    pos.close_price = price
                    pos.status = "closed"