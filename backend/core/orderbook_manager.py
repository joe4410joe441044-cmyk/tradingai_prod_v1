# -*- coding: utf-8 -*-
from backend.utils.log_buffer import logger, ws_debug


class OrderBookManager:

    def __init__(
        self,
        callback=None
    ):

        # =========================
        # CALLBACK
        # =========================

        self.callback = callback

        # =========================
        # LOCAL ORDERBOOK
        # =========================

        self.bids = {}

        self.asks = {}

        # =========================
        # PRICE
        # =========================

        self.current_price = 0.0

        self.best_bid = 0.0

        self.best_ask = 0.0

        self.spread = 0.0

        # =========================
        # VOLUME
        # =========================

        self.bid_volume = 0.0

        self.ask_volume = 0.0

        self.imbalance = 0.0

    # =========================
    # UPDATE
    # =========================

    def update(self, bids, asks):
        """
        reconstructed local orderbook 更新
        """

        # =========================
        # EMPTY CHECK
        # =========================

        if not bids or not asks:
            ws_debug(
                "EMPTY ORDERBOOK bids=%d asks=%d",
                len(bids),
                len(asks),
            )

            return

        # =========================
        # LOCAL BOOK SNAPSHOT
        # =========================

        self.bids = dict(bids)

        self.asks = dict(asks)

        # =========================
        # EMPTY CHECK
        # =========================

        if (
            not self.bids
            or
            not self.asks
        ):

            ws_debug(
                "EMPTY LOCAL ORDERBOOK bids=%d asks=%d",
                len(self.bids),
                len(self.asks),
            )

            return

        # =========================
        # BEST PRICE
        # =========================

        self.best_bid = max(
            self.bids.keys()
        )

        self.best_ask = min(
            self.asks.keys()
        )

        # =========================
        # CROSSED BOOK PROTECTION
        # =========================

        if (
            self.best_bid
            >=
            self.best_ask
        ):

            ws_debug(
                "CROSSED ORDERBOOK bid=%s ask=%s",
                self.best_bid,
                self.best_ask,
            )

            return

        # =========================
        # PRICE / SPREAD
        # =========================

        self.current_price = (
            self.best_bid
            + self.best_ask
        ) / 2

        self.spread = (
            self.best_ask
            - self.best_bid
        )

        # =========================
        # TOP LEVELS
        # =========================

        top_bid_prices = sorted(
            self.bids.keys(),
            reverse=True
        )[:5]

        top_ask_prices = sorted(
            self.asks.keys()
        )[:5]

        # =========================
        # VOLUME
        # =========================

        self.bid_volume = sum(
            self.bids[p]
            for p in top_bid_prices
        )

        self.ask_volume = sum(
            self.asks[p]
            for p in top_ask_prices
        )

        total_volume = (
            self.bid_volume
            + self.ask_volume
        )

        # =========================
        # IMBALANCE
        # =========================

        if total_volume > 0:

            self.imbalance = (
                self.bid_volume
                - self.ask_volume
            ) / total_volume

        else:

            self.imbalance = 0.0

        ws_debug(
            "OrderBook snapshot bids=%d asks=%d best_bid=%s "
            "best_ask=%s price=%s spread=%s bid_volume=%s "
            "ask_volume=%s imbalance=%s",
            len(self.bids),
            len(self.asks),
            self.best_bid,
            self.best_ask,
            self.current_price,
            self.spread,
            self.bid_volume,
            self.ask_volume,
            self.imbalance,
        )

        # =========================
        # CALLBACK
        # =========================

        if self.callback:
            self.callback(
                self.current_price,
                self.best_bid,
                self.best_ask,
                self.bid_volume,
                self.ask_volume,
            )

    # =========================
    # GET TOP N VOLUME
    # =========================

    def get_top_n_volume(self, n=5):

        if (
            not self.bids
            or
            not self.asks
        ):

            ws_debug(
                "EMPTY ORDERBOOK in get_top_n_volume"
            )

            return 0.0, 0.0

        try:

            top_bid_prices = sorted(
                self.bids.keys(),
                reverse=True
            )[:n]

            top_ask_prices = sorted(
                self.asks.keys()
            )[:n]

            bid_vol = sum(
                self.bids[p]
                for p in top_bid_prices
            )

            ask_vol = sum(
                self.asks[p]
                for p in top_ask_prices
            )

            ws_debug(
                "OrderBook top-n volume n=%d bid_volume=%s ask_volume=%s",
                n,
                bid_vol,
                ask_vol,
            )

            return bid_vol, ask_vol

        except Exception:

            logger.exception("OrderBook volume error")

            return 0.0, 0.0

    # =========================
    # GET BEST BID ASK
    # =========================

    def get_best_bid_ask(self):

        if (
            not self.bids
            or
            not self.asks
        ):

            return None, None

        best_bid = max(
            self.bids.keys()
        )

        best_ask = min(
            self.asks.keys()
        )

        return best_bid, best_ask

    # =========================
    # GET CURRENT PRICE
    # =========================

    def get_current_price(self):

        logger.error(
            f"🟢 GET_CURRENT_PRICE="
            f"{self.current_price}"
        )

        return self.current_price

    # =========================
    # GET SPREAD
    # =========================

    def get_spread(self):

        return self.spread

    # =========================
    # GET IMBALANCE
    # =========================

    def get_imbalance(self):

        return self.imbalance

    # =========================
    # MARKET SNAPSHOT
    # =========================

    def get_market_snapshot(self):

        return {
            "current_price": self.current_price,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread": self.spread,
            "bid_volume": self.bid_volume,
            "ask_volume": self.ask_volume,
            "imbalance": self.imbalance,
        }
