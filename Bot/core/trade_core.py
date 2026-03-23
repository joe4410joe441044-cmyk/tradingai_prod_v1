# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import List
import datetime
import logging


# =====================================================
# BotLogger
# =====================================================
class BotLogger:

    def __init__(self, name="Bot"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)

    def get_logger(self):
        return self.logger


# =====================================================
# Position
# =====================================================
@dataclass
class Position:
    entry_price: float
    trade_type: str
    sl: float
    tp: float
    volume: float
    entry_time: datetime.datetime
    symbol: str = "BTCUSDT"


# =====================================================
# StrategyContext
# =====================================================
@dataclass
class StrategyContext:
    strategy_name: str
    trade_type: str
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    partial_close_percent: float = 0
    reason: str = ""
    extra: dict = field(default_factory=dict)


# =====================================================
# TradeCore（統合版）
# =====================================================
class TradeCore:

    def __init__(self, execution_engine=None, logger=None, initial_balance=10000):
        print(">>> TradeCore INIT CALLED")

        self.logger = logger if logger else BotLogger().get_logger()
        self.execution_engine = execution_engine

        self.positions: List[Position] = []
        self.max_concurrent_positions = 5

    # --------------------------
    # Entry（Strategy → ここ）
    # --------------------------
    def try_enter(self, ctx: StrategyContext):

        if len(self.positions) >= self.max_concurrent_positions:
            self.logger.warning("Max positions reached")
            return False

        # ① 内部ポジション記録（従来機能）
        self.open_position(
            trade_type=ctx.trade_type,
            price=ctx.entry_price,
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            symbol="BTCUSDT"
        )

        # ② ExecutionEngineへ流す（新構造）
        if self.execution_engine:
            signal = {
                "symbol": "BTCUSDT",
                "side": ctx.trade_type,
                "qty": 0.001,  # 仮（後でロット管理）
                "price": ctx.entry_price
            }

            print("[TradeCore] Sending signal:", signal)

            return self.execution_engine.send_signal(signal)

        return True

    # --------------------------
    def open_position(self, trade_type, price, sl, tp, volume=1.0, symbol="BTCUSDT"):

        trade_type = str(trade_type).upper()

        pos = Position(
            entry_price=price,
            trade_type=trade_type,
            sl=sl,
            tp=tp,
            volume=volume,
            entry_time=datetime.datetime.now(),
            symbol=symbol
        )

        self.positions.append(pos)

        self.logger.info(f"ENTRY {trade_type} @ {price} SL:{sl} TP:{tp}")
        return True

    # --------------------------
    # SL / TP 管理
    # --------------------------
    def update_positions(self, price_dict):

        if not isinstance(price_dict, dict):
            return

        remaining = []

        for pos in self.positions:

            price = price_dict.get(pos.symbol)

            if price is None:
                remaining.append(pos)
                continue

            closed = False

            if pos.trade_type == "BUY":
                if price <= pos.sl:
                    self.logger.info(f"SL HIT @ {price}")
                    closed = True
                elif price >= pos.tp:
                    self.logger.info(f"TP HIT @ {price}")
                    closed = True

            elif pos.trade_type == "SELL":
                if price >= pos.sl:
                    self.logger.info(f"SL HIT @ {price}")
                    closed = True
                elif price <= pos.tp:
                    self.logger.info(f"TP HIT @ {price}")
                    closed = True

            else:
                self.logger.warning(f"Unknown trade_type: {pos.trade_type}")

            if not closed:
                remaining.append(pos)

        self.positions = remaining

    # --------------------------
    def check_orders(self, price_dict):
        self.update_positions(price_dict)