# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time
import requests

from backend.utils.log_buffer import add_log, ws_debug


class OrderBookWS:

    MARKET_TYPE = "SPOT"

    def __init__(
        self,
        symbol,
        on_update,
        runtime_id,
    ):

        self.original_symbol = symbol.upper()

        self.symbol = self.original_symbol.lower()

        self.url = (
            "wss://stream.binance.com:9443/ws/"
            f"{self.symbol}@depth"
        )

        self.on_update = on_update

        self.runtime_id = runtime_id

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
    # SNAPSHOT
    # =========================

    def load_orderbook_snapshot(self):

        self.snapshot_loaded = False

        try:

            url = (
                "https://api.binance.com"
                "/api/v3/depth"
                f"?symbol={self.original_symbol}&limit=5000"
            )

            add_log(
                f"📚 LOADING SNAPSHOT: "
                f"{self.original_symbol}",
                "info"
            )

            response = requests.get(
                url,
                timeout=10
            )

            data = response.json()

            if "lastUpdateId" not in data:

                add_log(
                    f"❌ INVALID SNAPSHOT: "
                    f"{data}",
                    "error"
                )

                return

            self.bids.clear()

            self.asks.clear()

            # =========================
            # LOAD BIDS
            # =========================

            for bid in data["bids"]:

                price = float(
                    bid[0]
                )

                size = float(
                    bid[1]
                )

                self.bids[price] = size

            # =========================
            # LOAD ASKS
            # =========================

            for ask in data["asks"]:

                price = float(
                    ask[0]
                )

                size = float(
                    ask[1]
                )

                self.asks[price] = size

            # =========================
            # EMPTY CHECK
            # =========================

            if (
                not self.bids
                or
                not self.asks
            ):

                add_log(
                    "❌ EMPTY SNAPSHOT",
                    "error"
                )

                return

            # =========================
            # RECONSTRUCT
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
            # SAVE VALID BOOK
            # =========================

            self.last_valid_bid = (
                self.best_bid
            )

            self.last_valid_ask = (
                self.best_ask
            )

            self.snapshot_loaded = True

            self.snapshot_sequence = int(
                data["lastUpdateId"]
            )

            self.last_sequence_end = self.snapshot_sequence

            add_log(
                f"📚 SNAPSHOT LOADED "
                f"BIDS={len(self.bids)} "
                f"ASKS={len(self.asks)} "
                f"BID={self.best_bid} "
                f"ASK={self.best_ask} "
                f"SPREAD={self.spread}",
                "success"
            )

        except Exception as e:

            add_log(
                f"❌ SNAPSHOT ERROR: "
                f"{e}",
                "error"
            )

    # =========================
    # MESSAGE
    # =========================

    def on_message(self, ws, message):

        try:

            data = json.loads(message)

            bids = data.get("b", [])

            asks = data.get("a", [])

            # =========================
            # SNAPSHOT PROTECTION
            # =========================

            if not self.snapshot_loaded:

                ws_debug("Binance snapshot not loaded")

                return

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

                if new_u <= self.last_sequence_end:
                    return

                expected = self.last_sequence_end + 1

                if new_U > expected:
                    add_log(
                        f"⚠️ BINANCE SEQUENCE GAP "
                        f"EXPECTED={expected} "
                        f"ACTUAL={new_U}",
                        "warning"
                    )

                    self.snapshot_loaded = False

                    self.load_orderbook_snapshot()

                    return

                self.last_sequence_end = new_u

            # =========================
            # EMPTY CHECK
            # =========================

            if not bids and not asks:

                ws_debug("Empty Binance WebSocket book")

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

                ws_debug("Empty Binance local orderbook")

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
                self.original_symbol,
                {
                    "symbol": self.original_symbol,
                    "exchange_symbol": self.original_symbol,
                    "market_type": self.MARKET_TYPE,
                    "market_timestamp": time.time(),
                    "sequence": self.last_sequence_end,
                    "bids": dict(self.bids),
                    "asks": dict(self.asks),
                    "best_bid": self.best_bid,
                    "best_ask": self.best_ask,
                    "spread": self.spread,
                    "price": self.last_price,
                },
                self.runtime_id
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

        self.load_orderbook_snapshot()

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

                    self.connected = False

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
