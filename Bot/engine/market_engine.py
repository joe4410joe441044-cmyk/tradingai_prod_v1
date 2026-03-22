# -*- coding: utf-8 -*-
from typing import List
from strategies.base_strategy import BaseStrategy
from market.candle_buffer import CandleBuffer
from utils.multi_timeframe_manager import MultiTimeFrameManager
from websocket.ws_client import BinanceWSClient
from utils.telegram import TelegramNotifier  # 譛ｬ逡ｪ逕ｨ

class MarketEngine:
    """
    MarketEngine・域悽逡ｪ逕ｨ・上ム繝溘・繝・・繧ｿ蜈ｼ逕ｨ・・
    - CandleBuffer譖ｴ譁ｰ
    - MultiTimeFrameManager縺ｧ莉ｻ諢乗凾髢楢ｶｳ逕滓・
    - 謌ｦ逡･縺ｫ on_bar 繝・・繧ｿ繧呈ｸ｡縺・
    - WebSocket邨ｱ蜷・
    """

    def __init__(self, strategies: List[BaseStrategy], debug: bool = True,
                 telegram_token: str = None, telegram_chat_id: str = None):
        self.strategies = strategies
        self.debug = debug

        # 逕溯ｶｳ繝舌ャ繝輔ぃ
        self.candle_buffer = CandleBuffer()

        # 繝槭Ν繝√ち繧､繝繝輔Ξ繝ｼ繝邂｡逅・ｼ・蛻・ｶｳ繝吶・繧ｹ・・
        self.mtf_manager = MultiTimeFrameManager(base_timeframe="1m")

        # 蟇ｾ蠢懈凾髢楢ｶｳ
        self.timeframes = ["M15", "H1", "H4"]

        # Telegram 騾夂衍
        self.notifier = TelegramNotifier(token=telegram_token, chat_id=telegram_chat_id) if telegram_token else None

        # WebSocket 繧ｯ繝ｩ繧､繧｢繝ｳ繝育ｮ｡逅・
        self.ws_clients: List[BinanceWSClient] = []

    # ----------------------------
    # WebSocket 騾｣謳ｺ
    # ----------------------------
    def add_ws_client(self, symbol: str):
        """WebSocket Client 繧定ｿｽ蜉"""
        ws_client = BinanceWSClient(
            symbol=symbol,
            on_candle=self.process_data,  # 蜿嶺ｿ｡繝・・繧ｿ繧・process_data 縺ｫ貂｡縺・
            telegram_token=self.notifier.token if self.notifier else None,
            telegram_chat_id=self.notifier.chat_id if self.notifier else None
        )
        ws_client.start()
        self.ws_clients.append(ws_client)
        if self.debug:
            print(f"[MarketEngine] WS client started for {symbol}")

    # ----------------------------
    # 繧ｭ繝｣繝ｳ繝峨Ν蜃ｦ逅・
    # ----------------------------
    def process_data(self, data: dict):
        """
        WS繧・ム繝溘・繝・・繧ｿ繧貞女縺大叙繧・
        CandleBuffer 縺ｨ MTFManager 繧呈峩譁ｰ縺励※謌ｦ逡･縺ｫ貂｡縺・
        data 繝輔か繝ｼ繝槭ャ繝井ｾ・
        {
            "symbol": "BTCUSDT",
            "time": 1679452800000,
            "open": 30000,
            "high": 30100,
            "low": 29950,
            "close": 30050,
            "volume": 12.34
        }
        """
        candle = {
            "time": data.get("time"),
            "open": float(data.get("open", 0)),
            "high": float(data.get("high", 0)),
            "low": float(data.get("low", 0)),
            "close": float(data.get("close", 0)),
            "volume": float(data.get("volume", 0))
        }

        if self.debug:
            print(f"[MarketEngine] New candle: {candle}")

        # CandleBuffer 縺ｫ霑ｽ蜉
        self.candle_buffer.add_candle(candle)

        # MultiTimeFrameManager 繧呈峩譁ｰ
        self.mtf_manager.update_candle(
            symbol=data.get("symbol", "BTCUSDT"),
            candle=candle
        )

        # 蜷・凾髢楢ｶｳ繧貞叙蠕励＠縺ｦ謌ｦ逡･縺ｫ貂｡縺・
        market_data = self.mtf_manager.get_all_timeframes(
            symbol=data.get("symbol", "BTCUSDT"),
            timeframes=self.timeframes
        )
        market_data["symbol"] = data.get("symbol", "BTCUSDT")

        # 謌ｦ逡･縺ｫ繝・・繧ｿ繧呈ｸ｡縺・
        for strategy in self.strategies:
            strategy.on_bar(market_data)
