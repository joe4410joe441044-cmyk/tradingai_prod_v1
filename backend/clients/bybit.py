from .base import BaseClient

class BybitClient(BaseClient):
    def __init__(self):
        # TODO: APIキー読み込み
        pass

    def get_balance(self):
        # TODO: 実装
        return 1000.0

    def get_positions(self):
        return []

    def place_order(self, symbol, side, qty):
        print(f"[BYBIT] {side} {qty} {symbol}")