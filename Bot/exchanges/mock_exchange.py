# Bot/exchanges/mock_exchange.py

from Bot.exchanges.base_exchange import BaseExchange
import random
from datetime import datetime


class MockExchange(BaseExchange):
    """
    仮想取引所（安定版）
    - StateManager用
    - BOTテスト用
    """

    def __init__(self):
        self.positions = [
            {
                "id": "mock-1",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "entryPrice": 65000.0,
                "qty": 0.01,
                "sl": None,
                "tp": None,
                "time": datetime.utcnow().isoformat()
            }
        ]

    # -------------------------
    # ポジション取得
    # -------------------------
    def get_open_positions(self):
        return self.positions

    # -------------------------
    # 価格取得（疑似変動）
    # -------------------------
    def get_price(self, symbol: str):
        base = 65000
        return base + random.uniform(-200, 200)

    # -------------------------
    # 注文作成（ダミー）
    # -------------------------
    def create_order(self, symbol: str, side: str, qty: float, order_type: str = "market"):
        order = {
            "status": "mock_order_created",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "time": datetime.utcnow().isoformat()
        }

        print(f"[MOCK ORDER] {order}")
        return order

    # -------------------------
    # ポジションクローズ
    # -------------------------
    def close_position(self, position_id: str):
        before = len(self.positions)

        self.positions = [
            p for p in self.positions
            if p["id"] != position_id
        ]

        after = len(self.positions)

        print(f"[MOCK CLOSE] {position_id} ({before} -> {after})")

        return {
            "status": "closed",
            "position_id": position_id
        }