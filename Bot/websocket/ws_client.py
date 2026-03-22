# Bot/websocket/ws_client.py
import json
import websocket
import threading
import time
from typing import Callable, Optional

from Bot.utils.telegram import TelegramNotifier  # 絶対インポートに修正

# ここではテスト用 TelegramNotifier を使います
# トークンとチャットIDは実際のものに置き換えてください
tg = TelegramNotifier(token="YOUR_BOT_TOKEN", chat_id="YOUR_CHAT_ID")

class BinanceWSClient:
    """
    Binance WebSocket Client（テスト用）
    実際の発注は行わず、データ受信とTelegram通知のテスト用
    """

    def __init__(self, symbol: str = "BTCUSDT", on_message: Optional[Callable] = None):
        self.symbol = symbol.lower()
        self.ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol}@kline_1m"
        self.on_message_callback = on_message
        self.ws = None
        self.thread = None

    def _on_open(self, ws):
        print(f"[INFO] WebSocket opened for {self.symbol}")
        tg.send(f"WebSocket opened for {self.symbol}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[INFO] WebSocket closed for {self.symbol}")
        tg.send(f"WebSocket closed for {self.symbol}")

    def _on_error(self, ws, error):
        print(f"[ERROR] WebSocket error: {error}")
        tg.send(f"WebSocket error: {error}")

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
            print(f"[DEBUG] New candle: {candle}")
            tg.send(f"[TEST] Candle: {candle}")
            if self.on_message_callback:
                self.on_message_callback(candle)

    def start(self):
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
        if self.ws:
            self.ws.close()
        if self.thread:
            self.thread.join()
        print(f"[INFO] WebSocket stopped for {self.symbol}")
        