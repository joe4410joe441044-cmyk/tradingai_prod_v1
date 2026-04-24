from .base import BaseClient

class KucoinClient(BaseClient):
    def __init__(self):
        pass

    def get_balance(self):
        return 1000.0

    def get_positions(self):
        return []

    def place_order(self, symbol, side, qty):
        print(f"[KUCOIN] {side} {qty} {symbol}")