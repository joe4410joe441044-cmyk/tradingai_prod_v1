# -*- coding: utf-8 -*-

from .base import BaseClient
import logging
import requests
import time
import hmac
import hashlib
import base64
import json


class BitgetTradeClient(BaseClient):

    def __init__(self, api_key=None, api_secret=None, passphrase=None):
        self.logger = logging.getLogger(__name__)

        if not api_key or not api_secret or not passphrase:
            raise Exception("🚨 BITGET API KEY REQUIRED")

        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase

        self.base_url = "https://api.bitget.com"

        self.logger.info("[BITGET] LIVE FUTURES MODE")

    # =========================
    # 認証
    # =========================
    def _sign(self, method, request_path, body=""):
        timestamp = str(int(time.time() * 1000))
        message = timestamp + method + request_path + body

        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                message.encode(),
                hashlib.sha256
            ).digest()
        ).decode()

        return timestamp, signature

    def _headers(self, method, path, body=""):
        ts, sign = self._sign(method, path, body)

        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    # =========================
    # PRICE
    # =========================
    def get_price(self, symbol: str):
        url = f"/api/v2/mix/market/ticker?symbol={symbol}&productType=USDT-FUTURES"

        res = requests.get(self.base_url + url).json()

        return float(res["data"][0]["last"])

    # =========================
    # BALANCE
    # =========================
    def get_balance(self):
        path = "/api/v2/mix/account/accounts?productType=USDT-FUTURES"

        headers = self._headers("GET", path)

        res = requests.get(self.base_url + path, headers=headers).json()

        return float(res["data"][0]["available"])

    # =========================
    # POSITIONS
    # =========================
    def get_positions(self, symbol=None):
        path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES"

        headers = self._headers("GET", path)

        res = requests.get(self.base_url + path, headers=headers).json()

        return res["data"]

    # =========================
    # ORDER（Futures）
    # =========================
    def create_order(self, symbol, side, qty, price=None):

        if qty <= 0:
            raise Exception("🚨 qty must be > 0")

        path = "/api/v2/mix/order/place-order"

        body = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginMode": "cross",
            "marginCoin": "USDT",
            "size": str(qty),
            "side": "buy" if side.upper() == "BUY" else "sell",
            "orderType": "market" if price is None else "limit"
        }

        if price:
            body["price"] = str(price)

        body_str = json.dumps(body)

        headers = self._headers("POST", path, body_str)

        res = requests.post(
            self.base_url + path,
            headers=headers,
            data=body_str
        ).json()

        return res

    # =========================
    # ExecutionEngine互換
    # =========================
    def place_order(self, symbol, side, qty, price=None):
        return self.create_order(symbol, side, qty, price)

    def execute_order(self, signal: dict):

        if not isinstance(signal, dict):
            raise Exception("🚨 SIGNAL MUST BE DICT")

        return self.create_order(
            symbol=signal["symbol"],
            side=signal["side"],
            qty=signal["qty"],
            price=signal.get("price")
        )