# -*- coding: utf-8 -*-
import threading
from typing import Dict


class PortfolioManager:

    def __init__(self, initial_balance: float):

        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.realized_pnl = 0.0

        # symbol単位で管理（シンプル版）
        self.positions: Dict[str, dict] = {}

        self.max_exposure = 0.25
        self.lock = threading.Lock()

    # =========================
    # 基本
    # =========================
    def get_balance(self) -> float:
        with self.lock:
            return self.balance

    def get_equity(self, price_map: Dict[str, float]) -> float:
        # equity = 現金 + 含み損益
        return self.balance + self._calc_total_unrealized(price_map)

    # =========================
    # PnL計算（内部でやる）
    # =========================
    def _calc_unrealized(self, pos: dict, current_price: float) -> float:
        entry = pos["entry"]
        qty = pos["size"]
        side = pos["side"]

        if side == "BUY":
            return (current_price - entry) * qty
        else:
            return (entry - current_price) * qty

    def _calc_total_unrealized(self, price_map: Dict[str, float]) -> float:
        total = 0.0
        for symbol, pos in self.positions.items():
            price = price_map.get(symbol)
            if price is None:
                continue
            total += self._calc_unrealized(pos, price)
        return total

    # =========================
    # エクスポージャ
    # =========================
    def get_total_exposure(self) -> float:
        total = 0.0
        for p in self.positions.values():
            total += p["entry"] * p["size"]
        return total

    def get_exposure_ratio(self, price_map: Dict[str, float]) -> float:
        equity = self.get_equity(price_map)
        if equity == 0:
            return 0
        return self.get_total_exposure() / equity

    def can_open(self, symbol: str, price: float, size: float, price_map: Dict[str, float]) -> bool:
        with self.lock:
            new_exposure = price * size
            total = self.get_total_exposure()
            equity = self.get_equity(price_map)

            if equity <= 0:
                return False

            next_ratio = (total + new_exposure) / equity
            return next_ratio <= self.max_exposure

    # =========================
    # エントリー
    # =========================
    def open_position(self, symbol: str, price: float, size: float, side: str):

        with self.lock:
            # シンプル：1銘柄1ポジ（上書き）
            self.positions[symbol] = {
                "symbol": symbol,
                "entry": price,
                "size": size,
                "side": side
            }

    # =========================
    # クローズ
    # =========================
    def close_position(self, symbol: str, price: float):

        with self.lock:
            pos = self.positions.get(symbol)
            if not pos:
                return 0.0

            pnl = self._calc_unrealized(pos, price)

            # 実現損益
            self.realized_pnl += pnl
            self.balance += pnl

            del self.positions[symbol]

            return pnl

    # =========================
    # 情報取得
    # =========================
    def get_positions(self):
        with self.lock:
            return dict(self.positions)

    def summary(self, price_map: Dict[str, float]):

        unrealized = self._calc_total_unrealized(price_map)
        equity = self.balance + unrealized

        return {
            "balance": self.balance,
            "equity": equity,
            "unrealized_pnl": unrealized,
            "realized_pnl": self.realized_pnl,
            "positions": len(self.positions),
            "exposure_ratio": self.get_exposure_ratio(price_map),
            "symbols": list(self.positions.keys())
        }