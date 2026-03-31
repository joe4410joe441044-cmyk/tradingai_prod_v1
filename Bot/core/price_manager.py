import threading

class PriceManager:
    def __init__(self):
        self.prices = {}
        self.lock = threading.Lock()

    def update(self, symbol, price):
        with self.lock:
            self.prices[symbol.upper()] = price  # ★統一

    def get(self, symbol):
        with self.lock:
            return self.prices.get(symbol.upper(), 0.0)

    def get_all(self):
        with self.lock:
            return dict(self.prices)