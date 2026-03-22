from abc import ABC, abstractmethod
from typing import Dict, List, Any


class BaseExchange(ABC):
    """
    すべての取引所クラスが継承する抽象基底クラス、E
    戦略・コア層はこ�Eインターフェースのみを使用する、E
    """

    @abstractmethod
    def connect(self) -> None:
        """API接続確誁E""
        pass

    @abstractmethod
    def get_balance(self) -> Dict[str, Any]:
        """残高取征E""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """保有ポジション取征E""
        pass

    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """現在価格取征E""
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
        """新規注斁E""
        pass

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """注斁E��ャンセル"""
        pass

    @abstractmethod
    def close_position(self, symbol: str) -> Dict[str, Any]:
        """ポジションクローズ"""
        pass
