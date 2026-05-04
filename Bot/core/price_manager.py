# -*- coding: utf-8 -*-

import threading
import time


class PriceManager:

    DEBUG_PRICE = False  # 🔥 これで制御

    def __init__(self):
        self.prices = {}
        self.candles = {}
        self.lock = threading.Lock()

        self.subscribers = []
        self.max_candles = 100

    def subscribe(self, callback):
        if callable(callback):
            self.subscribers.append(callback)

    def update_price(self, symbol, price):

        if not symbol:
            print("❌ update_price: symbol is None")
            return

        try:
            symbol = symbol.upper()
            price = float(price)
        except Exception:
            print(f"❌ update_price: invalid input {symbol} {price}")
            return

        if price <= 0:
            print(f"❌ update_price: invalid price {price}")
            return

        with self.lock:

            self.prices[symbol] = price

            # 🔥 デバッグ制御
            if self.DEBUG_PRICE:
                print(f"📈 PRICE SET: {symbol} = {price}")
                print(f"📦 PRICE MAP: {self.prices}")

            if symbol not in self.candles:
                self.candles[symbol] = []

            candle_list = self.candles[symbol]
            now = int(time.time())

            if not candle_list:
                candle_list.append({
                    "time": now,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price
                })

            else:
                last = candle_list[-1]

                if now == last["time"]:
                    last["high"] = max(last["high"], price)
                    last["low"] = min(last["low"], price)
                    last["close"] = price
                else:
                    candle_list.append({
                        "time": now,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price
                    })

            if len(candle_list) > self.max_candles:
                self.candles[symbol] = candle_list[-self.max_candles:]

        for cb in list(self.subscribers):
            try:
                cb(symbol, price)
            except Exception as e:
                print("[PriceManager ERROR]", e)

    def get_price(self, symbol):
        if not symbol:
            print("❌ get_price: symbol is None")
            return 0.0

        symbol = symbol.upper()

        with self.lock:
            price = self.prices.get(symbol)

        if price is None:
            print(f"❌ PRICE NOT FOUND: {symbol}")
            print(f"👉 available: {list(self.prices.keys())}")
            return 0.0

        return price

    def get_all_prices(self):
        with self.lock:
            return dict(self.prices)

    def get_candles(self, symbol):
        if not symbol:
            return []

        symbol = symbol.upper()

        with self.lock:
            return self.candles.get(symbol, [])