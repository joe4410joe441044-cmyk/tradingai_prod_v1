# -*- coding: utf-8 -*-
from typing import List, Dict


class BaseClient:

    def get_balance(self) -> float:
        """残高"""
        raise NotImplementedError

    def get_positions(self) -> List[Dict]:
        """生ポジションデータ（未加工）"""
        raise NotImplementedError

    def get_price(self, symbol: str) -> float:
        """現在価格"""
        raise NotImplementedError

    def place_order(self, symbol: str, side: str, qty: float):
        """注文"""
        raise NotImplementedError

    def close_position(self, symbol: str):
        """ポジションクローズ"""
        raise NotImplementedError