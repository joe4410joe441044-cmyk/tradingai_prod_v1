# -*- coding: utf-8 -*-
import logging

# ★安全ラッパー
from Bot.utils.safety import safe_run


class ExecutionEngine:
    """
    ExecutionEngine
    ----------------
    TradeCore からの Signal を受け取り処理する。
    live=False の場合はログのみ（擬似約定）。
    notifier があれば Telegram へ通知。
    """

    def __init__(self, live=False, logger=None, notifier=None, trade_core=None):
        self.live = live
        self.logger = logger or logging.getLogger(__name__)
        self.notifier = notifier

        # ★追加：TradeCore接続
        self.trade_core = trade_core

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

    # --------------------------
    # Signal送信（内部処理）
    # --------------------------
    @safe_run
    def send_signal(self, signal):
        """
        Signal 例:
        {
            'side': 'BUY',
            'symbol': 'BTCUSDT',
            'qty': 0.001,
            'price': xxx,
            'sl': xxx,
            'tp': xxx
        }
        """

        print(f"[EXECUTION] ORDER: {signal['side']} @ {signal['price']}")

        self.logger.info(f"[EXECUTION] Processing signal: {signal}")

        if self.live:
            self.logger.info(f"[LIVE] Sending order: {signal}")
        else:
            self.logger.info(f"[DRY_RUN] Signal received: {signal}")

        # --------------------------
        # ★ここが最重要：擬似約定 → TradeCoreへ返す
        # --------------------------
        if self.trade_core:
            position = {
                "symbol": signal["symbol"],
                "side": signal["side"],
                "entry_price": signal["price"],
                "sl": signal.get("sl"),
                "tp": signal.get("tp"),
                "status": "OPEN"
            }

            self.trade_core.on_position_opened(position)

        # Telegram通知
        if self.notifier:
            try:
                self.notifier.send(f"Signal executed: {signal}")
            except Exception as e:
                self.logger.error(f"Failed to send Telegram notification: {e}")

    # --------------------------
    # 発注前準備（任意）
    # --------------------------
    @safe_run
    def prepare_order(self, position):
        signal = {
            "symbol": position["symbol"],
            "side": position["side"],
            "qty": position.get("qty", 0.001),
            "price": position["entry_price"]
        }

        if self.live:
            self.logger.info(f"[LIVE] Preparing order: {signal}")
        else:
            self.logger.info(f"[DRY_RUN] Preparing order: {signal}")

    # --------------------------
    # 決済準備（任意）
    # --------------------------
    @safe_run
    def prepare_close_order(self, position):
        signal = {
            "symbol": position["symbol"],
            "side": "SELL" if position["side"] == "BUY" else "BUY",
            "qty": position.get("qty", 0.001),
            "price": position["entry_price"]
        }

        if self.live:
            self.logger.info(f"[LIVE] Preparing close order: {signal}")
        else:
            self.logger.info(f"[DRY_RUN] Preparing close order: {signal}")

    # --------------------------
    # ★統一注文入口（TradeCore → ここ）
    # --------------------------
    @safe_run
    def execute_order(self, signal):
        """
        TradeCoreから呼ばれる唯一の入口
        """
        self.send_signal(signal)