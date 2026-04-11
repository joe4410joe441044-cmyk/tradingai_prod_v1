# -*- coding: utf-8 -*-
import logging

# ★安全ラッパー
from Bot.utils.safety import safe_run

# ★Duplicate Guard
from Bot.control.duplicate_guard import GlobalSignalRegistry, ExecutionGuard


class ExecutionEngine:
    """
    ExecutionEngine
    ----------------
    TradeCore からの Signal を受け取り処理する。
    live=False の場合はログのみ（擬似約定）。
    notifier があれば Telegram へ通知。
    """

    def __init__(self, live=False, logger=None, notifier=None, trade_core=None, state_manager=None):
        self.live = live
        self.logger = logger or logging.getLogger(__name__)
        self.notifier = notifier

        # ★TradeCore接続
        self.trade_core = trade_core

        # ★Execution Guard（追加）
        self.guard = ExecutionGuard(state_manager)

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

    # --------------------------
    # Signal送信（内部処理）
    # --------------------------
    @safe_run
    def send_signal(self, signal):

        print(f"[EXECUTION] ORDER: {signal['side']} @ {signal['price']}")

        self.logger.info(f"[EXECUTION] Processing signal: {signal}")

        if self.live:
            self.logger.info(f"[LIVE] Sending order: {signal}")
        else:
            self.logger.info(f"[DRY_RUN] Signal received: {signal}")

        # --------------------------
        # ★擬似約定 → TradeCoreへ返す
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
    # ★統一注文入口（Guard統合済み）
    # --------------------------
    @safe_run
    def execute_order(self, signal):
        """
        TradeCoreから呼ばれる唯一の入口
        """

        symbol = signal["symbol"]
        direction = signal["side"]

        # =================================================
        # 🛡️ STEP1: Global Signal Guard（重複排除）
        # =================================================
        fingerprint = GlobalSignalRegistry.generate_fingerprint(
            symbol=symbol,
            strategy=signal.get("strategy", "default"),
            timeframe=signal.get("timeframe", "1m"),
            direction=direction,
            price_bucket=round(signal["price"], 2)
        )

        if GlobalSignalRegistry.is_duplicate(fingerprint):
            self.logger.info("[GUARD] Duplicate signal blocked")
            return

        # =================================================
        # 🛡️ STEP2: Execution Guard（ローカル制御）
        # =================================================
        if not self.guard.can_execute(symbol, direction):
            self.logger.info("[GUARD] Execution blocked (state or position)")
            return

        if not self.guard.acquire():
            self.logger.info("[GUARD] Execution lock failed")
            return

        try:
            # =================================================
            # 🚀 実行本体
            # =================================================
            self.send_signal(signal)

            # =================================================
            # 🧠 State同期（安全側）
            # =================================================
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

        finally:
            self.guard.release()