# wrappers/test_signal_generator.py
import asyncio
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class TestSignalGenerator:
    """
    TradeCoreの制御テスト用シグナル生成
    - ポジション数制限（max_concurrent_positions）
    - DD制御（max_daily_dd_percent, max_total_dd_percent）
    """
    def __init__(self, strategy_wrapper, interval_sec=15):
        self.strategy_wrapper = strategy_wrapper
        self.interval_sec = interval_sec
        self.stop_flag = False
        self.position_counter = 0

    async def run(self):
        """
        interval_secごとにランダムシグナルを生成
        """
        while not self.stop_flag:
            # ランダムに買い or 売りシグナル生成
            trade_type = random.choice(["BUY", "SELL"])
            price = round(30000 + random.uniform(-1000, 1000), 2)
            volume = 0.001  # テスト用少量
            sl = price - 50 if trade_type == "BUY" else price + 50
            tp = price + 50 if trade_type == "BUY" else price - 50

            logger.info(f"[TEST SIGNAL] {trade_type} @ {price}, SL={sl}, TP={tp}")
            # StrategyWrapper 経由で TradeCore にシグナル送信
            self.strategy_wrapper.on_test_signal(trade_type, price, sl, tp, volume)

            await asyncio.sleep(self.interval_sec)

    def stop(self):
        self.stop_flag = True