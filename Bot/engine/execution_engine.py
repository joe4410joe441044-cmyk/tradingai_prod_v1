# -*- coding: utf-8 -*-
import logging
import time
import threading
from typing import Dict, Any

from Bot.control.duplicate_guard import ExecutionGuard
from backend.risk_manager import RiskManager


class StateManager:
    def __init__(self):
        self.positions: Dict[str, dict] = {}
        self.lock = threading.Lock()
        self.realized_pnl = 0.0

    def get_positions(self):
        with self.lock:
            return dict(self.positions)

    def set_position(self, pid: str, data: dict):
        with self.lock:
            self.positions[pid] = data

    def remove_position(self, pid: str):
        with self.lock:
            if pid in self.positions:
                del self.positions[pid]

    def calculate_position_pnl(self, pos, current_price):
        if pos["side"] == "BUY":
            return (current_price - pos["entry_price"]) * pos["qty"]
        else:
            return (pos["entry_price"] - current_price) * pos["qty"]


class ExecutionEngine:

    def __init__(
        self,
        live=False,
        logger=None,
        notifier=None,
        trade_core=None,
        state_manager=None,
        trade_client=None,
        monitor=None
    ):
        self.live = live
        self.logger = logger or logging.getLogger(__name__)
        self.state_manager = state_manager or StateManager()
        self.guard = ExecutionGuard(self.state_manager)
        self.risk = RiskManager(logger=self.logger)

        self.monitor = monitor
        self.active = False

        self.last_price = 0.0
        self.pnl = 0.0

    def start(self):
        if self.active:
            return {"status": "already_running"}

        self.active = True
        print("🔥 ENGINE START")
        return {"status": "started"}

    def stop(self):
        self.active = False

    # =========================
    # PRICE
    # =========================
    def on_price(self, price: float):
        if not self.active:
            return

        self.last_price = price

        positions = self.state_manager.get_positions()

        self.pnl = sum(
            self.state_manager.calculate_position_pnl(p, price)
            for p in positions.values()
        )

        # 🔥 決済
        self.check_exit(price)

        # 🔥 UI更新
        if self.monitor:
            self.monitor.update_dashboard(
                price=price,
                pnl=self.pnl,
                realized_pnl=self.state_manager.realized_pnl,
                positions=list(self.state_manager.get_positions().values())
            )

    # =========================
    # EXIT（修正）
    # =========================
    def check_exit(self, price):

        now = time.time()

        for pos in list(self.state_manager.get_positions().values()):

            if pos.get("status") != "OPEN":
                continue

            # 🔥 エントリー直後は無視（重要）
            if now - pos.get("created_at", now) < 2:
                continue

            entry = pos["entry_price"]

            tp = entry * 1.001
            sl = entry * 0.999

            if pos["side"] == "BUY":
                if price >= tp or price <= sl:
                    self._close_position(pos, price)
            else:
                if price <= tp or price >= sl:
                    self._close_position(pos, price)

    # =========================
    # CLOSE
    # =========================
    def _close_position(self, pos, price):

        pnl = self.state_manager.calculate_position_pnl(pos, price)
        self.state_manager.realized_pnl += pnl

        pos["status"] = "CLOSED"
        pos["closed"] = True

        self.state_manager.remove_position(pos["position_id"])

        if self.monitor:
            self.monitor.update_dashboard(
                realized_pnl=self.state_manager.realized_pnl,
                positions=list(self.state_manager.get_positions().values())
            )
            self.monitor.log_event("CLOSE", {"pnl": pnl})

        print("💰 CLOSED:", pnl)

    # =========================
    # CREATE（修正）
    # =========================
    def _create_position(self):

        price = self.last_price or 77777

        pid = f"BTCUSDT_{time.time()}"

        pos = {
            "position_id": pid,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "entry_price": price,
            "qty": 0.001,
            "status": "OPEN",
            "created_at": time.time()  # 🔥 追加
        }

        self.state_manager.set_position(pid, pos)
        return pos

    # =========================
    # ORDER
    # =========================
    def execute_order(self, signal: Dict[str, Any]):
        if not self.active:
            return None

        pos = self._create_position()

        if self.monitor:
            self.monitor.update_dashboard(
                positions=list(self.state_manager.get_positions().values())
            )
            self.monitor.log_event("ENTRY", pos)

        return pos

    def get_result(self):
        return {
            "realized_pnl": self.state_manager.realized_pnl,
            "positions": self.state_manager.get_positions()
        }