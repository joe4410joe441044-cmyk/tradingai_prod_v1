# -*- coding: utf-8 -*-

from backend.utils.log_buffer import add_log


class OrderFlowDepthStrategy:

    def __init__(self, orderbook_manager):

        self.ob = orderbook_manager

        # シグナル履歴
        self.history = []

        self.max_history = 3

    # =========================
    # ORDERBOOK EVENT
    # =========================

    def on_orderbook(self):

        print("📊 STRATEGY on_orderbook CALLED")

        bid_vol, ask_vol = (
            self.ob.get_top_n_volume(5)
        )

        total = bid_vol + ask_vol

        # =========================
        # DEBUG
        # =========================

        print(
            f"📊 STRATEGY DATA "
            f"bid={bid_vol:.2f} "
            f"ask={ask_vol:.2f}"
        )

        # =========================
        # データなし防止
        # =========================

        if total == 0:

            print("⚠️ TOTAL = 0")

            return None

        # =========================
        # 🔥 imbalance計算
        # =========================

        imbalance = (
            (bid_vol - ask_vol)
            / total
        )

        print(
            f"📊 IMBALANCE="
            f"{imbalance:.4f}"
        )

        add_log(
            f"📊 OB: "
            f"bid={bid_vol:.2f} "
            f"ask={ask_vol:.2f} "
            f"imbalance={imbalance:.2f}"
        )

        # =========================
        # 🔥 シグナル条件
        # =========================

        if imbalance > 0.2:

            signal = "BUY"

        elif imbalance < -0.2:

            signal = "SELL"

        else:

            signal = "NONE"

        print(
            f"🧠 SIGNAL CANDIDATE: "
            f"{signal}"
        )

        # =========================
        # 履歴保存
        # =========================

        self.history.append(signal)

        print(
            f"📚 HISTORY: "
            f"{self.history}"
        )

        if len(self.history) > self.max_history:

            self.history.pop(0)

        # =========================
        # 🔥 連続一致フィルタ
        # =========================

        if len(self.history) < self.max_history:

            return None

        # =========================
        # BUY
        # =========================

        if all(
            h == "BUY"
            for h in self.history
        ):

            add_log(
                "✅ BUY 3連続"
            )

            signal_data = {
                "side": "BUY"
            }

            add_log(
                f"🟡 SIGNAL: "
                f"{signal_data}"
            )

            print(
                f"🚀 FINAL SIGNAL: "
                f"{signal_data}"
            )

            self.history.clear()

            return signal_data

        # =========================
        # SELL
        # =========================

        if all(
            h == "SELL"
            for h in self.history
        ):

            add_log(
                "✅ SELL 3連続"
            )

            signal_data = {
                "side": "SELL"
            }

            add_log(
                f"🟡 SIGNAL: "
                f"{signal_data}"
            )

            print(
                f"🚀 FINAL SIGNAL: "
                f"{signal_data}"
            )

            self.history.clear()

            return signal_data

        return None