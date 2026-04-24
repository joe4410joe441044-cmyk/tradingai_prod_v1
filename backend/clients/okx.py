from .base import BaseClient

class OkxClient(BaseClient):
    def __init__(self):
        pass

    def get_balance(self):
        return 1000.0

    def get_positions(self):
        return []

    def place_order(self, symbol, side, qty):
        print(f"[OKX] {side} {qty} {symbol}")