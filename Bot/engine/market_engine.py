import asyncio
import logging
import json
from typing import List, Callable

from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.market.candle_buffer import CandleBuffer

logger = logging.getLogger("MarketEngine")


class MarketEngine:
    """
    WebSocket → Queue → CandleBuffer → Strategy
    """

    def __init__(self, strategies: List[FVGStrategy], strategy_callback: Callable):
        self.strategies = strategies
        self.strategy_callback = strategy_callback

        self.candle_buffer = CandleBuffer()

        # ✅ queue制限（メモリ暴走防止）
        self.queue = asyncio.Queue(maxsize=1000)

        self.ws_url = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
        self.last_candle_ts = None

        self._running = True

    # ------------------------------
    # WebSocket Listener
    # ------------------------------
    async def _websocket_listener(self):
        import websockets

        while self._running:
            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    logger.info("WebSocket connected")

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            kline = data.get("k")

                            if not kline:
                                continue

                            # queue満杯対策
                            if self.queue.full():
                                logger.warning("Queue full, dropping oldest data")
                                _ = self.queue.get_nowait()

                            await self.queue.put(kline)

                        except Exception as e:
                            logger.exception(f"Message processing error: {e}")

            except Exception as e:
                logger.error(f"WebSocket error: {e} → reconnecting in 5s")
                await asyncio.sleep(5)

    # ------------------------------
    # Candle Processor
    # ------------------------------
    async def _candle_processor(self):
        while self._running:
            try:
                kline = await self.queue.get()

                if not kline:
                    continue

                candle_ts = kline.get("t")

                if not candle_ts:
                    continue

                # 重複防止
                if self.last_candle_ts and candle_ts <= self.last_candle_ts:
                    continue

                self.last_candle_ts = candle_ts

                # CandleBuffer更新
                try:
                    self.candle_buffer.add_candle(kline)
                except Exception as e:
                    logger.exception(f"CandleBuffer error: {e}")

                # Strategy実行（最重要：絶対止めない）
                try:
                    await self.strategy_callback(kline)
                except Exception as e:
                    logger.exception(f"Strategy error: {e}")

            except Exception as e:
                logger.exception(f"Processor loop error: {e}")

    # ------------------------------
    # Run
    # ------------------------------
    async def run_websocket(self):
        listener_task = asyncio.create_task(self._websocket_listener())
        processor_task = asyncio.create_task(self._candle_processor())

        try:
            await asyncio.gather(listener_task, processor_task)
        finally:
            self._running = False   