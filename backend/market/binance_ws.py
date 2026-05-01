# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time


class BinanceClient:

    def __init__(self, price_manager, symbol="BTCUSDT", engine=None):
        self.price_manager = price_manager
        self.symbol = symbol.lower()
        self.ws = None
        self.thread = None
        self.engine = engine

        self._running = False
        self._lock = threading.Lock()

    # =========================
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)

            if "c" in data:
                price = float(data["c"])

                print(f"📡 {self.symbol.upper()} PRICE: {price}")

                if self.engine:
                    self.engine.on_price(price)

        except Exception as e:
            print("[WS PARSE ERROR]", e)

    def _on_open(self, ws):
        print(f"[WS] Connected {self.symbol.upper()}")

    def _on_error(self, ws, error):
        print("[WS ERROR]", error)

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[WS CLOSED] {self.symbol.upper()}")

    # =========================
    def _run(self):
        while self._running:
            try:
                url = f"wss://stream.binance.com:9443/ws/{self.symbol}@ticker"

                print(f"🌐 CONNECT → {url}")

                self.ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

                self.ws.run_forever()

            except Exception as e:
                print("[WS RUN ERROR]", e)

            time.sleep(2)

    # =========================
    def start_ws(self):
        with self._lock:
            if self._running:
                return

            self._running = True

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # =========================
    def stop_ws(self):
        with self._lock:
            self._running = False

        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

        # 🔥 これが超重要（threadを完全終了）
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

        self.thread = None
        self.ws = None

    # =========================
    def set_symbol(self, symbol):
        symbol = symbol.lower()

        if symbol == self.symbol:
            return

        print(f"🔄 WS SYMBOL SWITCH → {self.symbol.upper()} → {symbol.upper()}")

        # 🔥 完全停止
        self.stop_ws()

        # 🔥 更新
        self.symbol = symbol

        # 🔥 再起動
        self.start_ws()