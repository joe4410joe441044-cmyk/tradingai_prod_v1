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

    # =====================================================
    # ⭐ これを追加（今回のエラー解決ポイント）
    # =====================================================
    @safe_run
    def on_position_opened(self, position: dict):
        """
        ExecutionEngine → TradeCore の橋渡し
        実質：ポジション同期用フック
        """
        print("[TradeCore] on_position_opened called")

        pos = Position(
            entry_price=position["entry_price"],
            trade_type=position["side"],
            sl=position.get("sl", 0),
            tp=position.get("tp", 0),
            volume=position.get("volume", 0.001),
            entry_time=datetime.datetime.now(),
            symbol=position.get("symbol", "BTCUSDT"),
            status="open"
        )

        self.positions.append(pos)

    # --------------------------
    # CLOSE判定
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

            if pos.trade_type == "BUY":

                if price <= pos.sl:
                    print("[CLOSE] SL HIT")
                    pos.close_price = price
                    pos.status = "closed"

                elif price >= pos.tp:
                    print("[CLOSE] TP HIT")
                    pos.close_price = price
                    pos.status = "closed"

            elif pos.trade_type == "SELL":

                if price >= pos.sl:
                    print("[CLOSE] SL HIT")
                    pos.close_price = price
                    pos.status = "closed"

                elif price <= pos.tp:
                    print("[CLOSE] TP HIT")
                    pos.close_price = price
                    pos.status = "closed"