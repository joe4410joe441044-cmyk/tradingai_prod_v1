# -*- coding: utf-8 -*-

# Bot/websocket/ws_client.py

import json

import websocket

import threading

from typing import Callable, Optional



from Bot.utils.telegram import TelegramNotifier



class BinanceWSClient:

    """

    Binance WebSocket Client

    - MarketEngine Ag

    - Telegram m

    """



    def __init__(

        self,

        symbol: str = "BTCUSDT",

        on_candle: Optional[Callable] = None,

        telegram_token: str = None,

        telegram_chat_id: str = None

    ):

        self.symbol = symbol.lower()

        self.ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_1m"

        self.on_candle = on_candle

        self.ws = None

        self.thread = None

        self.notifier = TelegramNotifier(token=telegram_token, chat_id=telegram_chat_id)



    def _on_open(self, ws):

        print(f"[INFO] WebSocket opened for {self.symbol}")

        self.notifier.bot_started()



    def _on_close(self, ws, close_status_code, close_msg):

        print(f"[INFO] WebSocket closed for {self.symbol}")

        self.notifier.send(f"WebSocket closed for {self.symbol}")



    def _on_error(self, ws, error):

        print(f"[ERROR] WebSocket error: {error}")

        self.notifier.send(f"WebSocket error: {error}")



    def _on_message(self, ws, message):

        data = json.loads(message)

        kline = data.get("k")

        if kline:

            candle = {

                "open": float(kline["o"]),

                "high": float(kline["h"]),

                "low": float(kline["l"]),

                "close": float(kline["c"]),

                "volume": float(kline["v"]),

                "timestamp": kline["t"]

            }

            if self.on_candle:

                self.on_candle(candle)



    def start(self):

        """Start WebSocket thread"""

        self.ws = websocket.WebSocketApp(

            self.ws_url,

            on_open=self._on_open,

            on_close=self._on_close,

            on_error=self._on_error,

            on_message=self._on_message

        )

        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)

        self.thread.start()

        print(f"[INFO] WebSocket thread started for {self.symbol}")



    def stop(self):

        """Stop WebSocket thread"""

        if self.ws:

            self.ws.close()

        if self.thread:

            self.thread.join()

        print(f"[INFO] WebSocket stopped for {self.symbol}")
