from dataclasses import dataclass, field
from typing import List
import datetime
import logging

# =====================================================
# 修正版 BotLogger
# =====================================================
class BotLogger:
    def __init__(self, name="Bot"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            ch.setFormatter(formatter)
            self.logger.addHandler(ch)

    def get_logger(self):
        """ TradeCore が使用する get_logger メソッド """
        return self.logger

# =====================================================
# ポジション情報
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
# 戦略 → Core への注文コンテキスト
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
# 資金管理・DD制御コア
# =====================================================
class TradeCore:

    def __init__(
        self,
        initial_balance: float = 10000,
        is_live: bool = False,
        logger: BotLogger | None = None,
        execution_engine=None
    ):

        self.is_live = is_live
        # ← ここを get_logger() で安全に取得
        self.logger = logger.get_logger() if logger else BotLogger("TradeCore").get_logger()

        self.execution_engine = execution_engine

        self.initial_balance = initial_balance
        self.equity = initial_balance
        self.max_equity = initial_balance
        self.day_start_balance = initial_balance

        self.account_frozen = False
        self.freeze_reason = None

        self.positions: List[Position] = []
        self.max_concurrent_positions = 5

        self.strategy_wrapper = None

    # =====================================================
    # エントリー受付（🔥追加）
    # =====================================================
    def try_enter(self, ctx: StrategyContext) -> bool:

        if not self.can_trade():
            self.logger.warning("Account frozen, skip entry")
            return False

        return self.open_position(
            trade_type=ctx.trade_type,
            price=ctx.entry_price,
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            volume=1.0,
            symbol="BTCUSDT"
        )

    # =====================================================
    # エントリー可否
    # =====================================================
    def can_trade(self) -> bool:
        return not self.account_frozen

    # =====================================================
    # ポジションオープン
    # =====================================================
    def open_position(
        self,
        trade_type: str,
        price: float,
        sl: float,
        tp: float,
        volume: float = 1.0,
        symbol: str = "BTCUSDT"
    ) -> bool:

        trade_type_upper = trade_type.upper()

        if trade_type_upper not in ["BUY", "SELL"]:
            self.logger.error(f"Invalid trade_type: {trade_type}")
            return False

        if not self.can_trade():
            return False

        if len(self.positions) >= self.max_concurrent_positions:
            self.logger.warning("Max positions reached")
            return False

        pos = Position(
            entry_price=price,
            trade_type=trade_type_upper,
            sl=sl,
            tp=tp,
            volume=volume,
            entry_time=datetime.datetime.now(),
            symbol=symbol
        )

        self.positions.append(pos)

        self.logger.info(f"🔥 ENTRY {trade_type_upper} @ {price} SL:{sl} TP:{tp}")

        # 本番発注
        if self.execution_engine and self.is_live:
            self.execution_engine.place_order(
                symbol=symbol,
                side=trade_type_upper,
                order_type="MARKET",
                quantity=volume,
                price=price,
                sl=sl,
                tp=tp
            )

        return True

    # =====================================================
    # ポジション更新（SL/TP）
    # =====================================================
    def update_positions(self, price_dict: dict):

        remaining = []

        for pos in self.positions:
            price = price_dict.get(pos.symbol)

            if price is None:
                remaining.append(pos)
                continue

            closed = False

            if pos.trade_type == "BUY":
                if price <= pos.sl:
                    self.logger.info(f"❌ SL HIT @ {price}")
                    closed = True
                elif price >= pos.tp:
                    self.logger.info(f"✅ TP HIT @ {price}")
                    closed = True

            elif pos.trade_type == "SELL":
                if price >= pos.sl:
                    self.logger.info(f"❌ SL HIT @ {price}")
                    closed = True
                elif price <= pos.tp:
                    self.logger.info(f"✅ TP HIT @ {price}")
                    closed = True

            if not closed:
                remaining.append(pos)

        self.positions = remaining

    # =====================================================
    # 状態確認
    # =====================================================
    def get_status(self):
        return {
            "equity": self.equity,
            "account_frozen": self.account_frozen,
            "is_live": self.is_live,
            "open_positions": len(self.positions)
        }