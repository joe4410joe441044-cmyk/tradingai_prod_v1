# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time

from backend.utils.log_buffer import add_log, ws_debug


class OrderBookWS:

    def __init__(self, symbol, on_update):

        self.symbol = symbol.lower()

        self.url = (
            f"wss://stream.binance.com:9443/ws/"
            f"{self.symbol}@depth"
        )

        self.on_update = on_update

        self.ws = None

        self.last_price = 0.0

        self.best_bid = 0.0

        self.best_ask = 0.0

        self.spread = 0.0

        # =========================
        # LAST VALID BOOK
        # =========================

        self.last_valid_bid = 0.0

        self.last_valid_ask = 0.0

        self.connected = False

        self.running = False

        # =========================
        # LOCAL ORDERBOOK
        # =========================

        self.bids = {}

        self.asks = {}

        # =========================
        # SEQUENCE
        # =========================

        self.snapshot_loaded = False

        self.orderbook_initialized = False

        self.snapshot_sequence = 0

        self.last_sequence_end = None

        self.resnapshot_required = False

    # =========================
    # MESSAGE
    # =========================

    def on_message(self, ws, message):

        try:

            data = json.loads(message)

            bids = data.get("b", [])

            asks = data.get("a", [])

            # =========================
            # SEQUENCE
            # =========================

            new_U = data.get("U")

            new_u = data.get("u")

            if (
                new_U is not None
                and
                new_u is not None
            ):

                # =========================
                # INITIALIZE
                # =========================

                if self.last_sequence_end is None:

                    self.last_sequence_end = (
                        new_u
                    )

                else:

                    expected = (
                        self.last_sequence_end + 1
                    )

                    if new_U != expected:

                        ws_debug(
                            "Orderbook sequence gap expected=%s actual=%s",
                            expected,
                            new_U,
                        )

                        self.resnapshot_required = True

                    # =========================
                    # UPDATE AFTER VALIDATION
                    # =========================

                    self.last_sequence_end = (
                        new_u
                    )

            # =========================
            # EMPTY CHECK
            # =========================

            if not bids or not asks:

                ws_debug("Empty WebSocket orderbook")

                return

            # =========================
            # APPLY BID DELTAS
            # =========================

            for bid in bids:

                price = float(
                    bid[0]
                )

                size = float(
                    bid[1]
                )

                if size <= 0:

                    self.bids.pop(
                        price,
                        None
                    )

                else:

                    self.bids[price] = size

            # =========================
            # APPLY ASK DELTAS
            # =========================

            for ask in asks:

                price = float(
                    ask[0]
                )

                size = float(
                    ask[1]
                )

                if size <= 0:

                    self.asks.pop(
                        price,
                        None
                    )

                else:

                    self.asks[price] = size

            # =========================
            # EMPTY LOCAL BOOK
            # =========================

            if (
                not self.bids
                or
                not self.asks
            ):

                ws_debug("Empty local orderbook")

                return

            # =========================
            # RECONSTRUCT BEST PRICE
            # =========================

            self.best_bid = max(
                self.bids.keys()
            )

            self.best_ask = min(
                self.asks.keys()
            )

            self.spread = (
                self.best_ask
                - self.best_bid
            )

            self.last_price = (
                self.best_bid
                + self.best_ask
            ) / 2

            # =========================
            # INVALID BOOK PROTECTION
            # =========================

            if (
                self.best_bid <= 0
                or
                self.best_ask <= 0
            ):

                add_log(
                    "❌ INVALID BOOK",
                    "error"
                )

                return

            # =========================
            # CROSSED BOOK PROTECTION
            # =========================

            if (
                self.best_bid
                >=
                self.best_ask
            ):

                add_log(
                    f"❌ CROSSED BOOK "
                    f"BID={self.best_bid} "
                    f"ASK={self.best_ask}",
                    "error"
                )

                # =========================
                # ROLLBACK
                # =========================

                if (
                    self.last_valid_bid > 0
                    and
                    self.last_valid_ask > 0
                ):

                    self.best_bid = (
                        self.last_valid_bid
                    )

                    self.best_ask = (
                        self.last_valid_ask
                    )

                    self.spread = (
                        self.best_ask
                        - self.best_bid
                    )

                    self.last_price = (
                        self.best_bid
                        + self.best_ask
                    ) / 2

                    add_log(
                        f"♻️ ROLLBACK "
                        f"BID={self.best_bid} "
                        f"ASK={self.best_ask}",
                        "warning"
                    )

                return

            # =========================
            # SAVE VALID BOOK
            # =========================

            self.last_valid_bid = (
                self.best_bid
            )

            self.last_valid_ask = (
                self.best_ask
            )

            # =========================
            # CALLBACK
            # =========================

            self.on_update(
                dict(self.bids),
                dict(self.asks)
            )

        except Exception as e:

            add_log(
                f"❌ ORDERBOOK MESSAGE ERROR: "
                f"{e}",
                "error"
            )

    # =========================
    # OPEN
    # =========================

    def on_open(self, ws):

        self.connected = True

        add_log(
            f"🟢 ORDERBOOK WS CONNECTED: "
            f"{self.symbol}",
            "info"
        )

    # =========================
    # CLOSE
    # =========================

    def on_close(
        self,
        ws,
        close_status_code,
        close_msg,
    ):

        self.connected = False

        add_log(
            "🔴 ORDERBOOK WS CLOSED",
            "warning"
        )

        add_log(
            f"🔴 CLOSE STATUS: "
            f"{close_status_code}",
            "warning"
        )

        add_log(
            f"🔴 CLOSE MESSAGE: "
            f"{close_msg}",
            "warning"
        )

    # =========================
    # ERROR
    # =========================

    def on_error(self, ws, error):

        self.connected = False

        add_log(
            f"❌ ORDERBOOK WS ERROR: "
            f"{error}",
            "error"
        )

    # =========================
    # START
    # =========================

    def start(self):

        self.running = True

        def run():

            while self.running:

                try:

                    add_log(
                        f"🚀 CONNECT URL: "
                        f"{self.url}",
                        "warning"
                    )

                    self.ws = (
                        websocket.WebSocketApp(
                            self.url,

                            on_message=(
                                self.on_message
                            ),

                            on_open=(
                                self.on_open
                            ),

                            on_close=(
                                self.on_close
                            ),

                            on_error=(
                                self.on_error
                            ),
                        )
                    )

                    self.ws.run_forever(
                        ping_interval=20,
                        ping_timeout=10,
                    )

                except Exception as e:

                    add_log(
                        f"❌ WS THREAD ERROR: "
                        f"{e}",
                        "error"
                    )

                add_log(
                    "♻️ RECONNECT IN 5 SEC",
                    "warning"
                )

                time.sleep(5)

        threading.Thread(
            target=run,
            daemon=True
        ).start()

    # =========================
    # STOP
    # =========================

    def stop(self):

        self.running = False

        if self.ws:

            self.ws.close()
