# wrappers/test_signal_generator.py
import asyncio
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class TestSignalGenerator:
    """
    TradeCore縺ｮ蛻ｶ蠕｡繝・せ繝育畑繧ｷ繧ｰ繝翫Ν逕滓・
    - 繝昴ず繧ｷ繝ｧ繝ｳ謨ｰ蛻ｶ髯撰ｼ・ax_concurrent_positions・・
    - DD蛻ｶ蠕｡・・ax_daily_dd_percent, max_total_dd_percent・・
    """
    def __init__(self, strategy_wrapper, interval_sec=15):
        self.strategy_wrapper = strategy_wrapper
        self.interval_sec = interval_sec
        self.stop_flag = False
        self.position_counter = 0

    async def run(self):
        """
        interval_sec縺斐→縺ｫ繝ｩ繝ｳ繝繝繧ｷ繧ｰ繝翫Ν繧堤函謌・
        """
        while not self.stop_flag:
            # 繝ｩ繝ｳ繝繝縺ｫ雋ｷ縺・or 螢ｲ繧翫す繧ｰ繝翫Ν逕滓・
            trade_type = random.choice(["BUY", "SELL"])
            price = round(30000 + random.uniform(-1000, 1000), 2)
            volume = 0.001  # 繝・せ繝育畑蟆鷹㍼
            sl = price - 50 if trade_type == "BUY" else price + 50
            tp = price + 50 if trade_type == "BUY" else price - 50

            logger.info(f"[TEST SIGNAL] {trade_type} @ {price}, SL={sl}, TP={tp}")
            # StrategyWrapper 邨檎罰縺ｧ TradeCore 縺ｫ繧ｷ繧ｰ繝翫Ν騾∽ｿ｡
            self.strategy_wrapper.on_test_signal(trade_type, price, sl, tp, volume)

            await asyncio.sleep(self.interval_sec)

    def stop(self):
        self.stop_flag = True
