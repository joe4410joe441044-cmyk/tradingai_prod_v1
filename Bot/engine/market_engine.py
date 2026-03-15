# engine/market_engine.py
import asyncio
import logging
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.market.candle_buffer import CandleBuffer
import websockets
import json
import time

logger = logging.getLogger(__name__)

class MarketEngine:
    """
    Market Data Engine
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
                    logger.info("WebSocket接続成功")
                    await self.listen()
            except Exception as e:
                logger.error(f"WebSocket接続エラー: {e}")
                wait_sec = 5
                logger.info(f"{wait_sec}秒後に再接続を試みます")
                await asyncio.sleep(wait_sec)

    async def listen(self):
        async for message in self.ws:
            data = json.loads(message)
            self.process_data(data)

    def process_data(self, data):
        """
        ローソク足更新 → StrategyWrapperに通知
        """
        candle_updated = self.candle_buffer.update(data)
        if candle_updated:
            self.strategy_wrapper.on_candle(self.candle_buffer.get_latest())

    def stop(self):
        self.stop_flag = True