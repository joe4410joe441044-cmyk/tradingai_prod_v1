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
# EXECUTION ENGINE (FULL PRODUCTION + RECOVERY + MONITOR)
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

        # =========================
        # MONITOR
        # =========================
        self.monitor = None

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

        # =========================
        # AUTO RECOVERY START
        # =========================
        self.start_auto_recovery()

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
    # AUTO RECOVERY LOOP
    # =====================================================
    def start_auto_recovery(self):

        def loop():
            while True:
                try:
                    self._health_check_and_recover()
                except Exception as e:
                    self._log_error(e, {"loop": "auto_recovery"})
                time.sleep(5)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    # =====================================================
    # HEALTH CHECK + RECOVERY
    # =====================================================
    def _health_check_and_recover(self):

        # monitor alive
        if self.monitor:
            self.monitor.update_status("execution_engine", True)

        # =========================
        # BINANCE RECOVERY
        # =========================
        if self.live and self.binance:

            try:
                self.binance.ping()

            except Exception:

                self._log_event("BINANCE_DISCONNECTED", {})

                self._reconnect_binance()

        # =========================
        # SAFETY CHECK
        # =========================
        if self.risk.open_positions > self.risk.max_positions * 2:

            self.risk.open_positions = self.risk.max_positions

            self._log_event("RISK_AUTO_RESET", {})

    # =====================================================
    # RECONNECT BINANCE
    # =====================================================
    def _reconnect_binance(self):

        try:
            self.binance.reconnect()

            self._log_event("BINANCE_RECONNECTED", {})

            self._restore_positions()

        except Exception as e:
            self._log_error(e, {"action": "reconnect_failed"})

    # =====================================================
    # RESTORE POSITIONS
    # =====================================================
    def _restore_positions(self):

        try:
            positions = self.binance.get_open_positions()

            for p in positions:
                self.state_manager.set_position(p["position_id"], p)

            self._log_event("POSITIONS_RESTORED", {
                "count": len(positions)
            })

        except Exception as e:
            self._log_error(e, {"action": "restore_failed"})

    # =====================================================
    # ORDER ENTRY
    # =====================================================
    @safe_run
    def execute_order(self, signal: Dict[str, Any]):

        try:

            if self.risk.killed:
                self._log_event("KILL_SWITCH_BLOCK", {})
                return

            symbol = signal["symbol"]
            side = signal["side"].upper()

            price = float(signal.get("price", 0))
            qty = float(signal.get("qty", 0.001))

            if qty <= 0:
                raise ValueError("qty must be > 0")

            if not self.risk.can_enter(signal):
                self._log_event("RISK_BLOCK", signal)
                return

            fingerprint = GlobalSignalRegistry.generate_fingerprint(
                symbol=symbol,
                strategy=signal.get("strategy", "default"),
                timeframe=signal.get("timeframe", "1m"),
                direction=side,
                price_bucket=round(price, 2)
            )

            if GlobalSignalRegistry.is_duplicate(fingerprint):
                self._log_event("DUPLICATE_BLOCK", {})
                return

            if not self.guard.can_execute(symbol, side):
                return

            if not self.guard.acquire():
                return

            position_id = signal.get("position_id") or f"{symbol}_{time.time()}"

            order_response = None

            if self.live and self.binance:
                order_response = self.binance.execute_order({
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "order_type": signal.get("order_type", "MARKET"),
                    "price": signal.get("price")
                })

            position = {
                "position_id": position_id,
                "symbol": symbol,
                "side": side,
                "entry_price": price,
                "current_price": price,
                "sl": signal.get("sl"),
                "tp": signal.get("tp"),
                "qty": qty,
                "status": "OPEN",
                "pnl": 0.0,
                "opened_at": time.time(),
                "order_response": order_response
            }

            self.state_manager.set_position(position_id, position)

            self.risk.open_positions += 1
            self.risk.on_entry(signal)

            self._log_event("ORDER_EXECUTE", position)

            self.ai_logger.log({
                "timestamp": time.time(),
                "symbol": symbol,
                "price": price,
                "position_id": position_id,
                "event": "OPEN"
            })

            if self.trade_core:
                self.trade_core.on_position_opened(position)

        except Exception as e:
            self._log_error(e, {"signal": signal})
            raise

        finally:
            self.guard.release()

    # =====================================================
    # PRICE UPDATE
    # =====================================================
    @safe_run
    def on_price_update(self, symbol: str, price: float):

        self.risk.update_equity(price)

        for p in self.state_manager.get_open_positions():

            if p["symbol"] != symbol:
                continue

            pid = p["position_id"]

            self.state_manager.update_price(pid, price)

            entry = p["entry_price"]
            qty = p["qty"]

            pnl = (price - entry) * qty if p["side"] == "BUY" else (entry - price) * qty
            p["pnl"] = pnl

            if p.get("sl") and price <= p["sl"]:
                self.close_position(pid, price, "SL")

            if p.get("tp") and price >= p["tp"]:
                self.close_position(pid, price, "TP")

    # =====================================================
    # CLOSE POSITION
    # =====================================================
    @safe_run
    def close_position(self, position_id: str, price: float, reason="manual"):

        pos = self.state_manager.positions.get(position_id)
        if not pos:
            return

        pnl = (price - pos["entry_price"]) * pos["qty"] if pos["side"] == "BUY" else (pos["entry_price"] - price) * pos["qty"]

        if self.live and self.binance:
            self.binance.execute_order({
                "symbol": pos["symbol"],
                "side": "SELL" if pos["side"] == "BUY" else "BUY",
                "qty": pos["qty"],
                "order_type": "MARKET"
            })

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

        self._log_event("ORDER_CLOSE", closed)

        if self.trade_core:
            self.trade_core.on_position_closed(closed)

    # =====================================================
    # API
    # =====================================================
    def get_positions(self):
        return self.state_manager.get_open_positions()

    def get_balance(self):
        if self.live and self.binance:
            return self.binance.get_balance()
        return 0

    def get_pnl(self):
        return sum(p.get("pnl", 0) for p in self.state_manager.get_open_positions())