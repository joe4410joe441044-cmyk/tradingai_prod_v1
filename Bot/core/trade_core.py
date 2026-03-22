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
# 繝昴ず繧ｷ繝ｧ繝ｳ
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
# TradeCore
# =====================================================
class TradeCore:

    def __init__(self, initial_balance=10000, logger=None):
        # 笨・logger邨ｱ荳・井ｻ雁屓縺ｮ譛ｬ雉ｪ・・
        self.logger = logger if logger else BotLogger().get_logger()

        self.positions: List[Position] = []
        self.max_concurrent_positions = 5

    # --------------------------
    # 繧ｨ繝ｳ繝医Μ繝ｼ
    # --------------------------
    def try_enter(self, ctx: StrategyContext):

        if len(self.positions) >= self.max_concurrent_positions:
            self.logger.warning("Max positions reached")
            return False

        return self.open_position(
            trade_type=ctx.trade_type,
            price=ctx.entry_price,
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            symbol="BTCUSDT"
        )

    # --------------------------
    def open_position(self, trade_type, price, sl, tp, volume=1.0, symbol="BTCUSDT"):

        trade_type = str(trade_type).upper()  # 櫨 蠑ｷ蛻ｶ螳牙・蛹・

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

        self.logger.info(f"櫨 ENTRY {trade_type} @ {price} SL:{sl} TP:{tp}")
        return True

    # --------------------------
    # SL / TP 蛻､螳・
    # --------------------------
    def update_positions(self, price_dict):

        if not isinstance(price_dict, dict):  # 櫨 莠区腐髦ｲ豁｢
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
                    self.logger.info(f"笶・SL HIT @ {price}")
                    closed = True
                elif price >= pos.tp:
                    self.logger.info(f"笨・TP HIT @ {price}")
                    closed = True

            elif pos.trade_type == "SELL":
                if price >= pos.sl:
                    self.logger.info(f"笶・SL HIT @ {price}")
                    closed = True
                elif price <= pos.tp:
                    self.logger.info(f"笨・TP HIT @ {price}")
                    closed = True

            else:
                # 櫨 譛ｪ螳夂ｾｩ繧ｿ繧､繝玲､懷・・医ョ繝舌ャ繧ｰ雜・㍾隕・ｼ・
                self.logger.warning(f"Unknown trade_type: {pos.trade_type}")

            if not closed:
                remaining.append(pos)

        self.positions = remaining

    # --------------------------
    # 豕ｨ譁・メ繧ｧ繝・け・・ngine縺九ｉ蜻ｼ縺ｰ繧後ｋ・・
    # --------------------------
    def check_orders(self, price_dict):
        self.update_positions(price_dict)
