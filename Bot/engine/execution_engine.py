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

    # 🔥 完全修正（統一）
    def calculate_position_pnl(self, pos, current_price):
        if pos["side"] == "LONG":
            return (current_price - pos["entry"]) * pos["size"]
        else:
            return (pos["entry"] - current_price) * pos["size"]


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

    # =========================
    # START / STOP
    # =========================
    def start(self):
        if self.active:
            return {"status": "already_running"}

        self.active = True
        print("🔥 ENGINE START")
        return {"status": "started"}

    def stop(self):
        self.active = False

    # =========================
    # PRICE（コア）
    # =========================
    def on_price(self, price: float):
        if not self.active:
            return

        self.last_price = price

        # ENTRY
        self.check_entry(price)

        # EXIT
        self.check_exit(price)

        # PnL計算
        positions = self.state_manager.get_positions()
        self.pnl = sum(
            self.state_manager.calculate_position_pnl(p, price)
            for p in positions.values()
        )

        # monitor（唯一ソース）
        if self.monitor:
            self.monitor.update_dashboard(
                price=price,
                pnl=self.pnl,
                realized_pnl=self.state_manager.realized_pnl,
                positions=len(positions)
            )

    # =========================
    # ENTRY
    # =========================
    def check_entry(self, price):
        positions = self.state_manager.get_positions()

        if len(positions) > 0:
            return

        self._create_position(price)

    # =========================
    # EXIT（完全統一）
    # =========================
    def check_exit(self, price):

        now = time.time()

        for pos in list(self.state_manager.get_positions().values()):

            if pos.get("status") != "OPEN":
                continue

            # 即クローズ防止
            if now - pos.get("created_at", now) < 2:
                continue

            entry = pos["entry"]
            tp = pos["tp"]
            sl = pos["sl"]

            if pos["side"] == "LONG":
                if price >= tp or price <= sl:
                    self._close_position(pos, price)
            else:
                if price <= tp or price >= sl:
                    self._close_position(pos, price)

    # =========================
    # CLOSE（完全統一）
    # =========================
    def _close_position(self, pos, price):

        pnl = (price - pos["entry"]) * pos["size"]
        self.state_manager.realized_pnl += pnl

        pos["status"] = "CLOSED"

        self.state_manager.remove_position(pos["position_id"])

        if self.monitor:
            self.monitor.log_event("CLOSE", {"pnl": pnl})

        print("💰 CLOSED:", pnl)

    # =========================
    # CREATE（完全統一）
    # =========================
    def _create_position(self, price):

        pid = f"BTCUSDT_{time.time()}"

        pos = {
            "position_id": pid,
            "symbol": "BTCUSDT",

            # 🔥 統一フォーマット
            "side": "LONG",
            "entry": price,
            "tp": price * 1.001,
            "sl": price * 0.999,
            "size": 1,

            "status": "OPEN",
            "created_at": time.time()
        }

        self.state_manager.set_position(pid, pos)

        if self.monitor:
            self.monitor.log_event("ENTRY", pos)

        print("🚀 ENTRY:", price)

        return pos

    # =========================
    # ORDER
    # =========================
    def execute_order(self, signal: Dict[str, Any]):
        if not self.active:
            return None

        return self._create_position(self.last_price)

    # =========================
    # RESULT
    # =========================
    def get_result(self):
        return {
            "realized_pnl": self.state_manager.realized_pnl,
            "positions": self.state_manager.get_positions()
        }