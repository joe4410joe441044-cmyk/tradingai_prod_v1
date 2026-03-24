# -*- coding: utf-8 -*-
# Bot/engine/market_engine.py

import asyncio
import logging
from datetime import datetime
from collections import deque
import pandas as pd
from typing import List, Optional

from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier

# ★追加（ここだけ増やす）
from Bot.utils.safety import safe_run, check_connections, ensure_connections


# -------------------------
# CandleBuffer
# -------------------------
class CandleBuffer:
    """ローソク足管理"""
    def __init__(self, maxlen=500):
        self.candles = deque(maxlen=maxlen)
        self.df_M1 = pd.DataFrame()
        self.df_M5 = pd.DataFrame()
        self.df_M15 = pd.DataFrame()
        self.df_H1 = pd.DataFrame()
        self.df_H4 = pd.DataFrame()

    def add_candle(self, candle: dict, timeframe="M1"):
        timeframe_map = {
            "1m": "M1",
            "5m": "M5",
            "15m": "M15",
            "1h": "H1",
            "4h": "H4"
        }
        tf = timeframe_map.get(timeframe.lower())
        if not tf:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        df_attr = f"df_{tf}"
        df = getattr(self, df_attr)
        new_row = pd.DataFrame([candle])
        df = pd.concat([df, new_row], ignore_index=True)
        setattr(self, df_attr, df)
        self.candles.append(candle)

    def last(self):
        return self.candles[-1] if self.candles else None

    def prev(self):
        return self.candles[-2] if len(self.candles) >= 2 else None


# -------------------------
# MarketEngine
# -------------------------
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
        use_dummy: bool = False
    ):
        self.logger = logger or BotLogger()
        self.notifier = notifier
        self.ws_url = ws_url
        self.debug = debug
        self.use_dummy = use_dummy

        self.trade_core = trade_core
        self.strategy_wrapper = strategy_wrapper
        self.strategies = strategies or []

        self.candle_buffer = CandleBuffer()
        self._running = False

        self.logger.info("MarketEngine initialized.")

    # -------------------------
    # データ処理（安全化）
    # -------------------------
    @safe_run
    def process_data(self, candle: dict):

        # ★接続チェック（追加）
        if self.trade_core:
            errors = check_connections(self.trade_core)
            if errors:
                self.logger.error(f"[CONNECTION ERROR] {errors}")
                ensure_connections(self.trade_core, None)

        timeframe = candle.get("timeframe", "1m")
        self.candle_buffer.add_candle(candle, timeframe=timeframe)

        if self.debug:
            print(f"[MarketEngine] Candle added: {candle}")

        # Strategy通知
        try:
            if self.strategy_wrapper:
                signal = self.strategy_wrapper.on_bar(candle)
                if signal and self.trade_core:
                    self.trade_core.check_orders(signal)
            else:
                for strat in self.strategies:
                    signal = strat.on_bar(candle)
                    if signal and self.trade_core:
                        self.trade_core.check_orders(signal)
        except Exception as e:
            self.logger.error(f"[STRATEGY ERROR] {e}")

    # -------------------------
    # ダミー
    # -------------------------
    @safe_run
    async def run_dummy(self, dummy_candles: list):
        self._running = True
        self.logger.info("=== Running in DUMMY mode ===")

        for candle in dummy_candles:
            if not self._running:
                break

            self.process_data(candle)

            if self.trade_core:
                try:
                    self.trade_core.check_orders({})
                except Exception as e:
                    self.logger.error(f"[TRADECORE ERROR] {e}")

            await asyncio.sleep(0.1)

        self.logger.info("=== DUMMY mode completed ===")

    # -------------------------
    # WebSocket（無敵化）
    # -------------------------
    @safe_run
    async def run_websocket(self):

        if not self.ws_url:
            raise ValueError("WebSocket URL is required")

        import websockets
        import json

        self._running = True
        self.logger.info(f"Connecting to WS: {self.ws_url}")

        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:

                    last_recv = asyncio.get_event_loop().time()

                    async for message in ws:

                        last_recv = asyncio.get_event_loop().time()

                        candle = self.parse_message(message)
                        self.process_data(candle)

                        # ★タイムアウト監視（追加）
                        if asyncio.get_event_loop().time() - last_recv > 60:
                            raise Exception("WS timeout")

            except Exception as e:
                self.logger.error(f"WebSocket error: {e}, retrying in 5s")
                await asyncio.sleep(5)

    # -------------------------
    # メッセージ解析
    # -------------------------
    def parse_message(self, message: str) -> dict:
        import json
        data = json.loads(message)
        kline = data.get("k", {})

        return {
            "symbol": data.get("s"),
            "time": datetime.fromtimestamp(kline.get("t", 0)/1000).strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(kline.get("o", 0)),
            "high": float(kline.get("h", 0)),
            "low": float(kline.get("l", 0)),
            "close": float(kline.get("c", 0)),
            "volume": float(kline.get("v", 0)),
            "timeframe": kline.get("i", "1m")
        }

    # -------------------------
    # 停止
    # -------------------------
    def stop(self):
        self._running = False
        self.logger.info("MarketEngine stopped.")