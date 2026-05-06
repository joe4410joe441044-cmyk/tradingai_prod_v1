# -*- coding: utf-8 -*-

# =========================
# BOT MANAGER
# =========================

class BotManager:

    def __init__(self):

        self.engine = None

        self.price_manager = None

        self._running = False

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

        result = self.engine.get_result() or {}

        symbol = getattr(
            self.engine,
            "symbol",
            None
        )

        price = 0

        if (
            symbol
            and self.price_manager
        ):

            try:

                price = (
                    self.price_manager
                    .prices
                    .get(symbol, 0)
                )

            except Exception:

                price = 0

        return {

            **result,

            "price": price,

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

            "botStatus": (
                result.get("status")
                or (
                    "RUNNING"
                    if self._running
                    else "STOPPED"
                )
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