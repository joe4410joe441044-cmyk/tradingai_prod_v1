from dataclasses import dataclass, field
from typing import List
import datetime

from Bot.utils.logger import BotLogger


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
        logger: BotLogger | None = None
    ):

        self.is_live = is_live
        self.logger = logger if logger else BotLogger()

        self.initial_balance = initial_balance
        self.equity = initial_balance
        self.max_equity = initial_balance
        self.day_start_balance = initial_balance

        self.max_daily_dd_percent = 4.0
        self.max_total_dd_percent = 6.0
        self.max_peak_dd_percent = 8.0

        self.account_frozen = False
        self.freeze_reason = None

        self.positions: List[Position] = []
        self.max_concurrent_positions = 5

        self.current_date = datetime.datetime.now().date()

        self.strategy_wrapper = None

    # =====================================================
    # エントリー可否
    # =====================================================
    def can_trade(self) -> bool:
        return not self.account_frozen

    # =====================================================
    # ポジションオープン（StrategyWrapper互換）
    # =====================================================
    def open_position(self, trade_type, price, sl, tp, volume=1.0):

        if not self.can_trade():
            return False

        if len(self.positions) >= self.max_concurrent_positions:
            return False

        pos = Position(
            entry_price=price,
            trade_type=trade_type,
            sl=sl,
            tp=tp,
            volume=volume,
            entry_time=datetime.datetime.now()
        )

        self.positions.append(pos)

        print(
            f"[ENTRY] {trade_type} | "
            f"Entry: {price} | SL: {sl} | TP: {tp}"
        )

        return True

    # =====================================================
    # ポジション更新
    # =====================================================
    def update_positions(self, price=None):

        if price is None:
            return

        remaining = []

        for pos in self.positions:

            closed = False

            if pos.trade_type == "buy":

                if price <= pos.sl:
                    print("SL HIT")
                    closed = True

                elif price >= pos.tp:
                    print("TP HIT")
                    closed = True

            elif pos.trade_type == "sell":

                if price >= pos.sl:
                    print("SL HIT")
                    closed = True

                elif price <= pos.tp:
                    print("TP HIT")
                    closed = True

            if not closed:
                remaining.append(pos)

        self.positions = remaining

    # =====================================================
    # MarketEngine → Strategy
    # =====================================================
    def on_market_data(self, market_data):

        if not self.strategy_wrapper:
            return

        try:

            self.strategy_wrapper.on_bar(market_data)

        except Exception as e:
            print(f"Strategy execution error: {e}")

    # =====================================================
    # 状態確認
    # =====================================================
    def get_status(self):

        return {
            "equity": self.equity,
            "max_equity": self.max_equity,
            "account_frozen": self.account_frozen,
            "freeze_reason": self.freeze_reason,
            "is_live": self.is_live
        }
