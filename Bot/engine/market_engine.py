import asyncio
import logging
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.market.candle_buffer import CandleBuffer
import websockets
import json

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
            data = json.loads(message)
            self.process_data(data)

    def process_data(self, data):
        """
        CandleBuffer更新 → StrategyWrapper呼び出し
        """
        candle_updated = self.candle_buffer.update(data)
        if candle_updated:
            self.strategy_wrapper.on_bar(self.candle_buffer.get_latest())

    def stop(self):
        self.stop_flag = True