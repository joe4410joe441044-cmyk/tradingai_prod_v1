# backend/exchange_client.py
from abc import ABC, abstractmethod

class ExchangeClient(ABC):
    @abstractmethod
    def get_price(self, symbol: str) -> float:
        pass

    @abstractmethod
    def create_order(self, symbol: str, side: str, qty: float, order_type: str, price: float = None):
        pass

    @abstractmethod
    def get_positions(self, symbol: str):
        pass