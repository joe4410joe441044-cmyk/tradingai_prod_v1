# -*- coding: utf-8 -*-

import json
import threading
import websocket
import time


class BinanceClient:
    """
    Binance WebSocket（価格専用）
    """

    def __init__(self, price_manager=None, symbol="btcusdt"):
        self.price_manager = price_manager
        self.symbol = symbol.lower()

        self.running = False

    def start_ws(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):

        url = f"wss://stream.binance.com:9443/ws/{self.symbol}@trade"

        def on_message(ws, msg):
            try:
                data = json.loads(msg)
                price = float(data["p"])

                if self.price_manager:
                    self.price_manager.update(self.symbol.upper(), price)

            except Exception as e:
                print("[WS ERROR]", e)

        while self.running:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message=on_message
                )
                ws.run_forever()
            except Exception as e:
                print("[WS RECONNECT]", e)
                time.sleep(3)