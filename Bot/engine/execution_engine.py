# -*- coding: utf-8 -*-
import logging
import time
import threading
from typing import Dict, Any

from Bot.control.duplicate_guard import ExecutionGuard
from backend.protection.risk_manager import RiskManager


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
        monitor=None,
        portfolio=None
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

        if portfolio is None:
            raise Exception("PortfolioManager is required")

        self.portfolio = portfolio

    # =========================
    # SIZE CALC（追加）
    # =========================
    def _calc_position_size(self, price):
        equity = self.portfolio.get_equity()

        risk_ratio = 0.01
        usd_size = equity * risk_ratio

        size = usd_size / price if price > 0 else 0

        # 最小サイズ制限
        if size < 0.0001:
            return 0

        return size

    # =========================
    # FORCE CLOSE（追加）
    # =========================
    def _force_close_all(self):
        positions = list(self.state_manager.get_positions().values())

        for pos in positions:
            try:
                self._close_position(pos, self.last_price)
            except Exception as e:
                if self.monitor:
                    self.monitor.log_event("FORCE_CLOSE_ERROR", {"error": str(e)})

    # =========================
    # AI SIGNAL（追加）
    # =========================
    def handle_signal(self, signal):

        if not self.active:
            return

        positions = self.state_manager.get_positions()
        has_position = len(positions) > 0

        if signal == "BUY" and not has_position:
            self._create_position(self.last_price, "LONG")

        elif signal == "SELL" and not has_position:
            self._create_position(self.last_price, "SHORT")

        elif signal == "CLOSE":
            self._force_close_all()

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
    # PRICE
    # =========================
    def on_price(self, price: float):
        if not self.active:
            return

        self.last_price = price

        # ===== 🚨 KILL SWITCH（追加・最重要）=====
        if self.risk.kill_switch.active:
            self._force_close_all()
            self.stop()
            return

        # ===== リスクチェック =====
        if not self.risk.allow_trade():
            return

        # ===== ENTRY / EXIT =====
        self.check_entry(price)
        self.check_exit(price)

        # ===== PnL更新 =====
        positions = self.state_manager.get_positions()
        total_pnl = 0

        for p in positions.values():
            pnl = self.state_manager.calculate_position_pnl(p, price)

            p["pnl"] = pnl
            p["pnl_percent"] = (pnl / (p["entry"] * p["size"])) * 100 if p["entry"] else 0
            p["duration"] = time.time() - p.get("created_at", time.time())

            total_pnl += pnl

        self.pnl = total_pnl

        # ===== Portfolio =====
        self.portfolio.update_unrealized_pnl(self.pnl)

        equity = self.portfolio.get_equity()

        # ===== Risk =====
        self.risk.update(equity, self.pnl)

        # ===== monitor =====
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

        # ★ AIに任せる構造にするならここは将来削除可
        self._create_position(price, "LONG")

    # =========================
    # EXIT
    # =========================
    def check_exit(self, price):

        now = time.time()

        for pos in list(self.state_manager.get_positions().values()):

            if pos.get("status") != "OPEN":
                continue

            if now - pos.get("created_at", now) < 2:
                continue

            if pos["side"] == "LONG":
                if price >= pos["tp"] or price <= pos["sl"]:
                    self._close_position(pos, price)
            else:
                if price <= pos["tp"] or price >= pos["sl"]:
                    self._close_position(pos, price)

    # =========================
    # CLOSE
    # =========================
    def _close_position(self, pos, price):

        if pos["side"] == "LONG":
            pnl = (price - pos["entry"]) * pos["size"]
        else:
            pnl = (pos["entry"] - price) * pos["size"]

        self.state_manager.realized_pnl += pnl

        pos["status"] = "CLOSED"
        self.state_manager.remove_position(pos["position_id"])

        self.portfolio.remove(pos["position_id"], pnl)

        equity = self.portfolio.get_equity()
        self.risk.update(equity, pnl)

        if self.monitor:
            self.monitor.log_event("CLOSE", {
                "pnl": pnl,
                "symbol": pos["symbol"]
            })

        print("💰 CLOSED:", pnl)

    # =========================
    # CREATE（修正）
    # =========================
    def _create_position(self, price, side="LONG"):

        size = self._calc_position_size(price)

        if size <= 0:
            return None

        if not self.portfolio.can_open("BTCUSDT", price, size):
            return None

        pid = f"BTCUSDT_{time.time()}"

        pos = {
            "position_id": pid,
            "symbol": "BTCUSDT",
            "side": side,

            "entry": price,
            "tp": price * 1.001 if side == "LONG" else price * 0.999,
            "sl": price * 0.999 if side == "LONG" else price * 1.001,
            "size": size,

            "pnl": 0,
            "pnl_percent": 0,
            "duration": 0,

            "status": "OPEN",
            "created_at": time.time()
        }

        self.state_manager.set_position(pid, pos)
        self.portfolio.add(pos)

        if self.monitor:
            self.monitor.log_event("ENTRY", pos)

        print("🚀 ENTRY:", side, price, "size:", size)

        return pos

    # =========================
    # ORDER
    # =========================
    def execute_order(self, signal: Dict[str, Any]):
        if not self.active:
            return None

        self.handle_signal(signal)

    # =========================
    # RESULT
    # =========================
    def get_result(self):
        return {
            "realized_pnl": self.state_manager.realized_pnl,
            "positions": self.state_manager.get_positions()
        }