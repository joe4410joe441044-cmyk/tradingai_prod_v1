# -*- coding: utf-8 -*-

# =========================
# IMPORTS
# =========================

import time
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.core.orderbook_manager import OrderBookManager

from backend.strategy.orderflow_depth_strategy import (
    OrderFlowDepthStrategy,
)

from backend.ws.orderbook_ws import OrderBookWS

from backend.utils.log_buffer import add_log

from backend.core.logger import logger


from Bot.engine.execution_engine import (
    ExecutionEngine
)





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

        self.market_ready = False

        self.last_update_time = 0

        # =========================
        # POSITION
        # =========================

        self.position = "NONE"

        self.entry_price = None

        # =========================
        # RISK
        # =========================

        self.tp_percent = 2.0

        self.sl_percent = 1.0

    # =========================
    # START
    # =========================

    def start(self, config):

        try:

            # =========================
            # RESET
            # =========================

            self.stop()

            self.position = "NONE"

            self.entry_price = None

            self.last_signal = None

            self.last_price = 0

            self.market_ready = False

            self.last_update_time = 0

            self.symbol = config["symbol"].upper()

            # =========================
            # CONFIG
            # =========================

            self.tp_percent = config.get(
                "tp_percent",
                2.0
            )

            self.sl_percent = config.get(
                "sl_percent",
                1.0
            )

            add_log(
                f"🚀 START BOT: "
                f"{self.symbol}"
            )

            # =========================
            # ORDERBOOK
            # =========================

            self.ob_manager = (
                OrderBookManager()
            )

            # =========================
            # EXECUTION ENGINE
            # =========================

            portfolio = PortfolioManager(
                initial_balance=1000
            )

            self.engine = ExecutionEngine(
                exchange=None,
                logger=logger,
                portfolio=portfolio,
                notifier=None,
                price_manager=self.ob_manager
            )

            self.engine.symbol = self.symbol
            
            
            # =========================
            # ENGINE START
            # =========================

            self.engine.start()
            
            
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

                logger.debug(
                    "📥 on_update CALLED"
                )

                try:

                    # =========================
                    # ORDERBOOK UPDATE
                    # =========================

                    self.ob_manager.update(
                        bids,
                        asks
                    )

                    logger.debug(
                        "✅ MANAGER UPDATED"
                    )

                    # =========================
                    # BEST PRICE
                    # =========================

                    try:

                        if bids:

                            self.last_price = float(
                                bids[0][0]
                            )

                            self.market_ready = True

                            self.last_update_time = (
                                time.time()
                            )

                    except Exception as e:

                        logger.debug(
                            f"❌ PRICE ERROR: "
                            f"{e}"
                        )

                    # =========================
                    # ENGINE PRICE EVENT
                    # =========================

                    if self.engine:

                        try:

                            self.engine.on_price(
                                self.symbol,
                                self.last_price
                            )

                        except Exception as e:

                            logger.debug(
                                f"❌ ENGINE PRICE ERROR: "
                                f"{e}"
                            )

                    # =========================
                    # STRATEGY
                    # =========================

                    logger.debug(
                        "🚀 CALL STRATEGY"
                    )

                    signal = (
                        self.strategy
                        .on_orderbook()
                    )

                    logger.debug(
                        f"🧠 STRATEGY RESULT: "
                        f"{signal}"
                    )

                    # =========================
                    # SIGNAL
                    # =========================

                    if signal:

                        self.last_signal = signal

                        add_log(
                            f"🟡 SIGNAL: "
                            f"{signal}"
                        )

                        # =========================
                        # EXECUTION ENGINE
                        # =========================

                        if self.engine:

                            try:

                                self.engine.submit_signal(
                                    signal
                                )

                            except Exception as e:

                                logger.debug(
                                    f"❌ ENGINE ERROR: "
                                    f"{e}"
                                )

                except Exception as e:

                    logger.debug(
                        f"❌ on_update ERROR: "
                        f"{e}"
                    )

            # =========================
            # WS START
            # =========================

            self.ws = OrderBookWS(
                self.symbol,
                on_update
            )

            self.ws.start()

            logger.debug(
                "🔥 WS START CALLED"
            )

            self._running = True

            add_log(
                "🟢 ORDERBOOK WS STARTED"
            )

            return {
                "status": "started",
                "symbol": self.symbol,
            }

        except Exception as e:

            add_log(
                f"❌ BOT START ERROR: "
                f"{e}"
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

            self.position = "NONE"

            self.entry_price = None

            self.last_signal = None

            self.last_price = 0

            self.market_ready = False

            self.last_update_time = 0

            add_log(
                "🛑 BOT STOPPED"
            )

            return {
                "status": "stopped"
            }

        except Exception as e:

            add_log(
                f"❌ STOP ERROR: "
                f"{e}"
            )

            return {
                "status": "error",
                "reason": str(e),
            }

    # =========================
    # RESULT
    # =========================

    def get_result(self):

        stale_seconds = 0

        if self.last_update_time > 0:

            stale_seconds = (
                time.time()
                - self.last_update_time
            )

        market_stale = (
            stale_seconds > 5
        )

        safe_price = (
            self.last_price
            if self.market_ready
            else None
        )

        actual_position = None

        pending_order = False

        if self.engine:

            actual_position = getattr(
                self.engine,
                "actual_position",
                None
            )

            pending_order = getattr(
                self.engine,
                "pending_order",
                False
            )

        return {

            "timestamp": time.time(),

            "price": safe_price,

            "marketReady":
                self.market_ready,

            "marketStale":
                market_stale,

            "lastUpdateAge":
                stale_seconds,

            "pnl": 0,

            "balance": 1000,

            "equity": 1000,

            "position": actual_position,

            "pendingOrder": pending_order,

            "signal":
                self.last_signal,

            "symbol":
                self.symbol,

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

                "status": "STOPPED",

                "symbol": None,

                "price": None,

                "marketReady": False,

                "marketStale": False,

                "lastUpdateAge": 0,

                "pnl": 0,

                "balance": 1000,

                "equity": 1000,

                "position": None,

                "pendingOrder": False,

                "signal": None,

                "botStatus": "STOPPED",
            }

        result = self.get_result() or {}

        return {

            **result,

            "status": result.get(
                "status",
                "STOPPED"
            ),

            "symbol": result.get(
                "symbol",
                None
            ),

            "price": result.get(
                "price",
                None
            ),

            "marketReady": result.get(
                "marketReady",
                False
            ),

            "marketStale": result.get(
                "marketStale",
                False
            ),

            "lastUpdateAge": result.get(
                "lastUpdateAge",
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
                None
            ),

            "pendingOrder": result.get(
                "pendingOrder",
                False
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