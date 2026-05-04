# -*- coding: utf-8 -*-

from ws.orderbook_ws import OrderBookWS
from core.orderbook_manager import OrderBookManager
from strategy.orderflow_depth_strategy import OrderFlowDepthStrategy

import time

ob_manager = OrderBookManager()
strategy = OrderFlowDepthStrategy(ob_manager)


def on_update(bids, asks):
    # =========================
    # 🔥 ① WSデータ受信確認
    # =========================
    print("🔥 UPDATE来てる")

    # =========================
    # ② OrderBook更新
    # =========================
    ob_manager.update(bids, asks)

    # =========================
    # 🔥 ③ 板の中身確認（先頭だけ）
    # =========================
    if bids and asks:
        print(f"TOP BID: {bids[0]}  TOP ASK: {asks[0]}")

    # =========================
    # 🔥 ④ ボリューム確認
    # =========================
    bid_vol, ask_vol = ob_manager.get_top_n_volume(5)
    print(f"DEBUG VOL: bid={bid_vol:.2f} ask={ask_vol:.2f}")

    # =========================
    # ⑤ Strategy実行
    # =========================
    signal = strategy.on_orderbook()

    # =========================
    # 🔥 ⑥ シグナル確認
    # =========================
    if signal:
        print("🟡 SIGNAL:", signal)


# =========================
# WS起動
# =========================
ws = OrderBookWS("btcusdt", on_update)
ws.start()

# =========================
# メインループ
# =========================
while True:
    time.sleep(1)