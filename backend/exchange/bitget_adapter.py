# -*- coding: utf-8 -*-

from typing import List, Dict
from Bot.exchanges.base_exchange import BaseExchange


class BitgetExchange(BaseExchange):

    def __init__(self, client):
        self.client = client

    # =========================
    # Positions（最重要）
    # =========================
    def get_positions(self) -> List[Dict]:

        raw = self.client.get_positions()
        results = []

        for p in raw:
            try:
                size = float(p.get("total", 0))

                # ポジションなしは除外
                if size == 0:
                    continue

                side_raw = (p.get("holdSide") or "").lower()

                side = "LONG" if side_raw == "long" else "SHORT"

                results.append({
                    "symbol": p.get("symbol"),
                    "side": side,
                    "size": abs(size),
                    "entry": float(p.get("openPriceAvg", 0)),
                    "pnl": float(p.get("unrealizedPL", 0))
                })

            except Exception:
                continue

        return results

    # =========================
    # Balance
    # =========================
    def get_balance(self) -> float:
        try:
            return float(self.client.get_balance())
        except Exception:
            return 0.0

    # =========================
    # PnL
    # =========================
    def get_pnl(self) -> float:
        try:
            return sum(p["pnl"] for p in self.get_positions())
        except Exception:
            return 0.0

    # =========================
    # Price
    # =========================
    def get_price(self, symbol: str) -> float:
        try:
            return float(self.client.get_price(symbol))
        except Exception:
            return 0.0

    # =========================
    # Order
    # =========================
    def create_order(self, symbol: str, side: str, size: float):
        side_conv = "BUY" if side == "LONG" else "SELL"
        return self.client.place_order(symbol, side_conv, size)

    def close_position(self, symbol: str):
        positions = self.get_positions()

        for p in positions:
            if p["symbol"] == symbol:
                side = "SELL" if p["side"] == "LONG" else "BUY"
                return self.client.place_order(symbol, side, p["size"])

        return None