# -*- coding: utf-8 -*-
import logging
import time

from Bot.utils.safety import safe_run
from Bot.control.duplicate_guard import GlobalSignalRegistry, ExecutionGuard
from backend.services.ai_logger import AILogger


# =========================
# SIMPLE STATE MANAGER
# =========================
class StateManager:
    def __init__(self):
        self.positions = {}

    def get_open_positions(self):
        return list(self.positions.values())

    def set_position(self, pid, data):
        self.positions[pid] = data

    def remove_position(self, pid):
        if pid in self.positions:
            del self.positions[pid]


# =====================================================
# EXECUTION ENGINE
# =====================================================
class ExecutionEngine:

    def __init__(self, live=False, logger=None, notifier=None, trade_core=None, state_manager=None):
        self.live = live
        self.logger = logger or logging.getLogger(__name__)
        self.notifier = notifier

        self.trade_core = trade_core

        # ★必ず存在させる（重要）
        self.state_manager = state_manager or StateManager()

        # Guard（state_manager必須）
        self.guard = ExecutionGuard(self.state_manager)

        self.ai_logger = AILogger()

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

    # =================================================
    # ORDER EXECUTION
    # =================================================
    @safe_run
    def execute_order(self, signal):

        symbol = signal["symbol"]
        direction = signal["side"]

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

        if not self.guard.can_execute(symbol, direction):
            self.logger.info("[GUARD] Execution blocked")
            return

        if not self.guard.acquire():
            self.logger.info("[GUARD] Execution lock failed")
            return

        try:
            # AI LOG
            self.ai_logger.log({
                "timestamp": time.time(),
                "symbol": symbol,
                "ai_score": signal.get("ai_score", 0.0),
                "risk_score": signal.get("risk_score", 0.0),
                "entry_allowed": True,
                "position_id": signal.get("position_id", "unknown"),
                "price": signal["price"],
                "reason": "execution"
            })

            self.send_signal(signal)

        finally:
            self.guard.release()

    # =================================================
    # SEND SIGNAL
    # =================================================
    @safe_run
    def send_signal(self, signal):

        print(f"[EXECUTION] ORDER: {signal['side']} @ {signal['price']}")
        self.logger.info(f"[EXECUTION] Processing signal: {signal}")

        if self.trade_core:
            pid = signal.get("position_id", f"pos_{time.time()}")

            position = {
                "position_id": pid,
                "symbol": signal["symbol"],
                "side": signal["side"],
                "entry_price": signal["price"],
                "sl": signal.get("sl"),
                "tp": signal.get("tp"),
                "status": "OPEN"
            }

            # ★ state_manager同期（重要）
            self.state_manager.set_position(pid, position)

            self.trade_core.on_position_opened(position)

    # =================================================
    # CLOSE ORDER ★追加（これが今回の修正ポイント）
    # =================================================
    @safe_run
    def close_order(self, order):

        pid = order.get("position_id")
        price = order.get("price")

        print(f"[CLOSE ORDER] {pid} @ {price}")

        # state削除
        self.state_manager.remove_position(pid)

        # TradeCoreへ通知（あれば）
        if self.trade_core and hasattr(self.trade_core, "on_position_closed"):
            self.trade_core.on_position_closed(order)