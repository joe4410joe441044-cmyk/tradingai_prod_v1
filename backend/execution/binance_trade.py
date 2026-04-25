# -*- coding: utf-8 -*-

from backend.exchange_client import ExchangeClient
from binance.client import Client
from binance.enums import *

import logging


class BinanceTradeClient(ExchangeClient):
    """
    Binance Futures 実トレードクライアント（Execution専用）
    """

    def __init__(self, api_key: str = None, api_secret: str = None):
        self.logger = logging.getLogger(__name__)

        # APIキーがない場合はDRYモード
        if api_key and api_secret:
            self.client = Client(api_key, api_secret)
            self.live = True
        else:
            self.client = None
            self.live = False
            self.logger.warning("[BINANCE] DRY MODE (no API key)")

    # ============================
    # 価格取得（補助用）
    # ============================
    def get_price(self, symbol: str) -> float:
        if not self.client:
            return 0.0

        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except Exception as e:
            self.logger.error(f"[get_price ERROR] {e}")
            return 0.0

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
        if not self.live:
            print(f"[BINANCE DRY ORDER] {side} {qty} {symbol}")
            return {"status": "DRY_RUN"}

        try:
            order_side = SIDE_BUY if side.upper() == "BUY" else SIDE_SELL

            qty = float(qty)
            if qty <= 0:
                raise ValueError("qty must be > 0")

            # =========================
            # MARKET
            # =========================
            if order_type.upper() == "MARKET":
                return self.client.futures_create_order(
                    symbol=symbol,
                    side=order_side,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty
                )

            # =========================
            # LIMIT
            # =========================
            elif order_type.upper() == "LIMIT":
                if price is None:
                    raise ValueError("LIMIT order requires price")

                price = float(price)

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
    # ExecutionEngine用インターフェース
    # ============================
    def place_order(self, symbol: str, side: str, qty: float, price=None):
        return self.create_order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type="MARKET" if price is None else "LIMIT",
            price=price
        )

    # ============================
    # ポジション取得
    # ============================
    def get_positions(self, symbol: str = None):
        if not self.client:
            return []

        try:
            if symbol:
                return self.client.futures_position_information(symbol=symbol)
            return self.client.futures_position_information()
        except Exception as e:
            self.logger.error(f"[get_positions ERROR] {e}")
            return []

    # ============================
    # 残高取得
    # ============================
    def get_balance(self):
        if not self.client:
            return 1000.0

        try:
            balance = self.client.futures_account_balance()
            usdt = next((b for b in balance if b["asset"] == "USDT"), None)
            return float(usdt["balance"]) if usdt else 0.0
        except Exception as e:
            self.logger.error(f"[get_balance ERROR] {e}")
            return 0.0

    # ============================
    # 統一エントリーポイント（互換維持）
    # ============================
    def execute_order(self, signal: dict):
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