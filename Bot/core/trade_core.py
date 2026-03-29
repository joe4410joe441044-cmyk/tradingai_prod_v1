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
    close_price: float = None  # 🔥 追加


@dataclass
class StrategyContext:
    strategy_name: str
    trade_type: str
    entry_price: float
    stop_loss_price: float
    take_profit_price: float


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
    def try_enter(self, ctx: StrategyContext):

        print("[TradeCore] try_enter called")

        now = time.time()
        if now - self.last_entry_time < self.entry_cooldown:
            return

        if len(self.positions) >= self.max_concurrent_positions:
            print("[TradeCore] Position exists → skip")
            return

        signal = {
            "symbol": "BTCUSDT",
            "side": ctx.trade_type,
            "qty": 0.001,
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
            volume=0.001,
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

            print(f"[POSITION] price={price} entry={pos.entry_price} sl={pos.sl} tp={pos.tp}")

            # ==========================
            # BUY
            # ==========================
            if pos.trade_type == "BUY":

                # SL
                if price <= pos.sl:
                    print("[CLOSE] SL HIT")
                    pos.close_price = price  # 🔥 追加
                    pos.status = "closed"

                # TP
                elif price >= pos.tp:
                    print("[CLOSE] TP HIT")
                    pos.close_price = price  # 🔥 追加
                    pos.status = "closed"

            # ==========================
            # SELL
            # ==========================
            elif pos.trade_type == "SELL":

                # SL
                if price >= pos.sl:
                    print("[CLOSE] SL HIT")
                    pos.close_price = price  # 🔥 追加
                    pos.status = "closed"

                # TP
                elif price <= pos.tp:
                    print("[CLOSE] TP HIT")
                    pos.close_price = price  # 🔥 追加
                    pos.status = "closed"