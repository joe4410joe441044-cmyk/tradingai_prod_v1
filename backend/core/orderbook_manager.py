# -*- coding: utf-8 -*-

class OrderBookManager:

    def __init__(self):

        self.bids = []

        self.asks = []

        self.current_price = 0.0

        self.best_bid = 0.0

        self.best_ask = 0.0

        self.spread = 0.0

        self.bid_volume = 0.0

        self.ask_volume = 0.0

        self.imbalance = 0.0

    def update(self, bids, asks):
        """
        WebSocketから受け取った板データを更新
        """

        print(
            f"📥 MANAGER UPDATE "
            f"bids={len(bids)} "
            f"asks={len(asks)}"
        )

        # =========================
        # 🔥 フィルタ①：0数量除外（最重要）
        # =========================

        self.bids = [
            b for b in bids
            if float(b[1]) > 0
        ]

        self.asks = [
            a for a in asks
            if float(a[1]) > 0
        ]

        print(
            f"✅ FILTERED "
            f"bids={len(self.bids)} "
            f"asks={len(self.asks)}"
        )

        # =========================
        # 🔥 フィルタ②：価格順ソート（安全対策）
        # =========================

        # bids: 高い順
        self.bids.sort(
            key=lambda x: float(x[0]),
            reverse=True
        )

        # asks: 安い順
        self.asks.sort(
            key=lambda x: float(x[0])
        )

        # =========================
        # DEBUG
        # =========================

        if self.bids and self.asks:

            self.best_bid = float(
                self.bids[0][0]
            )

            self.best_ask = float(
                self.asks[0][0]
            )

            self.current_price = (
                self.best_bid
                + self.best_ask
            ) / 2

            self.spread = (
                self.best_ask
                - self.best_bid
            )

            self.bid_volume = sum(
                float(b[1])
                for b in self.bids[:5]
            )

            self.ask_volume = sum(
                float(a[1])
                for a in self.asks[:5]
            )

            total_volume = (
                self.bid_volume
                + self.ask_volume
            )

            if total_volume > 0:

                self.imbalance = (
                    self.bid_volume
                    - self.ask_volume
                ) / total_volume

            else:

                self.imbalance = 0.0

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

    def get_top_n_volume(self, n=5):
        """
        上位n件の合計ボリュームを取得
        """

        if not self.bids or not self.asks:
            return 0.0, 0.0

        try:

            bid_vol = sum(
                float(b[1])
                for b in self.bids[:n]
            )

            ask_vol = sum(
                float(a[1])
                for a in self.asks[:n]
            )

            return bid_vol, ask_vol

        except Exception as e:

            print(
                "⚠️ OrderBook volume error:",
                e
            )

            return 0.0, 0.0

    def get_best_bid_ask(self):
        """
        最良価格（デバッグ・スプレッド確認用）
        """

        if not self.bids or not self.asks:
            return None, None

        best_bid = float(self.bids[0][0])

        best_ask = float(self.asks[0][0])

        return best_bid, best_ask

    def get_current_price(self):

        return self.current_price

    def get_spread(self):

        return self.spread

    def get_imbalance(self):

        return self.imbalance

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