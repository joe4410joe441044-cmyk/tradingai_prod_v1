# -*- coding: utf-8 -*-

from backend.exchange_client import ExchangeClient
from binance.client import Client
from binance.enums import *

import logging


class BinanceTradeClient(ExchangeClient):

    def __init__(self, api_key: str, api_secret: str):

        self.logger = logging.getLogger(__name__)

        if not api_key or not api_secret:
            raise Exception("🚨 BINANCE API KEY REQUIRED")

        self.client = Client(api_key, api_secret)
        self.logger.info("[BINANCE] LIVE MODE ONLY")

    # =========================
    # PRICE
    # =========================
    def get_price(self, symbol: str) -> float:

        data = self.client.futures_symbol_ticker(symbol=symbol)

        if "price" not in data:
            raise Exception("🚨 INVALID PRICE DATA")

        price = float(data["price"])

        if price <= 0:
            raise Exception("🚨 PRICE <= 0")

        return price

    # =========================
    # BALANCE
    # =========================
    def get_balance(self):

        balances = self.client.futures_account_balance()

        usdt = next((b for b in balances if b["asset"] == "USDT"), None)

        if not usdt:
            raise Exception("🚨 USDT BALANCE NOT FOUND")

        balance = float(usdt["balance"])

        if balance <= 0:
            raise Exception("🚨 INVALID BALANCE")

        return balance

    # =========================
    # POSITIONS
    # =========================
    def get_positions(self, symbol: str = None):

        data = self.client.futures_position_information(symbol=symbol) \
            if symbol else self.client.futures_position_information()

        if data is None:
            raise Exception("🚨 POSITION FETCH FAILED")

        return data

    # =========================
    # ORDER
    # =========================
    def create_order(self, symbol, side, qty, order_type="MARKET", price=None):

        if qty <= 0:
            raise Exception("🚨 qty must be > 0")

        order_side = SIDE_BUY if side.upper() == "BUY" else SIDE_SELL

        if order_type.upper() == "MARKET":

            return self.client.futures_create_order(
                symbol=symbol,
                side=order_side,
                type=ORDER_TYPE_MARKET,
                quantity=float(qty)
            )

        if order_type.upper() == "LIMIT":

            if price is None:
                raise Exception("🚨 LIMIT requires price")

            return self.client.futures_create_order(
                symbol=symbol,
                side=order_side,
                type=ORDER_TYPE_LIMIT,
                quantity=float(qty),
                price=str(price),
                timeInForce=TIME_IN_FORCE_GTC
            )

        raise Exception("🚨 INVALID ORDER TYPE")

    # =========================
    # ExecutionEngine用
    # =========================
    def place_order(self, symbol, side, qty, price=None):

        return self.create_order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type="MARKET" if price is None else "LIMIT",
            price=price
        )

    # =========================
    # SIGNAL API
    # =========================
    def execute_order(self, signal: dict):

        if not isinstance(signal, dict):
            raise Exception("🚨 SIGNAL MUST BE DICT")

        required = ["symbol", "side", "qty"]

        for k in required:
            if k not in signal:
                raise Exception(f"🚨 Missing {k}")

        return self.create_order(
            symbol=signal["symbol"],
            side=signal["side"],
            qty=signal["qty"],
            order_type=signal.get("order_type", "MARKET"),
            price=signal.get("price")
        )