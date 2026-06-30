# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time

from backend.utils.log_buffer import logger, ws_debug


class BinanceClient:
    """
    Binance WebSocket Client（価格専用）
    ※ REST機能は含めない
    """

    def __init__(self, price_manager, symbol="BTCUSDT", engine=None):
        ws_debug("Using Binance WebSocket-only client")

        self.price_manager = price_manager
        self.symbol = symbol.lower()
        self.engine = engine

        self.ws = None
        self.thread = None

        self._running = False
        self._lock = threading.Lock()

    # =========================
    # メッセージ受信
    # =========================
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)

            price = None

            # 🔥 trade優先（最重要）
            if "p" in data:
                price = float(data["p"])
            elif "c" in data:
                price = float(data["c"])
            elif "lastPrice" in data:
                price = float(data["lastPrice"])

            if price is None or price <= 0:
                return

            # 🔥 symbolはWSから取得（絶対）
            ws_symbol = data.get("s", "").upper()

            if not ws_symbol:
                ws_debug("Binance WebSocket symbol missing data=%s", data)
                return

            # =========================
            # PriceManager更新
            # =========================
            if self.price_manager:
                self.price_manager.update_price(ws_symbol, price)

            # =========================
            # Engine通知
            # =========================
            if self.engine:
                try:
                    self.engine.on_price(ws_symbol, price)
                except Exception as e:
                    logger.error("Binance engine callback error: %s", e)

        except Exception as e:
            logger.error("Binance WebSocket parse error: %s", e)

    # =========================
    # 接続イベント
    # =========================
    def _on_open(self, ws):
        logger.info("WS CONNECTED: %s", self.symbol.upper())

    def _on_error(self, ws, error):
        logger.error("WS ERROR: %s", error)

    def _on_close(self, ws, close_status_code, close_msg):
        logger.warning("WS DISCONNECTED: %s", self.symbol.upper())

    # =========================
    # 実行ループ
    # =========================
    def _run(self):
        ws_debug("Binance WebSocket loop started")

        while self._running:
            try:
                url = f"wss://fstream.binance.com/ws/{self.symbol}@trade"

                logger.info("WS CONNECT: %s", url)

                self.ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_open=self._on_open,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

                self.ws.run_forever(ping_interval=20, ping_timeout=10)

            except Exception as e:
                logger.error("WS RUN ERROR: %s", e)

            # 🔁 再接続
            time.sleep(2)

    # =========================
    # 起動（新）
    # =========================
    def start(self):
        with self._lock:
            if self._running:
                return

            self._running = True

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # =========================
    # 停止（新）
    # =========================
    def stop(self):
        with self._lock:
            self._running = False

        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

        self.thread = None
        self.ws = None

    # =========================
    # シンボル変更
    # =========================
    def set_symbol(self, symbol):
        symbol = symbol.lower()

        if symbol == self.symbol:
            return

        logger.info(
            "WS SYMBOL SWITCH: %s -> %s",
            self.symbol.upper(),
            symbol.upper(),
        )

        self.stop()
        self.symbol = symbol

        time.sleep(0.5)

        self.start()
