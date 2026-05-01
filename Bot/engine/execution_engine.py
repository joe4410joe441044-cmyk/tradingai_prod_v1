class ExecutionEngine:

    def __init__(self, exchange=None, logger=None, portfolio=None):
        self.exchange = exchange
        self.logger = logger
        self.portfolio = portfolio

        self.price = 0
        self.pnl = 0
        self.balance = 0
        self.symbol = "BTCUSDT"
        self.engine_id = id(self)

        self.config = {
            "risk_percent": 1,
            "leverage": 10,
            "sl_percent": 1
        }

    def start(self):
        return {"status": "started"}

    def stop(self):
        return {"status": "stopped"}

    def on_price(self, price):
        self.price = price

    def get_result(self):
        balance = self.balance
        equity = balance + self.pnl

        return {
            "price": self.price,
            "pnl": self.pnl,
            "balance": balance,
            "equity": equity,
            "preview": {},
            "symbol": self.symbol,
            "engine_id": self.engine_id
        }