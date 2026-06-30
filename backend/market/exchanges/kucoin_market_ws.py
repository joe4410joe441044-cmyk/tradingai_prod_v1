# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time
import requests
import uuid

from backend.utils.log_buffer import add_log, logger, ws_debug


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

        ws_debug(
            "KuCoin symbol map '%s' -> '%s'",
            symbol,
            normalized,
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

            ws_debug(
                "Requesting KuCoin orderbook snapshot url=%s",
                url,
            )

            response = requests.get(
                url,
                timeout=10
            )

            data = response.json()

            ws_debug(
                "KuCoin snapshot response=%s",
                data,
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
                f"asks={len(self.asks)}"
            )

            ws_debug(
                "KuCoin snapshot bid_levels=%s ask_levels=%s",
                sorted(self.bids.keys(), reverse=True)[:10],
                sorted(self.asks.keys())[:10],
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
            ws_debug(
                "KuCoin first WebSocket message=%s",
                message[:300],
            )
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

                ws_debug("KuCoin snapshot not loaded; loading now")

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

                ws_debug("KuCoin message contained no orderbook change")

                return


            try:

                price, side, size = (
                    change.split(",")
                )

                price = float(price)

                size = float(size)
            
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

                ws_debug(
                    "Empty KuCoin local book bids=%d asks=%d",
                    len(self.bids),
                    len(self.asks),
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

                common = (
                    set(self.bids.keys())
                    &
                    set(self.asks.keys())
                )

                ws_debug(
                    "Crossed KuCoin book details top_bids=%s common_prices=%s",
                    sorted(self.bids.keys(), reverse=True)[:50],
                    sorted(list(common))[:20],
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

            # =========================
            # MID PRICE
            # =========================

            self.last_price = (
                self.best_bid
                + self.best_ask
            ) / 2

            ws_debug(
                "KuCoin delta sequence=%s side=%s price=%s size=%s "
                "best_bid=%s best_ask=%s mid_price=%s spread=%s",
                sequence,
                side,
                price,
                size,
                self.best_bid,
                self.best_ask,
                self.last_price,
                self.spread,
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

        if self.running:

            add_log(
                "⚠️ WS ALREADY RUNNING",
                "warning"
            )

            return

        self.running = True

        def run():

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

                    ws_debug(
                        "Creating KuCoin WebSocket symbol=%s",
                        self.symbol,
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

                    add_log(
                        "⚠️ WS DISCONNECTED",
                        "warning"
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
