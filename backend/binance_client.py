# backend/binance_client.py

from backend.exchange_client import ExchangeClient
from binance.client import Client
from binance.enums import *

import logging


class BinanceClient(ExchangeClient):
    """
    Binance Futures Client (Production Ready Wrapper)
    """

    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret)
        self.logger = logging.getLogger(__name__)

    # ============================
    # 内部ユーティリティ（超重要）
    # ============================
    def _adjust_quantity(self, symbol: str, qty: float) -> float:
        info = self.client.futures_exchange_info()
        symbol_info = next(s for s in info["symbols"] if s["symbol"] == symbol)

        lot_size = next(f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE")
        step_size = float(lot_size["stepSize"])

        qty = float(qty)
        qty = qty - (qty % step_size)

        return float(f"{qty:.8f}")

    def _adjust_price(self, symbol: str, price: float) -> float:
        info = self.client.futures_exchange_info()
        symbol_info = next(s for s in info["symbols"] if s["symbol"] == symbol)

        price_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER")
        tick_size = float(price_filter["tickSize"])

        price = float(price)
        price = price - (price % tick_size)

        return float(f"{price:.8f}")

    # ============================
    # 価格取得
    # ============================
    def get_price(self, symbol: str) -> float:
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except Exception as e:
            self.logger.error(f"[get_price ERROR] {e}")
            return 0.0

    # ============================
    # 新規注文（本体）
    # ============================
    def create_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        price: float = None
    ):
        try:
            order_side = SIDE_BUY if side.upper() == "BUY" else SIDE_SELL

            # =========================
            # 数量調整（超重要）
            # =========================
            qty = self._adjust_quantity(symbol, qty)

            if qty <= 0:
                raise ValueError("qty must be > 0 after adjustment")

            # =========================
            # MARKET ORDER
            # =========================
            if order_type.upper() == "MARKET":
                return self.client.futures_create_order(
                    symbol=symbol,
                    side=order_side,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty
                )

            # =========================
            # LIMIT ORDER
            # =========================
            elif order_type.upper() == "LIMIT":
                if price is None:
                    raise ValueError("LIMIT order requires price")

                price = self._adjust_price(symbol, price)

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

        except Exception as e:
            self.logger.error(f"[create_order ERROR] {e}")
            return {
                "status": "ERROR",
                "message": str(e),
                "symbol": symbol,
                "side": side
            }

    # ============================
    # ポジション取得
    # ============================
    def get_positions(self, symbol: str):
        try:
            return self.client.futures_position_information(symbol=symbol)
        except Exception as e:
            self.logger.error(f"[get_positions ERROR] {e}")
            return []

    # ============================
    # 統一エントリーポイント
    # ============================
    def execute_order(self, signal: dict):
        """
        signal:
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 0.001,
            "price": 12345,        # optional (LIMIT用)
            "order_type": "MARKET"
        }
        """

        try:
            if not isinstance(signal, dict):
                raise TypeError("signal must be dict")

            required_keys = ["symbol", "side", "qty"]
            for k in required_keys:
                if k not in signal:
                    raise ValueError(f"Missing key: {k}")

            return self.create_order(
                symbol=signal["symbol"],
                side=signal["side"],
                qty=signal["qty"],
                order_type=signal.get("order_type", "MARKET"),
                price=signal.get("price")
            )

        except Exception as e:
            self.logger.error(f"[execute_order ERROR] {e}")
            return {
                "status": "ERROR",
                "message": str(e),
                "signal": signal
            }