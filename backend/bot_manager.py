# -*- coding: utf-8 -*-

# =========================
# IMPORTS
# =========================

from backend.core.orderbook_manager import OrderBookManager
from backend.strategy.orderflow_depth_strategy import (
    OrderFlowDepthStrategy,
)
from backend.ws.orderbook_ws import OrderBookWS

from backend.utils.log_buffer import add_log


# =========================
# BOT MANAGER
# =========================

class BotManager:

    def __init__(self):

        self.engine = None

        self.price_manager = None

        self._running = False

        self.symbol = None

        # =========================
        # ORDERFLOW COMPONENTS
        # =========================

        self.ob_manager = None

        self.strategy = None

        self.ws = None

        # =========================
        # STATUS
        # =========================

        self.last_signal = None

        self.last_price = 0

    # =========================
    # START
    # =========================

    def start(self, config):

        try:

            # =========================
            # 既存停止
            # =========================

            self.stop()

            self.symbol = config["symbol"].upper()

            add_log(
                f"🚀 START BOT: {self.symbol}"
            )

            # =========================
            # ORDERBOOK
            # =========================

            self.ob_manager = (
                OrderBookManager()
            )

            # =========================
            # STRATEGY
            # =========================

            self.strategy = (
                OrderFlowDepthStrategy(
                    self.ob_manager
                )
            )

            # =========================
            # WS CALLBACK
            # =========================

            def on_update(bids, asks):

                # =========================
                # ORDERBOOK UPDATE
                # =========================

                self.ob_manager.update(
                    bids,
                    asks
                )

                # =========================
                # BEST PRICE
                # =========================

                try:

                    if bids:

                        self.last_price = float(
                            bids[0][0]
                        )

                except Exception:

                    pass

                # =========================
                # STRATEGY
                # =========================

                signal = (
                    self.strategy
                    .on_orderbook()
                )

                # =========================
                # SIGNAL
                # =========================

                if signal:

                    self.last_signal = signal

                    add_log(
                        f"🟡 SIGNAL: {signal}"
                    )

            # =========================
            # WS START
            # =========================

            self.ws = OrderBookWS(
                self.symbol,
                on_update
            )

            self.ws.start()

            print(
                "🔥 WS START CALLED"
            )

            self._running = True

            # =========================
            # ENGINE DUMMY
            # =========================

            self.engine = self

            add_log(
                "🟢 ORDERBOOK WS STARTED"
            )

            return {
                "status": "started",
                "symbol": self.symbol,
            }

        except Exception as e:

            add_log(
                f"❌ BOT START ERROR: {e}"
            )

            return {
                "status": "error",
                "reason": str(e),
            }

    # =========================
    # STOP
    # =========================

    def stop(self):

        try:

            if self.ws:

                self.ws.stop()

            self.ws = None

            self.strategy = None

            self.ob_manager = None

            self.engine = None

            self._running = False

            add_log(
                "🛑 BOT STOPPED"
            )

            return {
                "status": "stopped"
            }

        except Exception as e:

            add_log(
                f"❌ STOP ERROR: {e}"
            )

            return {
                "status": "error",
                "reason": str(e),
            }

    # =========================
    # RESULT
    # =========================

    def get_result(self):

        return {

            "price": self.last_price,

            "pnl": 0,

            "balance": 1000,

            "equity": 1000,

            "position": "NONE",

            "entryPrice": None,

            "signal": self.last_signal,

            "status": (
                "RUNNING"
                if self._running
                else "STOPPED"
            ),
        }

    # =========================
    # STATUS
    # =========================

    def get_status(self):

        if self.engine is None:

            return {

                "price": 0,

                "pnl": 0,

                "balance": 1000,

                "equity": 1000,

                "position": "NONE",

                "entryPrice": None,

                "botStatus": "STOPPED",
            }

        result = self.get_result() or {}

        return {

            **result,

            "price": result.get(
                "price",
                0
            ),

            "pnl": result.get(
                "pnl",
                0
            ),

            "balance": result.get(
                "balance",
                1000
            ),

            "equity": result.get(
                "equity",
                1000
            ),

            "position": result.get(
                "position",
                "NONE"
            ),

            "entryPrice": result.get(
                "entryPrice",
                None
            ),

            "signal": result.get(
                "signal",
                None
            ),

            "botStatus": result.get(
                "status",
                "STOPPED"
            ),
        }


# =========================
# GLOBAL INSTANCE
# =========================

_bot_manager = None


# =========================
# GET BOT MANAGER
# =========================

def get_bot_manager():

    global _bot_manager

    if _bot_manager is None:

        _bot_manager = BotManager()

    return _bot_manager