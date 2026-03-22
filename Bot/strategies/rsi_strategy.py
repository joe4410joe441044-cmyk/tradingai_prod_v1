import pandas as pd
import random
from strategies.base_strategy import BaseStrategy
from core.trade_core import TradeCore
from utils.logger import BotLogger
from utils.telegram_notifier import TelegramNotifier


class RSIStrategy(BaseStrategy):
    """
    ダミー戦略：RSI風のシグナルを生成（テスト用）
    本物の RSI 計算はせず、ランダムで売買サイン
    """

    def __init__(self, trade_core: TradeCore,
                 df_h1: pd.DataFrame = pd.DataFrame(),
                 logger: BotLogger = None,
                 notifier: TelegramNotifier = None):
        super().__init__(trade_core, logger, notifier)
        self.df_h1 = df_h1
        self.logger and self.logger.info("RSIStrategy initialized.")

    def on_bar(self, market_data):
        # データ更新（M15/H1/H4のいずれか利用可能）
        if "H1" in market_data and not market_data["H1"].empty:
            self.df_h1 = market_data["H1"]

        # ダミーシグナル生成
        action = random.choice(["buy", "sell", None])
        if action is None:
            return None

        price = self.df_h1['close'].iloc[-1] if not self.df_h1.empty else 100.0
        signal_exec = {
            "action": "BUY" if action == "buy" else "SELL",
            "symbol": market_data.get("symbol", "BTCUSDT"),
            "price": price,
            "sl": price - 0.01 if action == "buy" else price + 0.01,
            "tp": price + 0.03 if action == "buy" else price - 0.03,
            "size": 0.001
        }

        # ログ・通知
        self.logger and self.logger.info(f"RSIStrategy signal: {signal_exec}")
        self.notifier and self.notifier.send(f"RSIStrategy signal: {signal_exec}")

        return signal_exec


# --------------------------
# process_data を追加（FVGStrategy と統一）
# --------------------------
def rsi_process_data(self, mtf_data: dict):
    """
    MTFManager から渡された複数時間足データを受け取り on_bar を呼ぶ
    """
    self.on_bar(mtf_data)


RSIStrategy.process_data = rsi_process_data