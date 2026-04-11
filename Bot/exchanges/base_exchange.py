# Bot/exchanges/base_exchange.py

from abc import ABC, abstractmethod


class BaseExchange(ABC):

    @abstractmethod
    def get_open_positions(self):
        """現在のポジション一覧を取得"""
        pass

    @abstractmethod
    def get_price(self, symbol: str):
        """現在価格取得"""
        pass

    @abstractmethod
    def create_order(self, symbol: str, side: str, qty: float, order_type: str = "market"):
        """注文作成"""
        pass

    @abstractmethod
    def close_position(self, position_id: str):
        """ポジションクローズ"""
        pass