# -*- coding: utf-8 -*-

from backend.utils.log_buffer import add_log, runtime_debug


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

        # =========================
        # STRATEGY UPDATE
        # =========================

        bid_vol, ask_vol = (
            self.ob.get_top_n_volume(5)
        )

        total = bid_vol + ask_vol

        # =========================
        # DEBUG
        # =========================

        # =========================
        # データなし防止
        # =========================

        if total == 0:

            runtime_debug("Order-flow strategy skipped: zero volume")

            return None

        # =========================
        # IMBALANCE
        # =========================

        imbalance = (
            (bid_vol - ask_vol)
            / total
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

        runtime_debug(
            "Order-flow strategy bid_volume=%.2f ask_volume=%.2f "
            "imbalance=%.4f candidate=%s",
            bid_vol,
            ask_vol,
            imbalance,
            signal,
        )

        # =========================
        # HISTORY
        # =========================

        self.history.append(signal)

        if len(self.history) > self.max_history:

            self.history.pop(0)

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

            signal_data = {
                "side": "BUY"
            }

            add_log(
                f"✅ BUY SIGNAL CONFIRMED: {signal_data}",
                "success"
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

            signal_data = {
                "side": "SELL"
            }

            add_log(
                f"✅ SELL SIGNAL CONFIRMED: {signal_data}",
                "success"
            )

            self.history.clear()

            return signal_data

        return None
