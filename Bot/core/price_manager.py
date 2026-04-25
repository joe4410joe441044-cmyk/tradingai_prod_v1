import threading

class PriceManager:

    def __init__(self):
        self.prices = {}
        self.lock = threading.Lock()

        # 🔥 追加：購読者（Engineなど）
        self.subscribers = []

    # =========================
    # SUBSCRIBE
    # =========================
    def subscribe(self, callback):
        """
        callback(symbol, price)
        """
        self.subscribers.append(callback)

    # =========================
    # UPDATE（🔥最重要）
    # =========================
    def update(self, symbol, price):

        symbol = symbol.upper()

        with self.lock:
            self.prices[symbol] = price

        # 🔥 ここが核心（全てを動かす）
        for cb in self.subscribers:
            try:
                cb(symbol, price)
            except Exception as e:
                print("[PriceManager ERROR]", e)

    # =========================
    # GET
    # =========================
    def get(self, symbol):
        with self.lock:
            return self.prices.get(symbol.upper(), 0.0)

    def get_all(self):
        with self.lock:
            return dict(self.prices)