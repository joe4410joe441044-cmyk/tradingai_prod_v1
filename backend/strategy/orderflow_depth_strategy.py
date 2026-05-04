# -*- coding: utf-8 -*-

class OrderFlowDepthStrategy:

    def __init__(self, orderbook_manager):
        self.ob = orderbook_manager

        # シグナル履歴
        self.history = []
        self.max_history = 3

    def on_orderbook(self):

        bid_vol, ask_vol = self.ob.get_top_n_volume(5)
        total = bid_vol + ask_vol

        # =========================
        # データなし防止
        # =========================
        if total == 0:
            return None

        # =========================
        # 🔥 imbalance計算
        # =========================
        imbalance = (bid_vol - ask_vol) / total

        print(f"📊 OB: bid={bid_vol:.2f} ask={ask_vol:.2f} imbalance={imbalance:.2f}")

        # =========================
        # 🔥 シグナル条件（現実調整）
        # =========================
        # ※元の0.6は強すぎるので緩和
        if imbalance > 0.2:
            signal = "BUY"
        elif imbalance < -0.2:
            signal = "SELL"
        else:
            signal = "NONE"

        # =========================
        # 履歴保存
        # =========================
        self.history.append(signal)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        # =========================
        # 🔥 連続一致フィルタ（最重要）
        # =========================
        if len(self.history) < self.max_history:
            return None

        if all(h == "BUY" for h in self.history):
            print("✅ BUY 3連続")
            self.history.clear()
            return {"side": "BUY"}

        if all(h == "SELL" for h in self.history):
            print("✅ SELL 3連続")
            self.history.clear()
            return {"side": "SELL"}

        return None