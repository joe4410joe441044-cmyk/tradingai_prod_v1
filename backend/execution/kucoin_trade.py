# -*- coding: utf-8 -*-

from .base import BaseClient
import requests
import time
import base64
import hmac
import hashlib
import logging
import json


class KucoinTradeClient(BaseClient):

    def __init__(self, api_key=None, api_secret=None, passphrase=None):
        self.logger = logging.getLogger(__name__)

        if not api_key or not api_secret or not passphrase:
            raise Exception("🚨 KUCOIN API KEY REQUIRED")

        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase

        self.base_url = "https://api-futures.kucoin.com"

    # =========================
    # SYMBOL
    # =========================
    def normalize_symbol(self, symbol: str) -> str:
        symbol = str(symbol).strip().upper()

        mapping = {
            "BTCUSDT": "XBTUSDTM",
            "ETHUSDT": "ETHUSDTM",
            "BNBUSDT": "BNBUSDTM",
            "SOLUSDT": "SOLUSDTM",
            "XRPUSDT": "XRPUSDTM",
        }

        mapped = mapping.get(symbol, symbol)
        print(f"[SYMBOL MAP] '{symbol}' -> '{mapped}'")
        return mapped

    # =========================
    # SIGN
    # =========================
    def _headers(self, method, endpoint, body=""):
        now = str(int(time.time() * 1000))
        str_to_sign = now + method + endpoint + body

        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                str_to_sign.encode(),
                hashlib.sha256
            ).digest()
        ).decode()

        passphrase = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                self.passphrase.encode(),
                hashlib.sha256
            ).digest()
        ).decode()

        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": now,
            "KC-API-PASSPHRASE": passphrase,
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json"
        }

    # =========================
    # BALANCE
    # =========================
    def get_balance(self):
        endpoint = "/api/v1/account-overview?currency=USDT"
        headers = self._headers("GET", endpoint)

        res = requests.get(self.base_url + endpoint, headers=headers)
        data = res.json()

        print("🔥 RAW BALANCE:", data)

        if data.get("code") != "200000":
            raise Exception(f"KUCOIN ERROR: {data}")

        d = data["data"]

        if "accountEquity" in d:
            balance = float(d["accountEquity"])
        else:
            balance = float(d.get("availableBalance", 0))

        print(f"[BALANCE PARSED] {balance}")
        return balance

    # =========================
    # 🔥 POSITIONS（完全版）
    # =========================
    def get_positions(self, symbol=None):

        endpoint = "/api/v1/positions"
        headers = self._headers("GET", endpoint)

        res = requests.get(self.base_url + endpoint, headers=headers)
        data = res.json()

        if data.get("code") != "200000":
            raise Exception(f"KUCOIN ERROR: {data}")

        positions = data["data"]

        active = []

        for p in positions:
            size = float(p.get("currentQty", 0))

            if size != 0:
                active.append({
                    "symbol": p["symbol"],
                    "qty": abs(size),
                    "side": "BUY" if size > 0 else "SELL",
                    "entry_price": float(p.get("avgEntryPrice", 0))
                })

        # symbol指定フィルタ
        if symbol:
            symbol = self.normalize_symbol(symbol)
            active = [p for p in active if p["symbol"] == symbol]

        return active[0] if active else None

    # =========================
    # PRICE
    # =========================
    def get_price(self, symbol: str):
        symbol = self.normalize_symbol(symbol)

        endpoint = f"/api/v1/ticker?symbol={symbol}"
        res = requests.get(self.base_url + endpoint)
        data = res.json()

        return float(data["data"]["price"])

    # =========================
    # SYMBOL RULES
    # =========================
    def get_symbol_rules(self, symbol: str):

        symbol = self.normalize_symbol(symbol)

        endpoint = f"/api/v1/contracts/{symbol}"
        res = requests.get(self.base_url + endpoint)
        data = res.json()

        if data.get("code") != "200000":
            raise Exception(f"KUCOIN SYMBOL ERROR: {data}")

        d = data["data"]

        return {
            "min_size": int(float(d["lotSize"])),
            "multiplier": float(d.get("multiplier", 1))
        }

    # =========================
    # 🔥 MIN QTY
    # =========================
    def get_min_qty(self, symbol):
        rules = self.get_symbol_rules(symbol)
        return rules["min_size"]

    # =========================
    # QTY NORMALIZE
    # =========================
    def normalize_qty(self, symbol: str, qty: float) -> int:

        rules = self.get_symbol_rules(symbol)
        min_size = rules["min_size"]

        qty = int(qty)

        if qty < min_size:
            return 0

        return qty

    # =========================
    # 🔥 LEVERAGE（必須）
    # =========================
    def set_leverage(self, symbol: str, leverage: int):

        symbol = self.normalize_symbol(symbol)

        endpoint = "/api/v1/position/risk-limit-level/change"

        body_dict = {
            "symbol": symbol,
            "leverage": str(leverage)
        }

        body = json.dumps(body_dict)
        headers = self._headers("POST", endpoint, body)

        res = requests.post(self.base_url + endpoint, headers=headers, data=body)
        data = res.json()

        if data.get("code") != "200000":
            print("⚠️ LEVERAGE ERROR:", data)
        else:
            print("✅ LEVERAGE SET:", leverage)

    # =========================
    # ORDER
    # =========================
    def create_order(self, symbol, side, qty, price=None):

        symbol = self.normalize_symbol(symbol)
        qty = self.normalize_qty(symbol, qty)

        if qty <= 0:
            raise Exception("🚨 INVALID QTY (0)")

        endpoint = "/api/v1/orders"

        body_dict = {
            "clientOid": str(int(time.time() * 1000)),
            "symbol": symbol,
            "side": side.lower(),
            "type": "market",
            "size": str(qty)
        }

        body = json.dumps(body_dict)
        headers = self._headers("POST", endpoint, body)

        res = requests.post(self.base_url + endpoint, headers=headers, data=body)
        data = res.json()

        if data.get("code") != "200000":
            raise Exception(f"KUCOIN ORDER ERROR: {data}")

        print("✅ KUCOIN ORDER SUCCESS:", data)
        return data

    def place_order(self, symbol, side, qty, price=None):
        return self.create_order(symbol, side, qty, price)

    # =========================
    # CLOSE（簡易版）
    # =========================
    def close_position(self, symbol):

        pos = self.get_positions(symbol)

        if not pos:
            print("⚠️ NO POSITION TO CLOSE")
            return

        side = "SELL" if pos["side"] == "BUY" else "BUY"

        return self.create_order(
            symbol=symbol,
            side=side,
            qty=pos["qty"]
        )