# -*- coding: utf-8 -*-

from .base import BaseClient
import logging


class BybitTradeClient(BaseClient):

    def __init__(self, api_key=None, api_secret=None):
        self.logger = logging.getLogger(__name__)

        if not api_key or not api_secret:
            raise Exception("🚨 BYBIT API KEY REQUIRED")

        # ★ ここに本来Bybitセッション初期化
        self.session = None

        raise Exception("🚨 BYBIT LIVE CLIENT NOT IMPLEMENTED")

    # =========================
    # BALANCE
    # =========================
    def get_balance(self):
        raise Exception("🚨 BYBIT get_balance NOT IMPLEMENTED")

    # =========================
    # POSITIONS
    # =========================
    def get_positions(self, symbol=None):
        raise Exception("🚨 BYBIT get_positions NOT IMPLEMENTED")

    # =========================
    # ORDER
    # =========================
    def create_order(self, symbol, side, qty, price=None):
        raise Exception("🚨 BYBIT create_order NOT IMPLEMENTED")

    # =========================
    # ExecutionEngine互換
    # =========================
    def place_order(self, symbol, side, qty, price=None):
        return self.create_order(symbol, side, qty, price)

    def execute_order(self, signal: dict):

        if not isinstance(signal, dict):
            raise Exception("🚨 SIGNAL MUST BE DICT")

        required = ["symbol", "side", "qty"]

        for k in required:
            if k not in signal:
                raise Exception(f"🚨 Missing {k}")

        return self.create_order(
            symbol=signal["symbol"],
            side=signal["side"],
            qty=signal["qty"],
            price=signal.get("price")
        )

    # =========================
    # OPTIONAL
    # =========================
    def cancel_order(self, order_id):
        raise Exception("🚨 BYBIT cancel_order NOT IMPLEMENTED")

    def get_order(self, order_id):
        raise Exception("🚨 BYBIT get_order NOT IMPLEMENTED")