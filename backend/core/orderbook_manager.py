# -*- coding: utf-8 -*-

class OrderBookManager:

    def __init__(self):
        self.bids = []
        self.asks = []

    def update(self, bids, asks):
        """
        WebSocketから受け取った板データを更新
        """

        # =========================
        # 🔥 フィルタ①：0数量除外（最重要）
        # =========================
        self.bids = [b for b in bids if float(b[1]) > 0]
        self.asks = [a for a in asks if float(a[1]) > 0]

        # =========================
        # 🔥 フィルタ②：価格順ソート（安全対策）
        # =========================
        # bids: 高い順
        self.bids.sort(key=lambda x: float(x[0]), reverse=True)

        # asks: 安い順
        self.asks.sort(key=lambda x: float(x[0]))

    def get_top_n_volume(self, n=5):
        """
        上位n件の合計ボリュームを取得
        """

        if not self.bids or not self.asks:
            return 0.0, 0.0

        try:
            bid_vol = sum(float(b[1]) for b in self.bids[:n])
            ask_vol = sum(float(a[1]) for a in self.asks[:n])
            return bid_vol, ask_vol

        except Exception as e:
            print("⚠️ OrderBook volume error:", e)
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