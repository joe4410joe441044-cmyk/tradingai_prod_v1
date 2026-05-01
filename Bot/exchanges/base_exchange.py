from abc import ABC, abstractmethod
from typing import List, Dict


class BaseExchange(ABC):

    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """
        統一フォーマットでポジション取得
        必須キー:
        symbol, side, size, entry, pnl
        """
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """残高"""
        pass

    @abstractmethod
    def get_pnl(self) -> float:
        """合計PnL"""
        pass

    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """現在価格"""
        pass

    @abstractmethod
    def create_order(self, symbol: str, side: str, size: float):
        """注文"""
        pass

    @abstractmethod
    def close_position(self, symbol: str):
        """ポジションクローズ"""
        pass