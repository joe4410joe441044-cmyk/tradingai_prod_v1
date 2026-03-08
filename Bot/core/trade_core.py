from dataclasses import dataclass
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
    extra: dict = None


# =====================================================
# 資金管理・DD制御コア
# =====================================================
class TradeCore:

    def __init__(
        self,
        initial_balance: float = 10000,
        is_live: bool = False,
        log_path: str = "bot.log"
    ):

        # ==== 実行モード ====
        self.is_live = is_live
        self.log_path = log_path

        # ==== Logger ====
        self.logger = BotLogger()

        # ==== 資金状態 ====
        self.initial_balance = initial_balance
        self.equity = initial_balance
        self.max_equity = initial_balance
        self.day_start_balance = initial_balance

        # ==== DD設定 ====
        self.max_daily_dd_percent = 4.0
        self.max_total_dd_percent = 6.0
        self.max_peak_dd_percent = 8.0

        # ==== 制御状態 ====
        self.account_frozen = False
        self.freeze_reason = None

        # ==== ポジション管理 ====
        self.positions: List[Position] = []
        self.max_concurrent_positions = 5

        # ==== 日次管理 ====
        self.current_date = datetime.datetime.now().date()

    # =====================================================
    # ポジション更新（簡易版）
    # =====================================================
    def update_positions(self):
        pass

    # =====================================================
    # 外部残高更新
    # =====================================================
    def update_equity(self, real_balance: float):

        self.equity = real_balance

        if self.equity > self.max_equity:
            self.max_equity = self.equity

        now = datetime.datetime.now()

        if now.date() != self.current_date:
            self.day_start_balance = self.equity
            self.current_date = now.date()

        self._check_drawdown()

    # =====================================================
    # DD判定
    # =====================================================
    def _check_drawdown(self):

        if self.equity <= 0:
            self._freeze("Equity <= 0")
            return

        daily_dd = (self.day_start_balance - self.equity) / self.day_start_balance * 100
        total_dd = (self.initial_balance - self.equity) / self.initial_balance * 100
        peak_dd = (self.max_equity - self.equity) / self.max_equity * 100

        if daily_dd >= self.max_daily_dd_percent:
            self._freeze("Daily DD exceeded")
            return

        if total_dd >= self.max_total_dd_percent:
            self._freeze("Total DD exceeded")
            return

        if peak_dd >= self.max_peak_dd_percent:
            self._freeze("Peak DD exceeded")
            return

    # =====================================================
    # 凍結処理
    # =====================================================
    def _freeze(self, reason: str):

        self.account_frozen = True
        self.freeze_reason = reason

        print(f"ACCOUNT FROZEN: {reason}")

    # =====================================================
    # エントリー可否
    # =====================================================
    def can_trade(self) -> bool:

        return not self.account_frozen

    # =====================================================
    # エントリー処理
    # =====================================================
    def try_enter(self, ctx: StrategyContext) -> bool:

        if not self.can_trade():
            return False

        if len(self.positions) >= self.max_concurrent_positions:
            return False

        pos = Position(
            entry_price=ctx.entry_price,
            trade_type=ctx.trade_type,
            sl=ctx.stop_loss_price,
            tp=ctx.take_profit_price,
            volume=1.0,
            entry_time=datetime.datetime.now()
        )

        self.positions.append(pos)

        print(
            f"[ENTRY] {ctx.strategy_name} | {ctx.trade_type} | "
            f"Entry: {ctx.entry_price} | SL: {ctx.stop_loss_price} | TP: {ctx.take_profit_price}"
        )

        # ===== ログ保存 =====
        self.logger.log_trade(
            ctx.strategy_name,
            ctx.trade_type,
            ctx.entry_price,
            ctx.stop_loss_price,
            ctx.take_profit_price
        )

        return True

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