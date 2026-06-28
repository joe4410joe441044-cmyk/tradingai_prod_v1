# -*- coding: utf-8 -*-
from backend.utils.log_buffer import add_log
from backend.core.logger import logger


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

        print("🔥 UPDATE ENTER")

        print(
            f"📥 MANAGER UPDATE "
            f"bids={len(bids)} "
            f"asks={len(asks)}"
        )

        # =========================
        # EMPTY CHECK
        # =========================

        print(
            f"TRACE INPUT "
            f"bids={len(bids)} "
            f"asks={len(asks)}"
        )

        if not bids or not asks:

            print(
                "⚠️ EMPTY ORDERBOOK"
            )

            print(
                "❌ RETURN EMPTY INPUT "
                f"bids={len(bids)} "
                f"asks={len(asks)}"
            )

            return

        # =========================
        # LOCAL BOOK SNAPSHOT
        # =========================

        self.bids = dict(bids)

        self.asks = dict(asks)

        add_log(
            f"🔥 WS OB INSTANCE={id(self)}",
            "warning"
        )

        add_log(
            f"🔥 WS BOOK UPDATE "
            f"bids={len(self.bids)} "
            f"asks={len(self.asks)}",
            "warning"
        )

        print(
            f"🔥 WS OB INSTANCE={id(self)}"
        )

        print(
            f"🔥 WS BOOK UPDATE "
            f"bids={len(self.bids)} "
            f"asks={len(self.asks)}"
        )

        # =========================
        # EMPTY CHECK
        # =========================

        print(
            f"TRACE LOCAL "
            f"bids={len(self.bids)} "
            f"asks={len(self.asks)}"
        )

        if (
            not self.bids
            or
            not self.asks
        ):

            print(
                "⚠️ EMPTY LOCAL BOOK"
            )

            print(
                "❌ RETURN EMPTY LOCAL BOOK "
                f"bids={len(self.bids)} "
                f"asks={len(self.asks)}"
            )

            return

        # =========================
        # BEST PRICE
        # =========================

        self.best_bid = max(
            self.bids.keys()
        )

        print(
            f"TRACE BEST BID="
            f"{self.best_bid}"
        )

        self.best_ask = min(
            self.asks.keys()
        )

        print(
            f"TRACE BEST ASK="
            f"{self.best_ask}"
        )

        # =========================
        # CROSSED BOOK PROTECTION
        # =========================

        print(
            f"TRACE CROSS CHECK "
            f"bid={self.best_bid} "
            f"ask={self.best_ask}"
        )

        if (
            self.best_bid
            >=
            self.best_ask
        ):

            print(
                f"❌ CROSSED BOOK "
                f"BID={self.best_bid} "
                f"ASK={self.best_ask}"
            )

            print(
                "❌ RETURN CROSSED BOOK "
                f"bid={self.best_bid} "
                f"ask={self.best_ask}"
            )

            return

        # =========================
        # PRICE / SPREAD
        # =========================

        self.current_price = (
            self.best_bid
            + self.best_ask
        ) / 2

        print(
            f"TRACE CURRENT PRICE="
            f"{self.current_price}"
        )

        self.spread = (
            self.best_ask
            - self.best_bid
        )

        print("✅ UPDATE SUCCESS")

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

        # =========================
        # DEBUG
        # =========================

        print(
            f"📊 TOP BID="
            f"{self.best_bid} "
            f"ASK={self.best_ask}"
        )

        print(
            f"💰 CURRENT PRICE="
            f"{self.current_price}"
        )

        print(
            f"💰 SPREAD="
            f"{self.spread}"
        )

        print(
            f"📊 BID VOLUME="
            f"{self.bid_volume}"
        )

        print(
            f"📊 ASK VOLUME="
            f"{self.ask_volume}"
        )

        print(
            f"📊 IMBALANCE="
            f"{self.imbalance}"
        )

        # =========================
        # CALLBACK
        # =========================

        if self.callback:

            print(
                "🔥 CALLBACK EXECUTE"
            )

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

        add_log(
            f"📚 OB INSTANCE={id(self)}",
            "warning"
        )

        add_log(
            f"📚 BOOK SIZES "
            f"bids={len(self.bids)} "
            f"asks={len(self.asks)}",
            "warning"
        )

        print(
            f"📚 OB INSTANCE={id(self)}"
        )

        print(
            f"📚 BOOK SIZES "
            f"bids={len(self.bids)} "
            f"asks={len(self.asks)}"
        )

        if (
            not self.bids
            or
            not self.asks
        ):

            print(
                "⚠️ EMPTY BOOK IN get_top_n_volume"
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

            print(
                f"📚 TOPN INPUT "
                f"bids={top_bid_prices[:3]} "
                f"asks={top_ask_prices[:3]}"
            )

            bid_vol = sum(
                self.bids[p]
                for p in top_bid_prices
            )

            ask_vol = sum(
                self.asks[p]
                for p in top_ask_prices
            )

            print(
                f"📚 TOPN RESULT "
                f"bid_vol={bid_vol} "
                f"ask_vol={ask_vol}"
            )

            return bid_vol, ask_vol

        except Exception as e:

            print(
                "⚠️ OrderBook volume error:",
                e
            )

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
