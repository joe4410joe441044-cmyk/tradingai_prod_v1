# -*- coding: utf-8 -*-

from .base import BaseClient

import requests
import time
import base64
import hmac
import hashlib
import json
import os

from dotenv import load_dotenv
from backend.utils.log_buffer import logger, runtime_debug


# =====================================
# LOAD ENV
# =====================================

load_dotenv()


class KucoinTradeClient(BaseClient):

    @staticmethod
    def credentials_present(
        api_key=None,
        api_secret=None,
        passphrase=None
    ):

        return bool(
            (api_key or os.getenv("KUCOIN_API_KEY"))
            and (api_secret or os.getenv("KUCOIN_API_SECRET"))
            and (passphrase or os.getenv("KUCOIN_API_PASSPHRASE"))
        )

    # =====================================
    # INIT
    # =====================================

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        passphrase=None
    ):

        self.logger = logger

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

        self.live_order_allowed = False

        self.live_block_reasons = [
            "LIVE_NOT_READY"
        ]

        runtime_debug(
            "KuCoin credentials configured key=%s secret=%s passphrase=%s",
            bool(self.api_key),
            bool(self.api_secret),
            bool(self.passphrase),
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

    def credentials_ready(self):

        return bool(
            self.api_key
            and self.api_secret
            and self.passphrase
        )

    def set_live_order_gate(
        self,
        allowed,
        reasons=None
    ):

        self.live_order_allowed = bool(allowed)
        self.live_block_reasons = list(
            reasons
            or (
                []
                if allowed
                else ["LIVE_NOT_READY"]
            )
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

        runtime_debug(
            "KuCoin trade symbol map '%s' -> '%s'",
            symbol,
            mapped,
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

        overview = self.get_account_overview()

        balance = overview.get("balance")

        runtime_debug("KuCoin parsed balance=%s", balance)

        return float(balance or 0.0)

    def get_account_overview(
        self,
        currency="USDT",
        timeout=10,
    ):

        endpoint = (
            "/api/v1/account-overview"
            f"?currency={currency}"
        )

        headers = self._headers(
            "GET",
            endpoint,
            ""
        )

        res = requests.get(
            self.base_url + endpoint,
            headers=headers,
            timeout=timeout,
        )

        data = res.json()

        runtime_debug("KuCoin raw balance response=%s", data)

        if data.get("code") != "200000":

            raise Exception(
                f"KUCOIN ERROR: {data}"
            )

        d = data.get(
            "data",
            {}
        )

        def as_float(*keys):
            for key in keys:
                if key in d and d.get(key) not in [None, ""]:
                    return float(d.get(key, 0) or 0)
            return None

        # =====================================
        # FUTURES ACCOUNT EQUITY
        # =====================================

        equity = as_float(
            "accountEquity",
            "marginBalance",
            "balance",
        )

        # =====================================
        # AVAILABLE BALANCE
        # =====================================

        available_balance = as_float(
            "availableBalance",
            "available_balance",
        )

        # =====================================
        # MARGIN BALANCE FALLBACK
        # =====================================

        margin_balance = as_float(
            "marginBalance",
            "balance",
            "accountEquity",
        )
        unrealized_pnl = as_float(
            "unrealisedPNL",
            "unrealizedPnl",
            "unrealisedPnl",
            "unrealizedPNL",
        )
        balance = (
            equity
            if equity is not None
            else (
                margin_balance
                if margin_balance is not None
                else available_balance
            )
        )

        overview = {
            "source": "KUCOIN_FUTURES_READ_ONLY",
            "accountType": "KUCOIN_FUTURES",
            "currency": d.get("currency", currency),
            "balance": (
                float(balance)
                if balance is not None
                else None
            ),
            "equity": (
                float(equity)
                if equity is not None
                else (
                    float(balance)
                    if balance is not None
                    else None
                )
            ),
            "availableBalance": (
                float(available_balance)
                if available_balance is not None
                else None
            ),
            "marginBalance": (
                float(margin_balance)
                if margin_balance is not None
                else None
            ),
            "unrealizedPnl": (
                float(unrealized_pnl)
                if unrealized_pnl is not None
                else None
            ),
            "exchangeAuth": "VERIFIED",
            "exchangeConnection": "CONNECTED",
            "apiKeyStatus": "VERIFIED",
            "permission": "READ_ONLY",
            "lastSync": time.time(),
        }

        runtime_debug("KuCoin parsed account overview=%s", overview)

        return overview

    # =========================
    # POSITIONS
    # =========================

    def get_positions(
        self,
        symbol=None,
        timeout=10,
    ):

        endpoint = "/api/v1/positions"

        headers = self._headers(
            "GET",
            endpoint
        )

        res = requests.get(
            self.base_url + endpoint,
            headers=headers,
            timeout=timeout,
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

        runtime_debug("KuCoin symbol rules=%s", rules)

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

        runtime_debug("KuCoin leverage payload=%s", body_dict)

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

            self.logger.error("KuCoin leverage error: %s", data)

        else:

            self.logger.info("KuCoin leverage set=%s", leverage)

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

        if not self.live_order_allowed:

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "blockedReason": "LIVE_NOT_READY",
                "liveBlockReasons": list(
                    self.live_block_reasons
                    or ["LIVE_NOT_READY"]
                ),
                "error": "LIVE_NOT_READY",
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin order blocked result=%s", result)

            return result

        runtime_debug(
            "KuCoin create order symbol=%s side=%s qty=%s price=%s",
            symbol,
            side,
            qty,
            price,
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

            runtime_debug("KuCoin order ticker=%s", ticker)

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

                self.logger.warning(
                    "ORDER REJECTED: below minimum contracts=%s min_size=%s",
                    contracts,
                    min_size,
                )

                runtime_debug("KuCoin normalized result=%s", result)

                return result

            qty = int(round(contracts))

            runtime_debug(
                "KuCoin contract conversion coin_qty=%s price=%s "
                "multiplier=%s contracts=%s final_size=%s",
                original_qty,
                price_now,
                multiplier,
                contracts,
                qty,
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

                runtime_debug("KuCoin normalized result=%s", result)

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

                runtime_debug("KuCoin normalized result=%s", result)

                return result

            self.logger.info("ORDER SENT: KuCoin response=%s", data)

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

            runtime_debug("KuCoin normalized result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN ORDER EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "error": str(e),
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin normalized result=%s", result)

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

                runtime_debug("KuCoin normalized result=%s", result)

                return result

            self.logger.info("ORDER SENT: KuCoin response=%s", data)

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

            runtime_debug("KuCoin normalized result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN ORDER EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "error": str(e),
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin normalized result=%s", result)

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

            runtime_debug("KuCoin close skipped: no position")

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

        runtime_debug(
            "KuCoin close conversion contracts=%s multiplier=%s coin_qty=%s",
            pos["qty"],
            multiplier,
            coin_qty,
        )

        return self.create_order(
            symbol=symbol,
            side=side,
            qty=coin_qty
        )
