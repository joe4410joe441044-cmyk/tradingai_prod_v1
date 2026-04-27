# -*- coding: utf-8 -*-

from .base import BaseClient
import logging
from pybit.unified_trading import HTTP


class BybitTradeClient(BaseClient):

    def __init__(self, api_key=None, api_secret=None):
        self.logger = logging.getLogger(__name__)

        if not api_key or not api_secret:
            raise Exception("🚨 BYBIT API KEY REQUIRED")

        # ✅ Bybit Futures セッション
        self.session = HTTP(
            testnet=False,
            api_key=api_key,
            api_secret=api_secret
        )

        self.logger.info("[BYBIT] LIVE FUTURES MODE")

    # =========================
    # PRICE
    # =========================
    def get_price(self, symbol: str):
        res = self.session.get_tickers(
            category="linear",
            symbol=symbol
        )
        return float(res["result"]["list"][0]["lastPrice"])

    # =========================
    # BALANCE
    # =========================
    def get_balance(self):
        res = self.session.get_wallet_balance(
            accountType="UNIFIED"
        )
        return float(res["result"]["list"][0]["totalWalletBalance"])

    # =========================
    # POSITIONS
    # =========================
    def get_positions(self, symbol=None):
        res = self.session.get_positions(
            category="linear",
            symbol=symbol
        )
        return res["result"]["list"]

    # =========================
    # ORDER（Futures）
    # =========================
    def create_order(self, symbol, side, qty, price=None):

        if qty <= 0:
            raise Exception("🚨 qty must be > 0")

        order_type = "Market" if price is None else "Limit"

        res = self.session.place_order(
            category="linear",  # ← これがFutures指定
            symbol=symbol,
            side="Buy" if side.upper() == "BUY" else "Sell",
            orderType=order_type,
            qty=str(qty),
            price=str(price) if price else None,
            timeInForce="GTC"
        )

        return res

    # =========================
    # ExecutionEngine互換
    # =========================
    def place_order(self, symbol, side, qty, price=None):
        return self.create_order(symbol, side, qty, price)

    def execute_order(self, signal: dict):

        if not isinstance(signal, dict):
            raise Exception("🚨 SIGNAL MUST BE DICT")

        return self.create_order(
            symbol=signal["symbol"],
            side=signal["side"],
            qty=signal["qty"],
            price=signal.get("price")
        )