# -*- coding: utf-8 -*-

from .base import BaseClient


class BybitTradeClient(BaseClient):
    """
    Bybit 実トレード用クライアント（現状はダミー）
    将来的にREST API接続へ拡張
    """

    def __init__(self):
        # TODO: APIキー読み込み（.envなど）
        self.name = "BYBIT"

    # =========================
    # BALANCE
    # =========================
    def get_balance(self):
        # TODO: 実API接続
        return 1000.0

    # =========================
    # POSITIONS
    # =========================
    def get_positions(self):
        # TODO: 実API接続
        return []

    # =========================
    # ORDER
    # =========================
    def place_order(self, symbol, side, qty):
        """
        実トレード（現状はダミー）
        """
        print(f"[BYBIT ORDER] {side} {qty} {symbol}")

    # =========================
    # OPTIONAL（将来用）
    # =========================
    def cancel_order(self, order_id):
        print(f"[BYBIT CANCEL] {order_id}")

    def get_order(self, order_id):
        return {"order_id": order_id, "status": "UNKNOWN"}