# backend/binance_client.py
from backend.exchange_client import ExchangeClient
from binance.client import Client
from binance.enums import *

class BinanceClient(ExchangeClient):
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret)

    # ============================
    # 価格取得
    # ============================
    def get_price(self, symbol: str) -> float:
        ticker = self.client.futures_symbol_ticker(symbol=symbol)
        return float(ticker["price"])

    # ============================
    # 新規注文（内部本体）
    # ============================
    def create_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        price: float = None
    ):
        order_side = SIDE_BUY if side.upper() == "BUY" else SIDE_SELL

        if order_type.upper() == "MARKET":
            return self.client.futures_create_order(
                symbol=symbol,
                side=order_side,
                type=ORDER_TYPE_MARKET,
                quantity=qty
            )

        elif order_type.upper() == "LIMIT":
            return self.client.futures_create_order(
                symbol=symbol,
                side=order_side,
                type=ORDER_TYPE_LIMIT,
                quantity=qty,
                price=str(price),
                timeInForce=TIME_IN_FORCE_GTC
            )

        else:
            raise ValueError(f"Unsupported order_type: {order_type}")

    # ============================
    # ポジション取得
    # ============================
    def get_positions(self, symbol: str):
        return self.client.futures_position_information(symbol=symbol)

    # ============================
    # ★統一エントリーポイント（重要）
    # ExecutionEngine からここだけ呼ぶ
    # ============================
    def execute_order(self, signal: dict):
        """
        signal例:
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 0.001,
            "price": 12345,
            "order_type": "MARKET"
        }
        """

        if not isinstance(signal, dict):
            raise TypeError("signal must be dict")

        required_keys = ["symbol", "side", "qty"]
        for k in required_keys:
            if k not in signal:
                raise ValueError(f"Missing key in signal: {k}")

        return self.create_order(
            symbol=signal["symbol"],
            side=signal["side"],
            qty=signal["qty"],
            order_type=signal.get("order_type", "MARKET"),
            price=signal.get("price", None)
        )