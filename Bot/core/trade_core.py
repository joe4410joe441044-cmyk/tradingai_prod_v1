# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import List
import datetime
import logging
import time

# ★追加：安全ラッパー
from Bot.utils.safety import safe_run, safe_task


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
    status: str = "open"  # open / closed


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
# TradeCore（本番向け統合版）
# =====================================================
class TradeCore:

    def __init__(self, execution_engine=None, logger=None, initial_balance=10000):
        print(">>> TradeCore INIT CALLED")

        self.logger = logger if logger else BotLogger().get_logger()
        self.execution_engine = execution_engine

        self.positions: List[Position] = []

        # ★変更：無限エントリー防止
        self.max_concurrent_positions = 1

        # ★追加：クールダウン制御
        self.entry_cooldown = 5  # 秒（調整OK）
        self.last_entry_time = 0

    # --------------------------
    # Entry（Strategy → ここ）
    # --------------------------
    @safe_run  # ★追加：絶対に落ちない
    def try_enter(self, ctx: StrategyContext):

        # ★追加：クールダウンチェック
        now = time.time()
        if now - self.last_entry_time < self.entry_cooldown:
            self.logger.info("Entry cooldown active")
            return False

        if not self.can_open_position():
            self.logger.warning("Max positions reached")
            return False

        # 内部ポジション記録
        pos = self.create_position(ctx)

        # ★追加：エントリー時間更新
        self.last_entry_time = time.time()

        # ExecutionEngineへ流す（発注準備）
        if self.execution_engine:
            signal = {
                "symbol": pos.symbol,
                "side": pos.trade_type,
                "qty": pos.volume,
                "price": pos.entry_price
            }

            self.logger.info(f"[TradeCore] Sending signal to ExecutionEngine: {signal}")

            # ★安全化：非同期でも絶対止まらない
            if hasattr(self.execution_engine, "execute_order"):
                safe_task(self.execution_engine.execute_order(signal))
                return True
            else:
                return self.execution_engine.send_signal(signal)

        return True

    # --------------------------
    # 建玉作成・管理
    # --------------------------
    def can_open_position(self):
        return len([p for p in self.positions if p.status == "open"]) < self.max_concurrent_positions

    def create_position(self, ctx: StrategyContext):
        pos = Position(
            entry_price=ctx.entry_price,
            trade_type=ctx.trade_type.upper(),
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            volume=0.001,  # 仮ロット、後で資金管理に対応
            entry_time=datetime.datetime.now(),
            symbol="BTCUSDT",
            status="open"
        )
        self.positions.append(pos)
        self.logger.info(f"ENTRY {pos.trade_type} @ {pos.entry_price} SL:{pos.sl} TP:{pos.tp}")
        return pos

    # --------------------------
    # SL / TP 判定
    # --------------------------
    def check_close_condition(self, pos: Position, price: float):
        if pos.status != "open":
            return False

        if pos.trade_type == "BUY":
            if price <= pos.sl or price >= pos.tp:
                return True
        elif pos.trade_type == "SELL":
            if price >= pos.sl or price <= pos.tp:
                return True
        return False

    @safe_run  # ★追加：決済も落ちない
    def close_position(self, pos: Position, reason=""):
        if pos.status == "closed":
            return

        pos.status = "closed"
        self.logger.info(f"CLOSE {pos.trade_type} @ {pos.entry_price} Reason: {reason}")

        # ★追加：ExecutionEngineへ決済も流す
        if self.execution_engine and hasattr(self.execution_engine, "prepare_close_order"):
            try:
                self.execution_engine.prepare_close_order(pos)
            except Exception as e:
                self.logger.error(f"Close order error: {e}")

    # --------------------------
    # 定期チェック用（価格dict形式）
    # --------------------------
    @safe_run  # ★追加：ここも止まらない
    def update_positions(self, price_dict):
        if not isinstance(price_dict, dict):
            return

        for pos in self.positions:
            price = price_dict.get(pos.symbol)
            if price is None:
                continue

            if self.check_close_condition(pos, price):
                reason = "SL" if (pos.trade_type=="BUY" and price<=pos.sl) or (pos.trade_type=="SELL" and price>=pos.sl) else "TP"
                self.close_position(pos, reason=reason)

    def check_orders(self, price_dict):
        self.update_positions(price_dict)