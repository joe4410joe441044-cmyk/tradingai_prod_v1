# -*- coding: utf-8 -*-

import websocket
import json
import threading


class OrderBookWS:

    def __init__(self, symbol, on_update):
        self.symbol = symbol.lower()
        self.url = f"wss://stream.binance.com:9443/ws/{self.symbol}@depth"
        self.on_update = on_update
        self.ws = None

    def on_message(self, ws, message):
        data = json.loads(message)

        bids = data.get("b", [])
        asks = data.get("a", [])

        # BOTへ渡す
        self.on_update(bids, asks)

    def on_open(self, ws):
        print(f"🟢 ORDERBOOK WS CONNECTED: {self.symbol}")

    def on_close(self, ws, close_status_code, close_msg):
        print("🔴 ORDERBOOK WS CLOSED")

    def start(self):
        def run():
            self.ws = websocket.WebSocketApp(
                self.url,
                on_message=self.on_message,
                on_open=self.on_open,
                on_close=self.on_close,
            )
            self.ws.run_forever()

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        if self.ws:
            self.ws.close()