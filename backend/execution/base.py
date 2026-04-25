class BaseClient:
    def get_balance(self) -> float:
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def place_order(self, symbol: str, side: str, qty: float):
        raise NotImplementedError