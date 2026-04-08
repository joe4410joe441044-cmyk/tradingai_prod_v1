# backend/binance_client.py
from backend.exchange_client import ExchangeClient
from binance.client import Client
from binance.enums import *

class BinanceClient(ExchangeClient):
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret)

    def get_price(self, symbol: str) -> float:
        ticker = self.client.futures_symbol_ticker(symbol=symbol)
        return float(ticker['price'])

    def create_order(self, symbol: str, side: str, qty: float, order_type: str = "MARKET", price: float = None):
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

    def get_positions(self, symbol: str):
        positions = self.client.futures_position_information(symbol=symbol)
        return positions