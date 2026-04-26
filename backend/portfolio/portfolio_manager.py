# -*- coding: utf-8 -*-
import threading
from typing import Dict


class PortfolioManager:

    def __init__(self, initial_balance: float):

        # ===== 資金 =====
        self.initial_balance = initial_balance
        self.balance = initial_balance   # 実現残高
        self.unrealized_pnl = 0.0        # 未実現
        self.realized_pnl = 0.0          # 実現

        # ===== ポジション =====
        self.positions: Dict[str, dict] = {}

        # ===== リスク制限 =====
        self.max_exposure = 0.25  # 25%

        # ===== スレッド安全 =====
        self.lock = threading.Lock()

    # =====================================================
    # ★ 追加（今回の核心）
    # =====================================================
    def set_balance(self, balance: float):
        with self.lock:
            self.balance = balance

    def get_balance(self) -> float:
        with self.lock:
            return self.balance

    # =====================================================
    # EQUITY
    # =====================================================
    def get_equity(self) -> float:
        return self.balance + self.unrealized_pnl

    # =====================================================
    # EXPOSURE（重要）
    # =====================================================
    def get_total_exposure(self) -> float:
        total = 0.0
        for p in self.positions.values():
            total += p["entry"] * p["size"]
        return total

    def get_exposure_ratio(self) -> float:
        equity = self.get_equity()
        if equity == 0:
            return 0
        return self.get_total_exposure() / equity

    # =====================================================
    # ENTRY CHECK
    # =====================================================
    def can_open(self, symbol: str, price: float, size: float) -> bool:

        with self.lock:
            new_exposure = price * size
            total = self.get_total_exposure()

            equity = self.get_equity()
            if equity <= 0:
                return False

            next_ratio = (total + new_exposure) / equity

            return next_ratio <= self.max_exposure

    # =====================================================
    # ADD POSITION
    # =====================================================
    def add(self, position: dict):

        with self.lock:
            self.positions[position["position_id"]] = position

    # =====================================================
    # REMOVE POSITION（クローズ）
    # =====================================================
    def remove(self, pid: str, realized_pnl: float):

        with self.lock:
            if pid in self.positions:
                del self.positions[pid]

                # ★ 実現損益反映
                self.realized_pnl += realized_pnl
                self.balance += realized_pnl

    # =====================================================
    # UPDATE PnL（Executionから呼ばれる）
    # =====================================================
    def update_unrealized_pnl(self, pnl: float):

        with self.lock:
            self.unrealized_pnl = pnl

    # =====================================================
    # POSITIONS
    # =====================================================
    def get_positions(self):
        with self.lock:
            return dict(self.positions)

    # =====================================================
    # SUMMARY（UI用）
    # =====================================================
    def summary(self):

        with self.lock:
            return {
                "balance": self.balance,
                "equity": self.get_equity(),
                "unrealized_pnl": self.unrealized_pnl,
                "realized_pnl": self.realized_pnl,
                "positions": len(self.positions),
                "exposure_ratio": self.get_exposure_ratio(),
                "symbols": list(set(p["symbol"] for p in self.positions.values()))
            }