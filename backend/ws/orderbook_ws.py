# -*- coding: utf-8 -*-

import websocket
import json
import threading


class OrderBookWS:

    def __init__(self, symbol, on_update):

        self.symbol = symbol.lower()

        self.url = (
            f"wss://stream.binance.com:9443/ws/"
            f"{self.symbol}@depth"
        )

        self.on_update = on_update

        self.ws = None

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

        print(
            "🔴 ORDERBOOK WS CLOSED"
        )

    # =========================
    # ERROR
    # =========================

    def on_error(self, ws, error):

        print(
            f"❌ ORDERBOOK WS ERROR: "
            f"{error}"
        )

    # =========================
    # START
    # =========================

    def start(self):

        def run():

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

                self.ws.run_forever()

            except Exception as e:

                print(
                    f"❌ WS THREAD ERROR: {e}"
                )

        threading.Thread(
            target=run
        ).start()

    # =========================
    # STOP
    # =========================

    def stop(self):

        if self.ws:

            self.ws.close()