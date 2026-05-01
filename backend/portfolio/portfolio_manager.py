# -*- coding: utf-8 -*-
import threading
from typing import Dict


class PortfolioManager:

    def __init__(self, initial_balance: float):

        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.unrealized_pnl = 0.0
        self.realized_pnl = 0.0

        self.positions: Dict[str, dict] = {}

        self.max_exposure = 0.25

        self.lock = threading.Lock()

    # =========================
    def set_balance(self, balance: float):
        with self.lock:
            self.balance = balance

    def get_balance(self) -> float:
        with self.lock:
            return self.balance

    # =========================
    def get_equity(self) -> float:
        return self.balance + self.unrealized_pnl

    # =========================
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

    # =========================
    def can_open(self, symbol: str, price: float, size: float) -> bool:

        with self.lock:
            new_exposure = price * size
            total = self.get_total_exposure()

            equity = self.get_equity()
            if equity <= 0:
                return False

            next_ratio = (total + new_exposure) / equity

            return next_ratio <= self.max_exposure

    # =========================
    def add(self, position: dict):
        with self.lock:
            self.positions[position["position_id"]] = position

    def remove(self, pid: str, realized_pnl: float):

        with self.lock:
            if pid in self.positions:
                del self.positions[pid]

                self.realized_pnl += realized_pnl
                self.balance += realized_pnl

    # =========================
    def update_unrealized_pnl(self, pnl: float):
        with self.lock:
            self.unrealized_pnl = pnl

    # =========================
    def get_positions(self):
        with self.lock:
            return dict(self.positions)

    # =========================
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