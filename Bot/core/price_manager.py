# -*- coding: utf-8 -*-

import threading
import time


class PriceManager:

    def __init__(self):
        self.prices = {}
        self.candles = {}  # ローソク足
        self.lock = threading.Lock()

        self.subscribers = []

        # 設定
        self.max_candles = 100

    # =========================
    # SUBSCRIBE
    # =========================
    def subscribe(self, callback):
        if callable(callback):
            self.subscribers.append(callback)

    # =========================
    # UPDATE（最重要）
    # =========================
    def update(self, symbol, price):

        if not symbol:
            return

        symbol = symbol.upper()

        with self.lock:

            # 最新価格
            self.prices[symbol] = price

            # =========================
            # ローソク足生成
            # =========================
            if symbol not in self.candles:
                self.candles[symbol] = []

            candle_list = self.candles[symbol]

            now = int(time.time())

            # 初回
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

                # 同一秒
                if now == last["time"]:
                    last["high"] = max(last["high"], price)
                    last["low"] = min(last["low"], price)
                    last["close"] = price

                # 新規足
                else:
                    candle_list.append({
                        "time": now,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price
                    })

            # メモリ制限
            if len(candle_list) > self.max_candles:
                self.candles[symbol] = candle_list[-self.max_candles:]

        # =========================
        # 通知
        # =========================
        for cb in list(self.subscribers):
            try:
                cb(symbol, price)
            except Exception as e:
                print("[PriceManager ERROR]", e)

    # =========================
    # GET
    # =========================
    def get(self, symbol):
        if not symbol:
            return 0.0
        with self.lock:
            return self.prices.get(symbol.upper(), 0.0)

    def get_all(self):
        with self.lock:
            return dict(self.candles)

    def get_candles(self, symbol):
        if not symbol:
            return []
        with self.lock:
            return self.candles.get(symbol.upper(), [])