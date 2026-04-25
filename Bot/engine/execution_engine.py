# -*- coding: utf-8 -*-
import logging
import time
import threading
from typing import Dict, Any

from Bot.utils.safety import safe_run
from Bot.control.duplicate_guard import ExecutionGuard
from backend.services.ai_logger import AILogger

from backend.binance_client import BinanceClient
from backend.risk_manager import RiskManager


# =====================================================
# STATE MANAGER
# =====================================================
class StateManager:
    def __init__(self):
        self.positions: Dict[str, dict] = {}
        self.lock = threading.Lock()

    def get_open_positions(self):
        with self.lock:
            return list(self.positions.values())

    def set_position(self, pid: str, data: dict):
        with self.lock:
            self.positions[pid] = data

    def remove_position(self, pid: str):
        with self.lock:
            if pid in self.positions:
                del self.positions[pid]

    def update_all_prices(self, price: float):
        with self.lock:
            for pos in self.positions.values():
                pos["current_price"] = price


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
        binance_client: BinanceClient = None,
        monitor=None
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

        self.monitor = monitor

        self.balance = 0.0
        self.pnl = 0.0

        self.active = False
        self._thread = None

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

        self._emit_ai_event("BOOT", {
            "symbol": "SYSTEM",
            "side": "INIT",
            "reason": "engine startup",
            "confidence": 1.0
        })

    # =====================================================
    # AI EVENT
    # =====================================================
    def _emit_ai_event(self, stage: str, data: dict):
        try:
            payload = {
                "stage": stage,
                "symbol": data.get("symbol"),
                "action": data.get("side") or data.get("action"),
                "reason": data.get("reason", ""),
                "confidence": data.get("confidence", 0.0)
            }

            if stage != "HEARTBEAT":
                print("AI_EVENT:", payload)

            if self.monitor:
                self.monitor.log_event("AI_EVENT", payload)

        except Exception as e:
            if self.monitor:
                self.monitor.log_error("AI_EVENT", e)

    # =====================================================
    # DASHBOARD
    # =====================================================
    def _update_dashboard(self):
        if not self.monitor:
            return

        try:
            self.monitor.update_dashboard(
                balance=self.balance,
                pnl=self.pnl,
                positions=self.state_manager.get_open_positions()
            )
        except Exception as e:
            self.monitor.log_error("execution_engine", e, {"stage": "dashboard"})

    # =====================================================
    # PRICE UPDATE
    # =====================================================
    def on_price(self, price: float):

        try:
            self.state_manager.update_all_prices(price)

            if self.monitor:
                self.monitor.update_dashboard(price=price)

            total_pnl = 0.0

            for pos in self.state_manager.get_open_positions():
                entry = pos.get("entry_price", 0)
                qty = pos.get("qty", 0)
                current = pos.get("current_price", price)

                if pos.get("side") == "BUY":
                    total_pnl += (current - entry) * qty
                else:
                    total_pnl += (entry - current) * qty

            self.pnl = total_pnl

        except Exception as e:
            if self.monitor:
                self.monitor.log_error("PNL_CALC", e)

        self._update_dashboard()

    # =====================================================
    # START / STOP
    # =====================================================
    def start(self):

        if self.active:
            return

        self.active = True

        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        if self.monitor:
            self.monitor.update_status("execution_engine", True)

    def stop(self):
        self.active = False

        if self.monitor:
            self.monitor.update_status("execution_engine", False)

    # =====================================================
    # LOOP
    # =====================================================
    def _loop(self):

        while self.active:
            try:
                self._emit_ai_event("HEARTBEAT", {
                    "symbol": "SYSTEM",
                    "side": "PING",
                    "reason": "alive",
                    "confidence": 1.0
                })

                self._health_check_and_recover()

            except Exception as e:
                if self.monitor:
                    self.monitor.log_error("ENGINE_LOOP", e)

            time.sleep(3)

    # =====================================================
    # HEALTH
    # =====================================================
    def _health_check_and_recover(self):

        if self.live and self.binance:
            try:
                self.binance.ping()
            except Exception:
                if self.monitor:
                    self.monitor.log_event("BINANCE_DISCONNECTED", {})
                self._reconnect_binance()

    def _reconnect_binance(self):
        try:
            self.binance.reconnect()
            if self.monitor:
                self.monitor.log_event("BINANCE_RECONNECTED", {})
        except Exception as e:
            if self.monitor:
                self.monitor.log_error("BINANCE_RECONNECT", e)

    # =====================================================
    # ORDER
    # =====================================================
    @safe_run
    def execute_order(self, signal: Dict[str, Any]):

        if not self.active:
            return

        if signal.get("confidence", 0) < 0.5:
            return

        if not self.risk.can_enter(signal):
            if self.monitor:
                self.monitor.metrics["risk_blocks"] += 1
            return

        symbol = signal["symbol"]
        side = signal["side"].upper()

        # 🔥 重複防止
        if not self.guard.can_execute(symbol, side):
            return

        self._emit_ai_event("AI_DECISION", signal)

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
        self.risk.on_entry(signal)

        if self.monitor:
            self.monitor.metrics["orders"] += 1
            self.monitor.log_event("ORDER_EXECUTE", position)

        self._update_dashboard()

    # =====================================================
    # CLOSE
    # =====================================================
    @safe_run
    def close_position(self, position_id: str, price: float, reason="manual"):

        pos = self.state_manager.positions.get(position_id)
        if not pos:
            return

        pnl = (price - pos["entry_price"]) * pos["qty"]
        if pos["side"] == "SELL":
            pnl = -pnl

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
        self.risk.on_exit(pnl)

        self._emit_ai_event("POSITION_CLOSE", closed)

        if self.monitor:
            self.monitor.log_event("ORDER_CLOSE", closed)

        self._update_dashboard()

    # =====================================================
    # GETTERS
    # =====================================================
    def get_positions(self):
        return self.state_manager.get_open_positions()

    def get_pnl(self):
        return self.pnl