# -*- coding: utf-8 -*-

from .base import BaseClient
import logging
import requests
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
    # サーバー時間取得
    # =========================
    def _get_server_time(self):
        url = "/api/v2/public/time"
        res = requests.get(self.base_url + url)

        try:
            data = res.json()
            return str(int(data["data"]["serverTime"]))
        except Exception:
            raise Exception(f"🚨 TIME FETCH ERROR: {res.text}")

    # =========================
    # 認証
    # =========================
    def _sign(self, method, request_path, body=""):
        timestamp = self._get_server_time()
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
    # 共通レスポンスチェック
    # =========================
    def _check_response(self, res):
        try:
            data = res.json()
        except Exception:
            raise Exception(f"🚨 INVALID RESPONSE: {res.text}")

        if data.get("code") != "00000":
            raise Exception(f"🚨 BITGET ERROR: {data}")

        return data

    # =========================
    # PRICE
    # =========================
    def get_price(self, symbol: str):
        url = f"/api/v2/mix/market/ticker?symbol={symbol}&productType=USDT-FUTURES"

        res = requests.get(self.base_url + url)
        data = self._check_response(res)

        return float(data["data"][0]["last"])

    # =========================
    # BALANCE（修正済）
    # =========================
    def get_balance(self):
        path = "/api/v2/mix/account/accounts?productType=USDT-FUTURES"

        headers = self._headers("GET", path)

        res = requests.get(self.base_url + path, headers=headers)
        data = self._check_response(res)

        account = data["data"][0]

        # 🔥 equity優先（UIと一致しやすい）
        return float(account.get("equity", account.get("available", 0)))

    # =========================
    # POSITIONS（修正済）
    # =========================
    def get_positions(self, symbol=None):
        path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES"

        headers = self._headers("GET", path)

        res = requests.get(self.base_url + path, headers=headers)
        data = self._check_response(res)

        # 🔥 size=0を除外（重要）
        return [
            p for p in data["data"]
            if float(p.get("total", 0)) != 0
        ]

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
            "marginMode": "isolated",
            "marginCoin": "USDT",
            "size": str(qty),
            "side": "buy" if side.upper() == "BUY" else "sell",
            "tradeSide": "open",
            "orderType": "market" if price is None else "limit",
            "positionSide": "net"
        }

        if price:
            body["price"] = str(price)

        body_str = json.dumps(body)

        headers = self._headers("POST", path, body_str)

        res = requests.post(
            self.base_url + path,
            headers=headers,
            data=body_str
        )

        data = self._check_response(res)

        return data

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