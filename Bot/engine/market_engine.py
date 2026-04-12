# -*- coding: utf-8 -*-
# Bot/engine/market_engine.py

import asyncio
from datetime import datetime
from collections import deque
import pandas as pd
from typing import List, Optional

from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier

from Bot.utils.safety import safe_run


class CandleBuffer:
    def __init__(self, maxlen=500):
        self.candles = deque(maxlen=maxlen)
        self.df_M1 = pd.DataFrame()

    def add_candle(self, candle: dict):
        new_row = pd.DataFrame([candle])
        self.df_M1 = pd.concat([self.df_M1, new_row], ignore_index=True)
        self.candles.append(candle)


class MarketEngine:

    def __init__(
        self,
        strategies: Optional[List] = None,
        strategy_wrapper: Optional[StrategyWrapper] = None,
        trade_core: Optional[TradeCore] = None,
        logger: Optional[BotLogger] = None,
        notifier: Optional[TelegramNotifier] = None,
        ws_url: Optional[str] = None,
        debug: bool = False,
    ):
        self.logger = logger or BotLogger()
        self.notifier = notifier
        self.ws_url = ws_url
        self.debug = debug

        self.trade_core = trade_core
        self.strategy_wrapper = strategy_wrapper
        self.strategies = strategies or []

        self.candle_buffer = CandleBuffer()
        self._running = False

        self.logger.info("MarketEngine initialized.")

    # =====================================================
    # DATA PIPELINE
    # =====================================================
    @safe_run
    def process_data(self, candle: dict):

        if not candle:
            return

        symbol = candle.get("symbol")
        close_price = candle.get("close")

        # 🚨 完全防御（ここ重要）
        if symbol is None or close_price is None:
            self.logger.error(f"[MARKET] invalid candle: {candle}")
            return

        print(f"[MARKET] is_closed={candle.get('is_closed')} price={close_price}")

        # Candle保存
        self.candle_buffer.add_candle(candle)

        # --------------------------
        # PRICE UPDATE → TRADE CORE
        # --------------------------
        if self.trade_core:

            try:
                price_dict = {symbol: float(close_price)}

                print(f"[TICK] {price_dict}")

                # 追加防御
                if price_dict[symbol] is None:
                    self.logger.error("[PRICE UPDATE ERROR] None price detected")
                    return

                # =================================================
                # MAIN PIPELINE
                # =================================================
                self.trade_core.process_events(price_dict)

            except Exception as e:
                self.logger.error(f"[PRICE UPDATE ERROR] {e}")

        # --------------------------
        # STRATEGY LAYER
        # --------------------------
        if self.strategy_wrapper:
            try:
                self.strategy_wrapper.on_bar(candle)
            except Exception as e:
                self.logger.error(f"[STRATEGY ERROR] {e}")

    # =====================================================
    # WEBSOCKET LOOP
    # =====================================================
    @safe_run
    async def run_websocket(self):

        import websockets

        self._running = True
        self.logger.info(f"Connecting to WS: {self.ws_url}")

        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    async for message in ws:
                        candle = self.parse_message(message)

                        # 🚨 非同期ループでも安全
                        if candle:
                            self.process_data(candle)

            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(5)

    # =====================================================
    # MESSAGE PARSER
    # =====================================================
    def parse_message(self, message: str) -> dict:

        import json

        try:
            data = json.loads(message)
            k = data.get("k", {})

            close = k.get("c")
            if close is None:
                return None

            return {
                "symbol": data.get("s"),
                "time": datetime.fromtimestamp(k.get("t", 0) / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(k.get("o", 0)),
                "high": float(k.get("h", 0)),
                "low": float(k.get("l", 0)),
                "close": float(close),
                "volume": float(k.get("v", 0)),
                "timeframe": k.get("i", "1m"),
                "is_closed": k.get("x", False)
            }

        except Exception as e:
            self.logger.error(f"[PARSE ERROR] {e}")
            return None