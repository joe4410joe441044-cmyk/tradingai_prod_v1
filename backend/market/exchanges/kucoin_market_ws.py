# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time
import requests
import uuid
import logging

from backend.utils.log_buffer import add_log

logger = logging.getLogger(__name__)


class OrderBookWS:

    def normalize_symbol(self, symbol):

        mapping = {

            "BTCUSDT": "XBTUSDTM",

            "XBTUSDT": "XBTUSDTM",

            "ETHUSDT": "ETHUSDTM",

            "XRPUSDT": "XRPUSDTM",

        }

        normalized = mapping.get(
            symbol,
            symbol
        )

        logger.warning(
            f"[SYMBOL MAP] "
            f"'{symbol}' -> "
            f"'{normalized}'"
        )

        return normalized

    def __init__(
        self,
        symbol,
        on_update,
        runtime_id,
    ):

        self.original_symbol = symbol.upper()

        self.symbol = self.normalize_symbol(
            self.original_symbol
        )

        self.url = None

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

        self.last_price_update = time.time()

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
    # LOAD SNAPSHOT
    # =========================

    def load_snapshot(self):

        try:

            url = (
                "https://api-futures.kucoin.com"
                f"/api/v1/level2/snapshot?symbol={self.symbol}"
            )

            add_log(
                f"📸 REQUEST SNAPSHOT: {url}",
                "warning"
            )

            response = requests.get(
                url,
                timeout=10
            )

            data = response.json()

            add_log(
                f"📸 SNAPSHOT RESPONSE: {data}",
                "warning"
            )

            snapshot = (
                data.get("data", {})
            )

            bids = snapshot.get(
                "bids",
                []
            )

            asks = snapshot.get(
                "asks",
                []
            )

            self.bids = {
                float(price): float(size)
                for price, size in bids
            }

            self.asks = {
                float(price): float(size)
                for price, size in asks
            }

            self.snapshot_loaded = True

            self.orderbook_initialized = True

            add_log(
                f"📸 SNAPSHOT LOADED "
                f"bids={len(self.bids)} "
                f"asks={len(self.asks)}",
                "warning"
            )

            print(
                f"📸 SNAPSHOT LOADED "
                f"bids={len(self.bids)} "
                f"asks={len(self.asks)}"
            )
            print(
                "[SNAPSHOT TOP BIDS]",
                sorted(
                    self.bids.keys(),
                    reverse=True
                )[:10]
            )

            print(
                "[SNAPSHOT TOP ASKS]",
                sorted(
                    self.asks.keys()
                )[:10]
            )

        except Exception as e:

            add_log(
                f"❌ SNAPSHOT LOAD ERROR: {e}",
                "error"
            )


    # =========================
    # MESSAGE
    # =========================

    def on_message(self, ws, message):
        
        if not hasattr(self, "_first_msg"):
            print("[FIRST WS MESSAGE]")
            print(message[:300])
            self._first_msg = True


        try:

            data = json.loads(message)

            # =========================
            # MESSAGE FILTER
            # =========================

            if data.get("type") != "message":

                return

            # =========================
            # SNAPSHOT CHECK
            # =========================

            if not self.snapshot_loaded:

                add_log(
                    "📸 SNAPSHOT NOT LOADED",
                    "warning"
                )

                self.load_snapshot()
                
            # =========================
            # FUTURES CHANGE
            # =========================


            change = (
                data.get("data", {})
                    .get("change")
            )
            sequence = (
                data.get("data", {})
                    .get("sequence")
            )

            if not change:

                add_log(
                    "⚠️ EMPTY CHANGE",
                    "warning"
                )

                return


            try:

                price, side, size = (
                    change.split(",")
                )

                price = float(price)

                size = float(size)
            
                print(
                    "[CHANGE DEBUG]",
                    sequence,
                    price,
                    side,
                    size
                )
            except Exception as e:

                add_log(
                    f"❌ CHANGE PARSE ERROR: "
                    f"{e}",
                    "error"
                )

                return

            # =========================
            # APPLY DELTAS
            # =========================

            print(
                "[BOOK UPDATE]",
                side,
                price,
                size
            )

            if side == "buy":

                if size <= 0:

                    self.bids.pop(
                        price,
                        None
                    )

                else:

                    self.bids[price] = size

            elif side == "sell":

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

                add_log(
                    "⚠️ EMPTY LOCAL BOOK",
                    "warning"
                )

                add_log(
                    f"⚠️ EMPTY DETAIL "
                    f"bids={len(self.bids)} "
                    f"asks={len(self.asks)}",
                    "warning"
                )

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


            print(
                "[TOP BIDS]",
                sorted(
                    self.bids.keys(),
                    reverse=True
                )[:10]
            )

            print(
                "[TOP ASKS]",
                sorted(
                    self.asks.keys()
                )[:10]
            )

            # =========================
            # EMPTY CHECK
            # =========================

            if (
                self.best_bid
                >=
                self.best_ask
            ):

                add_log(
                    f"❌ CROSSED BOOK "
                    f"SEQ={sequence} "
                    f"BID={self.best_bid} "
                    f"ASK={self.best_ask}",
                    "error"
                )

                add_log(
                    f"TOP BIDS "
                    f"{sorted(self.bids.keys(), reverse=True)[:50]}",
                    "error"
                )

                common = (
                    set(self.bids.keys())
                    &
                    set(self.asks.keys())
                )

                add_log(
                    f"COMMON_PRICES="
                    f"{sorted(list(common))[:20]}",
                    "error"
                )

                add_log(
                    "🔄 RESNAPSHOT TRIGGER",
                    "error"
                )

                self.snapshot_loaded = False

                self.bids.clear()

                self.asks.clear()

                self.load_snapshot()

                return

            # =========================
            # SPREAD
            # =========================

            self.spread = (
                self.best_ask
                - self.best_bid
            )

            add_log(
                f"📊 BID={self.best_bid} "
                f"ASK={self.best_ask} "
                f"SPREAD={self.spread}",
                "info"
            )

            # =========================
            # MID PRICE
            # =========================
            print(
                "[BEST PRICE]",
                self.best_bid,
                self.best_ask,
                self.last_price
            )

            self.last_price = (
                self.best_bid
                + self.best_ask
            ) / 2

            print(
                "[BEST DEBUG]",
                self.best_bid,
                self.best_ask,
                self.last_price
            )

            self.last_price_update = time.time()

            # =========================
            # INVALID BOOK
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
            # CROSSED BOOK
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
            # LOG
            # =========================

            add_log(
                f"📊 "
                f"BID={self.best_bid} "
                f"ASK={self.best_ask} "
                f"SPREAD={self.spread}",
                "info"
            )
            print(
                "[SEND PRICE]",
                self.best_bid,
                self.best_ask,
                self.last_price
            )

            # =========================
            # CALLBACK
            # =========================

            self.on_update(
                self.original_symbol,
                {
                    "symbol": self.original_symbol,
                    "best_bid": self.best_bid,
                    "best_ask": self.best_ask,
                    "spread": self.spread,
                    "price": self.last_price,
                    "bids": self.bids,
                    "asks": self.asks,
                },
                self.runtime_id
            )

        except Exception as e:

            add_log(
                f"❌ KUCOIN PARSE ERROR: "
                f"{e}",
                "error"
            )

    # =========================
    # OPEN
    # =========================

    def on_open(self, ws):
        print("[WS OPEN]")

        self.connected = True

        add_log(
            "🟢 KUCOIN WS CONNECTED",
            "success"
        )

        self.load_snapshot()

        subscribe_data = {

            "id": str(
                int(time.time() * 1000)
            ),

            "type": "subscribe",

            "topic": (
                f"/contractMarket/level2:"
                f"{self.symbol}"
            ),

            "privateChannel": False,

            "response": True
        }

        ws.send(
            json.dumps(
                subscribe_data
            )
        )

        add_log(
            f"📡 SUBSCRIBED: "
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
        print(
            "[WS CLOSED]",
            close_status_code,
            close_msg
        )

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
        print("[WS ERROR]", error)

        self.connected = False

        add_log(
            f"❌ ORDERBOOK WS ERROR: "
            f"{error}",
            "error"
        )

    # =========================
    # TOKEN
    # =========================

    def _get_ws_token(self):

        url = (
            "https://api-futures.kucoin.com"
            "/api/v1/bullet-public"
        )

        response = requests.post(
            url,
            timeout=10
        )

        data = response.json()

        token = data["data"]["token"]

        endpoint = (
            data["data"]
            ["instanceServers"][0]
            ["endpoint"]
        )

        return token, endpoint

    # =========================
    # START
    # =========================

    def start(self):

        add_log("[TRACE] ORDERBOOK START")

        print("[ORDERBOOK START]")

        if self.running:

            add_log(
                "⚠️ WS ALREADY RUNNING",
                "warning"
            )

            logger.warning(
                "[WS ALREADY RUNNING]"
            )

            return

        self.running = True

        def run():

            add_log("[TRACE] ORDERBOOK RUN")

            print("[ORDERBOOK RUN]")

            while self.running:
                now = time.time()

                if (
                    self.connected
                    and
                    now - self.last_price_update > 15
                ):

                    add_log(
                        "⚠️ STALE MARKET DATA",
                        "warning"
                    )

                    logger.warning(
                        "[STALE MARKET DATA]"
                    )

                    self.connected = False

                    try:

                        if self.ws:

                            self.ws.close()

                    except Exception:

                        pass

                try:

                    token, endpoint = (
                        self._get_ws_token()
                    )

                    connect_id = str(
                        uuid.uuid4()
                    )

                    self.url = (
                        f"{endpoint}"
                        f"?token={token}"
                        f"&connectId={connect_id}"
                    )

                    add_log(
                        f"🚀 CONNECT URL: "
                        f"{self.url}",
                        "warning"
                    )
                    add_log("[TRACE] CREATING WEBSOCKET")

                    print("[CREATING WEBSOCKET]")

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

                    add_log("[TRACE] RUN FOREVER")
                    
                    print("[RUN FOREVER]")

                    self.ws.run_forever(
                        ping_interval=20,
                        ping_timeout=10,
                    )
                    self.connected = False

                    add_log(
                        "⚠️ WS DISCONNECTED",
                        "warning"
                    )

                    logger.warning(
                        "[WS DISCONNECTED]"
                    )

                except Exception as e:

                    self.connected = False

                    add_log(
                        f"❌ WS THREAD ERROR: "
                        f"{e}",
                        "error"
                    )

                    logger.exception(
                        "[WS RECONNECT ERROR]"
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

        self.connected = False

        add_log(
            "🛑 WS STOP",
            "warning"
        )

        logger.warning(
            "[WS STOP]"
        )

        if self.ws:

            self.ws.close()
