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
    trade_type: str  # BUY / SELL
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
        self.logger = logger if logger else BotLogger("TradeCore").get_logger()

        self.execution_engine = execution_engine

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
            self.logger.warning("Account is frozen, cannot open position")
            return False

        if len(self.positions) >= self.max_concurrent_positions:
            self.logger.warning("Max concurrent positions reached")
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

        self.logger.info(f"ENTRY {trade_type_upper} | {symbol} Entry:{price} SL:{sl} TP:{tp}")

        # ExecutionEngine 呼び出し
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
    # ポジション更新（SL/TPチェック）
    # =====================================================
    def update_positions(self, price_dict: dict):

        remaining = []

        for pos in self.positions:
            symbol_price = price_dict.get(pos.symbol)
            if symbol_price is None:
                remaining.append(pos)
                continue

            closed = False

            if pos.trade_type == "BUY":
                if symbol_price <= pos.sl:
                    self.logger.info(f"SL HIT | {pos.symbol} Entry:{pos.entry_price} SL:{pos.sl} TP:{pos.tp}")
                    closed = True
                elif symbol_price >= pos.tp:
                    self.logger.info(f"TP HIT | {pos.symbol} Entry:{pos.entry_price} SL:{pos.sl} TP:{pos.tp}")
                    closed = True
            elif pos.trade_type == "SELL":
                if symbol_price >= pos.sl:
                    self.logger.info(f"SL HIT | {pos.symbol} Entry:{pos.entry_price} SL:{pos.sl} TP:{pos.tp}")
                    closed = True
                elif symbol_price <= pos.tp:
                    self.logger.info(f"TP HIT | {pos.symbol} Entry:{pos.entry_price} SL:{pos.sl} TP:{pos.tp}")
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
            self.logger.exception(f"Strategy execution error: {e}")

    # =====================================================
    # 状態確認
    # =====================================================
    def get_status(self):

        return {
            "equity": self.equity,
            "max_equity": self.max_equity,
            "account_frozen": self.account_frozen,
            "freeze_reason": self.freeze_reason,
            "is_live": self.is_live,
            "open_positions": len(self.positions)
        }