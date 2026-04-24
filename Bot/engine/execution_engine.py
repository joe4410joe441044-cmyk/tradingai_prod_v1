# -*- coding: utf-8 -*-
import logging
import time
import threading
from typing import Dict, Any

from Bot.utils.safety import safe_run
from Bot.control.duplicate_guard import GlobalSignalRegistry, ExecutionGuard
from backend.services.ai_logger import AILogger

from backend.binance_client import BinanceClient
from backend.risk_manager import RiskManager


# =====================================================
# STATE MANAGER
# =====================================================
class StateManager:
    def __init__(self):
        self.positions: Dict[str, dict] = {}

    def get_open_positions(self):
        return list(self.positions.values())

    def set_position(self, pid: str, data: dict):
        self.positions[pid] = data

    def remove_position(self, pid: str):
        if pid in self.positions:
            del self.positions[pid]

    def update_price(self, pid: str, price: float):
        if pid in self.positions:
            self.positions[pid]["current_price"] = price


# =====================================================
# EXECUTION ENGINE
# =====================================================
class ExecutionEngine:

    def __init__(
        self,
        live=False,
        logger=None,
        notifier=None,
        trade_core=None,
        state_manager=None,
        binance_client: BinanceClient = None
    ):

        self.live = live
        self.logger = logger or logging.getLogger(__name__)
        self.notifier = notifier

        self.trade_core = trade_core

        self.state_manager = state_manager or StateManager()
        self.guard = ExecutionGuard(self.state_manager)

        self.ai_logger = AILogger()
        self.binance = binance_client

        self.risk = RiskManager(logger=self.logger)

        self.monitor = None

        self.balance = 0.0
        self.pnl = 0.0

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

        self._emit_ai_event("BOOT", {
            "symbol": "SYSTEM",
            "side": "INIT",
            "reason": "engine startup",
            "confidence": 1.0
        })

        self.start_auto_recovery()

    # =====================================================
    # AI EVENT
    # =====================================================
    def _emit_ai_event(self, stage: str, data: dict):
        payload = {
            "stage": stage,
            "symbol": data.get("symbol"),
            "action": data.get("side") or data.get("action"),
            "reason": data.get("reason", ""),
            "confidence": data.get("confidence", 0.0)
        }

        print("🔥 AI_EVENT:", payload)

        if self.monitor:
            self.monitor.log_event("AI_EVENT", payload)

    # =====================================================
    # MONITOR CONNECT
    # =====================================================
    def set_monitor(self, monitor):
        self.monitor = monitor

        if self.monitor:
            self.monitor.update_status("execution_engine", True)
            self.monitor.log_event("EXECUTION_ENGINE_CONNECTED", {})

    def _log_event(self, event: str, data: dict):
        if self.monitor:
            self.monitor.log_event(event, data)

    def _log_error(self, error: Exception, context: dict = None):
        if self.monitor:
            self.monitor.log_error("execution_engine", str(error), context or {})

    # =====================================================
    # 🔥 DASHBOARD UPDATE（追加）
    # =====================================================
    def _update_dashboard(self):
        if not self.monitor:
            return

        try:
            positions = self.state_manager.get_open_positions()

            self.monitor.update_dashboard(
                balance=self.balance,
                pnl=self.pnl,
                positions=positions
            )
        except Exception as e:
            self._log_error(e, {"stage": "dashboard_update"})

    # =====================================================
    # AUTO RECOVERY
    # =====================================================
    def start_auto_recovery(self):

        def loop():
            while True:
                try:
                    self._emit_ai_event("HEARTBEAT", {
                        "symbol": "SYSTEM",
                        "side": "PING",
                        "reason": "alive",
                        "confidence": 1.0
                    })

                    self._health_check_and_recover()

                    # 🔥 UI更新（ここが重要）
                    self._update_dashboard()

                except Exception as e:
                    self._log_error(e, {"loop": "auto_recovery"})

                time.sleep(3)

        threading.Thread(target=loop, daemon=True).start()

    def _health_check_and_recover(self):

        if self.monitor:
            self.monitor.update_status("execution_engine", True)

        if self.live and self.binance:
            try:
                self.binance.ping()
            except Exception:
                self._log_event("BINANCE_DISCONNECTED", {})
                self._reconnect_binance()

    def _reconnect_binance(self):
        try:
            self.binance.reconnect()
            self._log_event("BINANCE_RECONNECTED", {})
        except Exception as e:
            self._log_error(e, {"action": "reconnect_failed"})

    # =====================================================
    # ORDER ENTRY
    # =====================================================
    @safe_run
    def execute_order(self, signal: Dict[str, Any]):

        try:
            symbol = signal["symbol"]
            side = signal["side"].upper()

            self._emit_ai_event("AI_DECISION", signal)

            if not self.risk.can_enter(signal):
                return

            position_id = f"{symbol}_{time.time()}"

            position = {
                "position_id": position_id,
                "symbol": symbol,
                "side": side,
                "entry_price": signal.get("price", 0),
                "qty": signal.get("qty", 0.001),
                "status": "OPEN",
                "opened_at": time.time()
            }

            self.state_manager.set_position(position_id, position)

            self.risk.open_positions += 1
            self.risk.on_entry(signal)

            self._log_event("ORDER_EXECUTE", position)

            # 🔥 即時UI反映
            self._update_dashboard()

        except Exception as e:
            self._log_error(e, {"signal": signal})
            raise

    # =====================================================
    # CLOSE POSITION
    # =====================================================
    @safe_run
    def close_position(self, position_id: str, price: float, reason="manual"):

        pos = self.state_manager.positions.get(position_id)
        if not pos:
            return

        pnl = (price - pos["entry_price"]) * pos["qty"]

        self.pnl += pnl

        closed = dict(pos)
        closed.update({
            "status": "CLOSED",
            "close_price": price,
            "closed_at": time.time(),
            "close_reason": reason,
            "pnl": pnl
        })

        self.state_manager.remove_position(position_id)

        self.risk.open_positions = max(0, self.risk.open_positions - 1)
        self.risk.on_exit(pnl)

        self._emit_ai_event("POSITION_CLOSE", closed)

        self._log_event("ORDER_CLOSE", closed)

        # 🔥 即時UI反映
        self._update_dashboard()