# -*- coding: utf-8 -*-

import websocket
import json
import threading
import time


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

        self.connected = False

        self.running = False

    # =========================
    # MESSAGE
    # =========================

    def on_message(self, ws, message):

        print("🔥 MESSAGE RECEIVED")

        try:

            print(message[:300])

            data = json.loads(message)

            bids = data.get("b", [])

            asks = data.get("a", [])

            print(
                f"📊 BIDS={len(bids)} "
                f"ASKS={len(asks)}"
            )

            if bids and asks:

                self.best_bid = float(
                    bids[0][0]
                )

                self.best_ask = float(
                    asks[0][0]
                )

                self.spread = (
                    self.best_ask
                    - self.best_bid
                )

                self.last_price = (
                    self.best_bid
                    + self.best_ask
                ) / 2

                print(
                    f"💰 BEST BID: "
                    f"{self.best_bid}"
                )

                print(
                    f"💰 BEST ASK: "
                    f"{self.best_ask}"
                )

                print(
                    f"💰 SPREAD: "
                    f"{self.spread}"
                )

                print(
                    f"💰 MID PRICE: "
                    f"{self.last_price}"
                )

            # BOTへ渡す
            self.on_update(
                bids,
                asks
            )

        except Exception as e:

            print(
                f"❌ ORDERBOOK MESSAGE ERROR: {e}"
            )

    # =========================
    # OPEN
    # =========================

    def on_open(self, ws):

        self.connected = True

        print(
            f"🟢 ORDERBOOK WS CONNECTED: "
            f"{self.symbol}"
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

        print(
            "🔴 ORDERBOOK WS CLOSED"
        )

        print(
            f"🔴 CLOSE STATUS: "
            f"{close_status_code}"
        )

        print(
            f"🔴 CLOSE MESSAGE: "
            f"{close_msg}"
        )

    # =========================
    # ERROR
    # =========================

    def on_error(self, ws, error):

        self.connected = False

        print(
            f"❌ ORDERBOOK WS ERROR: "
            f"{error}"
        )

    # =========================
    # START
    # =========================

    def start(self):

        self.running = True

        def run():

            while self.running:

                try:

                    print(
                        f"🚀 CONNECT URL: "
                        f"{self.url}"
                    )

                    print(
                        "🚀 RUN_FOREVER START"
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

                    print(
                        f"❌ WS THREAD ERROR: {e}"
                    )

                print(
                    "♻️ RECONNECT IN 5 SEC"
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