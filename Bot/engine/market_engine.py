import asyncio
import logging
import json
import websockets

from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.market.candle_buffer import CandleBuffer

logger = logging.getLogger(__name__)


class MarketEngine:
    """
    WebSocket受信 → CandleBuffer更新 → StrategyWrapper通知
    再接続対応
    """

    def __init__(self, ws_url: str, strategy_wrapper: StrategyWrapper):
        self.ws_url = ws_url
        self.strategy_wrapper = strategy_wrapper
        self.candle_buffer = CandleBuffer()
        self.ws = None
        self.stop_flag = False

        logger.info(f"CandleBuffer loaded from: {CandleBuffer.__module__}")

    async def connect(self):
        while not self.stop_flag:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    logger.info("WebSocket connected")
                    await self.listen()
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
                await asyncio.sleep(5)

    async def listen(self):
        async for message in self.ws:
            try:
                print("data received")  # ✅ データ受信確認
                data = json.loads(message)
                self.process_data(data)
            except Exception as e:
                logger.error(f"Data processing error: {e}")

    def process_data(self, data):
        """
        CandleBuffer更新 → StrategyWrapper呼び出し
        """
        try:
            k = data.get("k")

            # 🔥 テスト中は未確定足も通す（重要）
            if k is None:
                return

            print("candle closed (test)")  # ✅ 通過確認

            candle = {
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"])
            }

            # ---------------------------------
            # Candle追加
            # ---------------------------------
            self.candle_buffer.add_candle(candle)

            # ---------------------------------
            # 最新取得
            # ---------------------------------
            latest_data = self.candle_buffer.get_last(1)

            if not latest_data:
                return

            # 🔥 list / DataFrame 両対応
            if isinstance(latest_data, list):
                latest = latest_data[-1]
            else:
                latest = latest_data.iloc[-1]

            # ---------------------------------
            # Strategyへ渡す
            # ---------------------------------
            print("➡ Strategy call")  # ✅ ここ重要
            self.strategy_wrapper.on_bar(latest)

        except Exception as e:
            logger.error(f"process_data error: {e}")

    def stop(self):
        self.stop_flag = True