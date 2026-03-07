from abc import ABC, abstractmethod
from typing import Dict, List, Any


class BaseExchange(ABC):
    """
    すべての取引所クラスが継承する抽象基底クラス。
    戦略・コア層はこのインターフェースのみを使用する。
    """

    @abstractmethod
    def connect(self) -> None:
        """API接続確認"""
        pass

    @abstractmethod
    def get_balance(self) -> Dict[str, Any]:
        """残高取得"""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """保有ポジション取得"""
        pass

    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """現在価格取得"""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "Market",
        stop_loss: float = None,
        take_profit: float = None
    ) -> Dict[str, Any]:
        """新規注文"""
        pass

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """注文キャンセル"""
        pass

    @abstractmethod
    def close_position(self, symbol: str) -> Dict[str, Any]:
        """ポジションクローズ"""
        pass
