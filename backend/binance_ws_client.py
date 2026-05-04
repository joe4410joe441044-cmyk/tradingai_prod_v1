# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time


class BinanceWSClient:

    DEBUG = False

    def __init__(self, price_manager, symbol="BTCUSDT", engine=None):
        self.price_manager = price_manager
        self.symbol = symbol.lower()
        self.engine = engine

        self.ws = None
        self.thread = None

        self._running = False
        self._lock = threading.Lock()

    def _get_url(self):
        return f"wss://stream.binance.com:9443/ws/{self.symbol}@trade"

    # =========================
    # START
    # =========================
    def start(self):
        with self._lock:
            if self._running:
                print("⚠️ WS already running")
                return

            self._running = True

        print("🚀 WS START")

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # =========================
    # STOP（完全停止）
    # =========================
    def stop(self):
        with self._lock:
            self._running = False

        print("🛑 WS STOP")

        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

        # 🔥 thread終了待ち（重要）
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

        self.thread = None
        self.ws = None

    # =========================
    def _run(self):

        while self._running:

            try:
                url = self._get_url()
                print("🌐 CONNECT:", url)

                self.ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

                self.ws.on_open = self._on_open

                self.ws.run_forever(ping_interval=20, ping_timeout=10)

            except Exception as e:
                print("❌ WS LOOP ERROR:", e)

            if self._running:
                print("🔁 RECONNECT IN 2s...")
                time.sleep(2)

    # =========================
    def _on_open(self, ws):
        print("🟢 BINANCE WS CONNECTED:", self.symbol)

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)

            price = float(data.get("p", 0))
            if price <= 0:
                return

            symbol = self.symbol

            self.price_manager.update_price(symbol, price)

            if self.engine:
                self.engine.on_price(symbol.upper(), price)

        except Exception as e:
            print("❌ WS PARSE ERROR:", e)

    def _on_error(self, ws, error):
        print("🔴 WS ERROR:", error)

    def _on_close(self, ws, close_status_code, close_msg):
        print("🔴 WS CLOSED:", close_status_code, close_msg)
        self.ws = None