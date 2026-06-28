# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time

from backend.utils.log_buffer import add_log


class BinanceWSClient:

    DEBUG = False

    def __init__(
        self,
        price_manager,
        symbol="BTCUSDT",
        engine=None
    ):
        self.price_manager = price_manager

        self.symbol = symbol.lower()

        self.engine = engine

        self.ws = None

        self.thread = None

        self._running = False

        self._lock = threading.Lock()

    # =========================
    # URL
    # =========================

    def _get_url(self):

        return (
            f"wss://stream.binance.com:9443/ws/"
            f"{self.symbol}@trade"
        )

    # =========================
    # START
    # =========================

    def start(self):

        with self._lock:

            if self._running:

                add_log(
                    "⚠️ WS already running",
                    "warning"
                )

                return

            self._running = True

        add_log(
            f"🚀 BINANCE WS START "
            f"{self.symbol}",
            "info"
        )

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )

        self.thread.start()

    # =========================
    # STOP
    # =========================

    def stop(self):

        with self._lock:

            self._running = False

        add_log(
            "🛑 BINANCE WS STOP",
            "warning"
        )

        if self.ws:

            try:

                self.ws.close()

            except Exception as e:

                add_log(
                    f"❌ WS CLOSE ERROR: "
                    f"{e}",
                    "error"
                )

        # =========================
        # THREAD JOIN
        # =========================

        if (
            self.thread
            and
            self.thread.is_alive()
        ):

            self.thread.join(
                timeout=2
            )

        self.thread = None

        self.ws = None

    # =========================
    # RUN LOOP
    # =========================

    def _run(self):

        while self._running:

            try:

                url = self._get_url()

                add_log(
                    f"🌐 WS CONNECT "
                    f"{self.symbol}",
                    "warning"
                )

                self.ws = websocket.WebSocketApp(
                    url,

                    on_message=self._on_message,

                    on_error=self._on_error,

                    on_close=self._on_close
                )

                self.ws.on_open = (
                    self._on_open
                )

                self.ws.run_forever(
                    ping_interval=20,
                    ping_timeout=10
                )

            except Exception as e:

                add_log(
                    f"❌ WS LOOP ERROR: "
                    f"{e}",
                    "error"
                )

            if self._running:

                add_log(
                    "🔁 WS RECONNECT IN 2s",
                    "warning"
                )

                time.sleep(2)

    # =========================
    # OPEN
    # =========================

    def _on_open(self, ws):

        add_log(
            f"🟢 BINANCE WS CONNECTED: "
            f"{self.symbol}",
            "info"
        )

    # =========================
    # MESSAGE
    # =========================

    def _on_message(
        self,
        ws,
        message
    ):

        try:

            data = json.loads(
                message
            )

            price = float(
                data.get("p", 0)
            )

            if price <= 0:
                return

            symbol = self.symbol

            # =====================
            # PRICE UPDATE
            # =====================

            self.price_manager.update_price(
                symbol,
                price
            )

            # =====================
            # ENGINE CALLBACK
            # =====================

            if self.engine:

                self.engine.on_price(
                    symbol.upper(),
                    price
                )

            # =====================
            # DEBUG ONLY
            # =====================

            if self.DEBUG:

                add_log(
                    f"DEBUG PRICE "
                    f"{symbol.upper()} "
                    f"{price}",
                    "debug"
                )

        except Exception as e:

            add_log(
                f"❌ WS PARSE ERROR: "
                f"{e}",
                "error"
            )

    # =========================
    # ERROR
    # =========================

    def _on_error(
        self,
        ws,
        error
    ):

        add_log(
            f"🔴 WS ERROR: "
            f"{error}",
            "error"
        )

    # =========================
    # CLOSE
    # =========================

    def _on_close(
        self,
        ws,
        close_status_code,
        close_msg
    ):

        add_log(
            f"🔴 WS CLOSED "
            f"STATUS={close_status_code} "
            f"MSG={close_msg}",
            "warning"
        )

        self.ws = None