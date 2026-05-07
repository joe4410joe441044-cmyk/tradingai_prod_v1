# -*- coding: utf-8 -*-

from backend.utils.log_buffer import add_log


class OrderFlowDepthStrategy:

    def __init__(self, orderbook_manager):

        self.ob = orderbook_manager

        # =========================
        # SIGNAL HISTORY
        # =========================

        self.history = []

        # 3 → 2 に変更
        self.max_history = 2

    # =========================
    # ORDERBOOK EVENT
    # =========================

    def on_orderbook(self):

        print(
            "📊 STRATEGY on_orderbook CALLED"
        )

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
        # IMBALANCE
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
        # SIGNAL CONDITIONS
        # =========================

        # 0.2 → 0.05 に緩和

        if imbalance > 0.05:

            signal = "BUY"

        elif imbalance < -0.05:

            signal = "SELL"

        else:

            signal = "NONE"

        print(
            f"🧠 SIGNAL CANDIDATE: "
            f"{signal}"
        )

        # =========================
        # HISTORY
        # =========================

        self.history.append(signal)

        if len(self.history) > self.max_history:

            self.history.pop(0)

        print(
            f"📚 HISTORY: "
            f"{self.history}"
        )

        # =========================
        # WAIT HISTORY
        # =========================

        if len(self.history) < self.max_history:

            return None

        # =========================
        # BUY SIGNAL
        # =========================

        if all(
            h == "BUY"
            for h in self.history
        ):

            add_log(
                "✅ BUY CONFIRMED"
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
        # SELL SIGNAL
        # =========================

        if all(
            h == "SELL"
            for h in self.history
        ):

            add_log(
                "✅ SELL CONFIRMED"
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