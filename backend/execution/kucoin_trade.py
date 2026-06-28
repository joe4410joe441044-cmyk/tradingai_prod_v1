# -*- coding: utf-8 -*-

from .base import BaseClient

import requests
import time
import base64
import hmac
import hashlib
import logging
import json
import os

from dotenv import load_dotenv


# =====================================
# LOAD ENV
# =====================================

load_dotenv()


class KucoinTradeClient(BaseClient):

    # =====================================
    # INIT
    # =====================================

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        passphrase=None
    ):

        self.logger = logging.getLogger(__name__)

        # =====================================
        # ENV LOAD
        # =====================================

        self.api_key = (
            api_key or
            os.getenv("KUCOIN_API_KEY")
        )

        self.api_secret = (
            api_secret or
            os.getenv("KUCOIN_API_SECRET")
        )

        self.passphrase = (
            passphrase or
            os.getenv("KUCOIN_API_PASSPHRASE")
        )

        print(
            "🔑 KUCOIN KEY EXISTS:",
            bool(self.api_key)
        )

        print(
            "🔑 KUCOIN SECRET EXISTS:",
            bool(self.api_secret)
        )

        print(
            "🔑 KUCOIN PASSPHRASE EXISTS:",
            bool(self.passphrase)
        )

        if (
            not self.api_key or
            not self.api_secret or
            not self.passphrase
        ):

            raise Exception(
                "🚨 KUCOIN API KEY REQUIRED"
            )

        self.base_url = (
            "https://api-futures.kucoin.com"
        )

    # =========================
    # SYMBOL
    # =========================

    def normalize_symbol(
        self,
        symbol: str
    ) -> str:

        symbol = (
            str(symbol)
            .strip()
            .upper()
        )

        mapping = {
            "BTCUSDT": "XBTUSDTM",
            "ETHUSDT": "ETHUSDTM",
            "BNBUSDT": "BNBUSDTM",
            "SOLUSDT": "SOLUSDTM",
            "XRPUSDT": "XRPUSDTM",
        }

        mapped = mapping.get(
            symbol,
            symbol
        )

        print(
            f"[SYMBOL MAP] "
            f"'{symbol}' -> '{mapped}'"
        )

        return mapped

    # =========================
    # SIGN
    # =========================

    def _headers(
        self,
        method,
        endpoint,
        body=""
    ):

        now = str(
            int(time.time() * 1000)
        )

        str_to_sign = (
            now + method + endpoint + body
        )

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

        endpoint = (
            "/api/v1/account-overview"
            "?currency=USDT"
        )

        headers = self._headers(
            "GET",
            endpoint,
            ""
        )

        res = requests.get(
            self.base_url + endpoint,
            headers=headers
        )

        data = res.json()

        print(
            "🔥 RAW BALANCE:",
            data
        )

        if data.get("code") != "200000":

            raise Exception(
                f"KUCOIN ERROR: {data}"
            )

        d = data.get(
            "data",
            {}
        )

        balance = 0.0

        # =====================================
        # FUTURES ACCOUNT EQUITY
        # =====================================

        if "accountEquity" in d:

            balance = float(
                d.get(
                    "accountEquity",
                    0
                )
            )

        # =====================================
        # AVAILABLE BALANCE
        # =====================================

        elif "availableBalance" in d:

            balance = float(
                d.get(
                    "availableBalance",
                    0
                )
            )

        # =====================================
        # MARGIN BALANCE FALLBACK
        # =====================================

        elif "marginBalance" in d:

            balance = float(
                d.get(
                    "marginBalance",
                    0
                )
            )

        print(
            f"💰 PARSED BALANCE: {balance}"
        )

        return balance

    # =========================
    # POSITIONS
    # =========================

    def get_positions(
        self,
        symbol=None
    ):

        endpoint = "/api/v1/positions"

        headers = self._headers(
            "GET",
            endpoint
        )

        res = requests.get(
            self.base_url + endpoint,
            headers=headers
        )

        data = res.json()

        if data.get("code") != "200000":
            raise Exception(
                f"KUCOIN ERROR: {data}"
            )

        positions = data["data"]

        active = []

        for p in positions:

            size = float(
                p.get("currentQty", 0)
            )

            if size != 0:

                active.append({
                    "symbol": p["symbol"],
                    "qty": abs(size),
                    "side": (
                        "BUY"
                        if size > 0
                        else "SELL"
                    ),
                    "entry_price": float(
                        p.get(
                            "avgEntryPrice",
                            0
                        )
                    )
                })

        if symbol:

            symbol = self.normalize_symbol(symbol)

            active = [
                p for p in active
                if p["symbol"] == symbol
            ]

        return (
            active[0]
            if active
            else None
        )

    # =========================
    # PRICE
    # =========================

    def get_price(
        self,
        symbol: str
    ):

        symbol = self.normalize_symbol(symbol)

        endpoint = (
            f"/api/v1/ticker?symbol={symbol}"
        )

        res = requests.get(
            self.base_url + endpoint
        )

        data = res.json()

        return float(
            data["data"]["price"]
        )

    # =========================
    # SYMBOL RULES
    # =========================

    def get_symbol_rules(
        self,
        symbol: str
    ):

        symbol = self.normalize_symbol(symbol)

        endpoint = (
            f"/api/v1/contracts/{symbol}"
        )

        res = requests.get(
            self.base_url + endpoint
        )

        data = res.json()

        if data.get("code") != "200000":
            raise Exception(
                f"KUCOIN SYMBOL ERROR: {data}"
            )

        d = data["data"]

        rules = {
            "min_size": int(
                float(d["lotSize"])
            ),
            "multiplier": float(
                d.get(
                    "multiplier",
                    1
                )
            )
        }

        print(
            "📦 SYMBOL RULES:",
            rules
        )

        return rules

    # =========================
    # MIN QTY
    # =========================

    def get_min_qty(
        self,
        symbol
    ):

        rules = self.get_symbol_rules(symbol)

        return rules["min_size"]

    # =========================
    # QTY NORMALIZE
    # =========================

    def normalize_qty(
        self,
        symbol: str,
        qty: float
    ) -> int:

        rules = self.get_symbol_rules(symbol)

        min_size = rules["min_size"]

        qty = max(
            min_size,
            int(round(qty))
        )

        return qty

    # =========================
    # LEVERAGE
    # =========================

    def set_leverage(
        self,
        symbol: str,
        leverage: int
    ):

        symbol = self.normalize_symbol(symbol)

        endpoint = (
            "/api/v1/position/leverage"
        )

        body_dict = {
            "symbol": symbol,
            "leverage": str(leverage)
        }

        print(
            "🟣 ORDER PAYLOAD:",
            body_dict
        )

        body = json.dumps(body_dict)

        headers = self._headers(
            "POST",
            endpoint,
            body
        )

        res = requests.post(
            self.base_url + endpoint,
            headers=headers,
            data=body
        )

        data = res.json()

        if data.get("code") != "200000":

            print(
                "⚠️ LEVERAGE ERROR:",
                data
            )

        else:

            print(
                "✅ LEVERAGE SET:",
                leverage
            )

    # =========================
    # ORDER
    # =========================

    def create_order(
        self,
        symbol,
        side,
        qty,
        price=None
    ):

        print("🚀 CREATE_ORDER ENTERED")

        print(
            "🚀 CREATE_ORDER PARAMS:",
            {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price
            }
        )

        try:

            symbol = self.normalize_symbol(symbol)

            # =====================================
            # BTC QTY -> CONTRACT SIZE
            # =====================================

            rules = self.get_symbol_rules(symbol)

            multiplier = rules.get(
                "multiplier",
                1
            )

            ticker = self.get_price(symbol)

            print(
                "📈 TICKER:",
                ticker
            )

            price_now = float(ticker)

            contracts = qty / multiplier

            original_qty = qty

            # =====================================
            # MIN CONTRACT SAFETY
            # =====================================

            min_size = rules.get(
                "min_size",
                1
            )

            if contracts < min_size:

                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": (
                        f"position size below minimum "
                        f"contract size "
                        f"({contracts} < {min_size})"
                    ),
                    "timestamp": time.time(),
                }

                print(
                    "🚫 MIN CONTRACT REJECT:",
                    {
                        "contracts": contracts,
                        "min_size": min_size,
                    }
                )

                print(
                    "🟢 NORMALIZED RESULT:",
                    result
                )

                return result

            qty = int(round(contracts))

            print(
                "📦 CONTRACT CONVERT:",
                {
                    "btc_qty": original_qty,
                    "price": price_now,
                    "multiplier": multiplier,
                    "contracts": contracts,
                    "final_size": qty
                }
            )

            qty = self.normalize_qty(
                symbol,
                qty
            )

            if qty <= 0:

                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": "🚨 INVALID QTY (0)",
                    "timestamp": time.time(),
                }

                print(
                    "🟢 NORMALIZED RESULT:",
                    result
                )

                return result

            endpoint = "/api/v1/orders"

            body_dict = {
                "clientOid": str(
                    int(time.time() * 1000)
                ),
                "symbol": symbol,
                "side": side.lower(),
                "type": "market",
                "size": str(qty),
                "leverage": "10",
                "marginMode": "ISOLATED"
            }

            body = json.dumps(body_dict)

            headers = self._headers(
                "POST",
                endpoint,
                body
            )

            res = requests.post(
                self.base_url + endpoint,
                headers=headers,
                data=body
            )

            data = res.json()

            if data.get("code") != "200000":

                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": str(data),
                    "raw": data,
                    "timestamp": time.time(),
                }

                print(
                    "🟢 NORMALIZED RESULT:",
                    result
                )

                return result

            print(
                "✅ KUCOIN ORDER SUCCESS:",
                data
            )

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "order_id": (
                    data.get("data", {})
                    .get("orderId")
                ),
                "raw": data,
                "timestamp": time.time(),
            }

            print(
                "🟢 NORMALIZED RESULT:",
                result
            )

            return result

        except Exception as e:

            print(
                "❌ KUCOIN ORDER EXCEPTION:",
                e
            )

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "error": str(e),
                "timestamp": time.time(),
            }

            print(
                "🟢 NORMALIZED RESULT:",
                result
            )

            return result

            endpoint = "/api/v1/orders"

            body_dict = {
                "clientOid": str(
                    int(time.time() * 1000)
                ),
                "symbol": symbol,
                "side": side.lower(),
                "type": "market",
                "size": str(qty),
                "leverage": "10",
                "marginMode": "ISOLATED"
            }

            body = json.dumps(body_dict)

            headers = self._headers(
                "POST",
                endpoint,
                body
            )

            res = requests.post(
                self.base_url + endpoint,
                headers=headers,
                data=body
            )

            data = res.json()

            if data.get("code") != "200000":

                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": str(data),
                    "raw": data,
                    "timestamp": time.time(),
                }

                print(
                    "🟢 NORMALIZED RESULT:",
                    result
                )

                return result

            print(
                "✅ KUCOIN ORDER SUCCESS:",
                data
            )

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "order_id": (
                    data.get("data", {})
                    .get("orderId")
                ),
                "raw": data,
                "timestamp": time.time(),
            }

            print(
                "🟢 NORMALIZED RESULT:",
                result
            )

            return result

        except Exception as e:

            print(
                "❌ KUCOIN ORDER EXCEPTION:",
                e
            )

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "error": str(e),
                "timestamp": time.time(),
            }

            print(
                "🟢 NORMALIZED RESULT:",
                result
            )

            return result

    def place_order(
        self,
        symbol,
        side,
        qty,
        price=None
    ):

        return self.create_order(
            symbol,
            side,
            qty,
            price
        )

    # =========================
    # CLOSE POSITION
    # =========================

    def close_position(
        self,
        symbol
    ):

        pos = self.get_positions(symbol)

        if not pos:

            print(
                "⚠️ NO POSITION TO CLOSE"
            )

            return {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "error": "NO POSITION TO CLOSE",
                "timestamp": time.time(),
            }

        side = (
            "SELL"
            if pos["side"] == "BUY"
            else "BUY"
        )

        # =====================================
        # CONTRACT -> COIN QTY
        # =====================================

        rules = self.get_symbol_rules(symbol)

        multiplier = rules["multiplier"]

        coin_qty = (
            pos["qty"] * multiplier
        )

        print(
            "🔄 CLOSE POSITION CONVERT:",
            {
                "contracts": pos["qty"],
                "multiplier": multiplier,
                "coin_qty": coin_qty
            }
        )

        return self.create_order(
            symbol=symbol,
            side=side,
            qty=coin_qty
        )