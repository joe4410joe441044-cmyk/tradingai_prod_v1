# -*- coding: utf-8 -*-

from .base import BaseClient

import requests
from requests.adapters import HTTPAdapter
import socket
import urllib3.util.connection as _urllib3_conn
import time
import base64
import hmac
import hashlib
import json
import math
import os
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
from backend.utils.log_buffer import logger, runtime_debug
from backend.market.kucoin_futures_public import to_kucoin_futures_symbol


# =====================================
# LOAD ENV
# =====================================

load_dotenv()


class ForceIPv4Adapter(HTTPAdapter):

    def send(self, request, stream=False, timeout=None, verify=True,
             cert=None, proxies=None):

        original_allowed = _urllib3_conn.allowed_gai_family
        _urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
        try:
            return super().send(
                request,
                stream=stream,
                timeout=timeout,
                verify=verify,
                cert=cert,
                proxies=proxies,
            )
        finally:
            _urllib3_conn.allowed_gai_family = original_allowed


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

        self.session = requests.Session()
        self.session.mount("https://", ForceIPv4Adapter())
        self.session.mount("http://", ForceIPv4Adapter())

    def credentials_ready(self):

        return bool(
            self.api_key
            and self.api_secret
            and self.passphrase
        )

    def private_get(self, endpoint, *, base_url=None, timeout=10):
        """Execute one authenticated GET with the existing KuCoin signer only."""
        if not isinstance(endpoint, str) or not endpoint.startswith("/api/"):
            raise ValueError("KuCoin private GET endpoint required")
        headers = self._headers("GET", endpoint, "")
        response = self.session.get(
            (base_url or self.base_url) + endpoint,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != "200000":
            raise RuntimeError("KUCOIN_PRIVATE_GET_FAILED")
        return payload.get("data")

    def get_deposit_history(self, *, start_at, end_at, current_page=1,
                            page_size=50, currency="USDT", timeout=10):
        query = urlencode({"currency": currency, "startAt": int(start_at),
                           "endAt": int(end_at), "currentPage": int(current_page),
                           "pageSize": int(page_size)})
        return self.private_get(
            "/api/v1/deposits?" + query,
            base_url="https://api.kucoin.com", timeout=timeout,
        )

    def get_withdrawal_history(self, *, start_at, end_at, current_page=1,
                               page_size=50, currency="USDT", timeout=10):
        query = urlencode({"currency": currency, "startAt": int(start_at),
                           "endAt": int(end_at), "currentPage": int(current_page),
                           "pageSize": int(page_size)})
        return self.private_get(
            "/api/ua/v1/asset/withdrawal/history?" + query,
            base_url="https://api.kucoin.com", timeout=timeout,
        )

    def get_futures_transaction_history(self, *, start_at, end_at, offset=None,
                                        max_count=50, currency="USDT", timeout=10):
        start_at, end_at = int(start_at), int(end_at)
        if end_at < start_at or end_at - start_at > 86_400_000:
            raise ValueError("Futures transaction history range must not exceed one day")
        params = {"currency": currency, "startAt": int(start_at),
                  "endAt": int(end_at), "maxCount": int(max_count),
                  "forward": "false"}
        if offset is not None:
            params["offset"] = str(offset)
        return self.private_get(
            "/api/v1/transaction-history?" + urlencode(params), timeout=timeout,
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

        mapped = to_kucoin_futures_symbol(symbol)

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
            "KC-API-KEY-VERSION": "3",
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

        res = self.session.get(
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

        res = self.session.get(
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

    def get_position_authority_snapshot(self, timeout=10):
        """Return an explicit, timestamped shape for Live authority checks.

        The legacy ``get_positions`` API uses ``None`` for a successfully
        verified flat account.  Keep that compatibility surface unchanged,
        while preventing generic consumers from confusing that value with a
        missing or malformed response.
        """
        position = self.get_positions(timeout=timeout)
        evaluated_at = time.time()
        if position is None:
            return {"qty": 0, "evaluatedAt": evaluated_at}
        if isinstance(position, dict):
            return {**position, "evaluatedAt": evaluated_at}
        return position

    def get_current_position(
        self,
        symbol,
        timeout=10,
    ):

        raw_symbol = (
            str(symbol).strip()
            if symbol is not None
            else ""
        )
        normalized_symbol = (
            self.normalize_symbol(raw_symbol)
            if raw_symbol
            else None
        )

        def response(
            success,
            found=False,
            error_code=None,
            error=None,
            raw=None,
            raw_quantity=None,
            side=None,
            quantity=0.0,
            signed_quantity=0.0,
            entry_price=None,
        ):
            result = {
                "success": success,
                "exchange": "kucoin",
                "source": "kucoin",
                "found": found,
                "symbol": normalized_symbol,
                "exchange_symbol": normalized_symbol,
                "side": side,
                "quantity": quantity,
                "signed_quantity": signed_quantity,
                "raw_quantity": raw_quantity,
                "entry_price": entry_price,
                "raw": raw,
                "error_code": error_code,
                "error": error,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin current position result=%s", result)

            return result

        if not normalized_symbol:
            return response(
                False,
                error_code="INVALID_SYMBOL",
                error="symbol is required",
            )

        endpoint = "/api/v1/positions"

        try:
            headers = self._headers(
                "GET",
                endpoint
            )

            res = self.session.get(
                self.base_url + endpoint,
                headers=headers,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            return response(
                False,
                error_code="TIMEOUT",
                error=str(e),
            )
        except requests.exceptions.RequestException as e:
            return response(
                False,
                error_code="API_ERROR",
                error=str(e),
            )
        except Exception as e:
            return response(
                False,
                error_code="API_ERROR",
                error=str(e),
            )

        status_code = getattr(
            res,
            "status_code",
            None
        )

        try:
            status_code = (
                int(status_code)
                if status_code is not None
                else None
            )
        except (TypeError, ValueError):
            status_code = None

        if status_code in [401, 403]:
            return response(
                False,
                error_code="AUTH_ERROR",
                error=f"HTTP {status_code}",
            )

        if status_code is not None and status_code >= 400:
            return response(
                False,
                error_code="API_ERROR",
                error=f"HTTP {status_code}",
            )

        try:
            data = res.json()
        except Exception as e:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error=str(e),
            )

        if not isinstance(data, dict):
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="response is not a dict",
                raw=data,
            )

        if "code" not in data:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing code",
                raw=data,
            )

        if data.get("code") != "200000":
            return response(
                False,
                error_code="API_ERROR",
                error=str(data),
                raw=data,
            )

        if "data" not in data:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing data",
                raw=data,
            )

        positions = data.get("data")

        if not isinstance(positions, list):
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="data is not a list",
                raw=data,
            )

        if not positions:
            return response(
                True,
                found=False,
            )

        matches = []

        for item in positions:
            if not isinstance(item, dict):
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="position item is not a dict",
                    raw=item,
                )

            if "symbol" not in item:
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="missing symbol",
                    raw=item,
                )

            raw_item_symbol = item.get("symbol")

            if raw_item_symbol is None:
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="invalid symbol",
                    raw=item,
                )

            item_symbol = str(
                raw_item_symbol
            ).strip().upper()

            if not item_symbol:
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="invalid symbol",
                    raw=item,
                )

            if item_symbol == normalized_symbol:
                matches.append(item)

        if not matches:
            return response(
                True,
                found=False,
            )

        if len(matches) > 1:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="multiple positions for symbol",
                raw=matches,
            )

        position = matches[0]

        if "currentQty" not in position:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing currentQty",
                raw=position,
            )

        raw_quantity = position.get("currentQty")

        if isinstance(raw_quantity, bool):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if raw_quantity is None:
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if isinstance(raw_quantity, str) and not raw_quantity.strip():
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        try:
            signed_quantity = float(raw_quantity)
        except (TypeError, ValueError):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if not math.isfinite(signed_quantity):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if signed_quantity == 0:
            return response(
                True,
                found=False,
                raw=position,
                raw_quantity=raw_quantity,
                signed_quantity=0.0,
                quantity=0.0,
            )

        entry_price = None

        if position.get("avgEntryPrice") not in [None, ""]:
            try:
                parsed_entry = float(
                    position.get("avgEntryPrice")
                )

                if math.isfinite(parsed_entry):
                    entry_price = parsed_entry
            except (TypeError, ValueError):
                entry_price = None

        side = (
            "long"
            if signed_quantity > 0
            else "short"
        )

        return response(
            True,
            found=True,
            raw=position,
            raw_quantity=raw_quantity,
            side=side,
            quantity=abs(signed_quantity),
            signed_quantity=signed_quantity,
            entry_price=entry_price,
        )

    def flatten_current_position(
        self,
        symbol,
        timeout=10,
    ):

        def response(
            success,
            skipped=False,
            accepted=False,
            confirmed=False,
            closed=False,
            error_code=None,
            error=None,
            normalized_symbol=None,
            side=None,
            size=0,
            order_id=None,
            initial_position=None,
            final_position=None,
            raw_order=None,
        ):
            result = {
                "success": success,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "skipped": skipped,
                "accepted": accepted,
                "confirmed": confirmed,
                "closed": closed,
                "side": side,
                "size": size,
                "order_id": order_id,
                "initial_position": initial_position,
                "final_position": final_position,
                "raw_order": raw_order,
                "error_code": error_code,
                "error": error,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin flatten current position result=%s", result)

            return result

        initial = self.get_current_position(
            symbol,
            timeout=timeout,
        )

        normalized_symbol = (
            initial.get("exchange_symbol")
            or initial.get("symbol")
            if isinstance(initial, dict)
            else None
        )

        if not isinstance(initial, dict) or not initial.get("success"):
            return response(
                False,
                error_code=(
                    initial.get("error_code")
                    if isinstance(initial, dict)
                    else "POSITION_CHECK_FAILED"
                ),
                error=(
                    initial.get("error")
                    if isinstance(initial, dict)
                    else "position check failed"
                ),
                normalized_symbol=normalized_symbol,
                initial_position=initial,
            )

        if not initial.get("found"):
            return response(
                True,
                skipped=True,
                confirmed=True,
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                final_position=initial,
            )

        position_side = initial.get("side")

        if position_side == "long":
            close_side = "sell"
        elif position_side == "short":
            close_side = "buy"
        else:
            return response(
                False,
                error_code="MALFORMED_POSITION",
                error="invalid position side",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
            )

        raw_size = initial.get("quantity")

        if isinstance(raw_size, bool) or raw_size in [None, ""]:
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid position quantity",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                side=close_side,
            )

        try:
            size_value = float(raw_size)
        except (TypeError, ValueError):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid position quantity",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                side=close_side,
            )

        if (
            not math.isfinite(size_value)
            or size_value <= 0
            or not size_value.is_integer()
        ):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid position quantity",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                side=close_side,
            )

        size = int(size_value)
        endpoint = "/api/v1/orders"
        body_dict = {
            "clientOid": str(
                int(time.time() * 1000)
            ),
            "symbol": normalized_symbol,
            "side": close_side,
            "type": "market",
            "size": str(size),
            "reduceOnly": True,
            "leverage": "10",
            "marginMode": "ISOLATED",
        }
        body = json.dumps(body_dict)

        try:
            headers = self._headers(
                "POST",
                endpoint,
                body,
            )

            res = self.session.post(
                self.base_url + endpoint,
                headers=headers,
                data=body,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            return response(
                False,
                error_code="TIMEOUT",
                error=str(e),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )
        except requests.exceptions.RequestException as e:
            return response(
                False,
                error_code="API_ERROR",
                error=str(e),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )
        except Exception as e:
            return response(
                False,
                error_code="API_ERROR",
                error=str(e),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )

        status_code = getattr(
            res,
            "status_code",
            None,
        )

        try:
            status_code = (
                int(status_code)
                if status_code is not None
                else None
            )
        except (TypeError, ValueError):
            status_code = None

        if status_code in [401, 403]:
            return response(
                False,
                error_code="AUTH_ERROR",
                error=f"HTTP {status_code}",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )

        if status_code is not None and status_code >= 400:
            return response(
                False,
                error_code="API_ERROR",
                error=f"HTTP {status_code}",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )

        try:
            raw_order = res.json()
        except Exception as e:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error=str(e),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )

        if not isinstance(raw_order, dict):
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="order response is not a dict",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
                raw_order=raw_order,
            )

        if raw_order.get("code") != "200000":
            return response(
                False,
                error_code="API_ERROR",
                error=str(raw_order),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
                raw_order=raw_order,
            )

        order_data = raw_order.get("data")

        if not isinstance(order_data, dict):
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing order data",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
                raw_order=raw_order,
            )

        order_id = order_data.get("orderId")
        order_id = (
            str(order_id).strip()
            if order_id is not None
            else ""
        )

        if not order_id:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing orderId",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
                raw_order=raw_order,
            )

        final = self.get_current_position(
            normalized_symbol,
            timeout=timeout,
        )

        if not isinstance(final, dict) or not final.get("success"):
            post_error_code = (
                final.get("error_code")
                if isinstance(final, dict)
                else "FAILED"
            )

            return response(
                False,
                accepted=True,
                confirmed=False,
                error_code=f"POST_CHECK_{post_error_code or 'FAILED'}",
                error=(
                    final.get("error")
                    if isinstance(final, dict)
                    else "post-check failed"
                ),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                order_id=order_id,
                initial_position=initial,
                final_position=final,
                raw_order=raw_order,
            )

        if final.get("found"):
            return response(
                False,
                accepted=True,
                confirmed=False,
                error_code="POSITION_REMAINS",
                error="position remains after flatten order",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                order_id=order_id,
                initial_position=initial,
                final_position=final,
                raw_order=raw_order,
            )

        return response(
            True,
            accepted=True,
            confirmed=True,
            closed=True,
            normalized_symbol=normalized_symbol,
            side=close_side,
            size=size,
            order_id=order_id,
            initial_position=initial,
            final_position=final,
            raw_order=raw_order,
        )

    # =========================
    # PRICE
    # =========================

    def get_open_orders(
        self,
        symbol=None
    ):

        normalized_symbol = (
            self.normalize_symbol(symbol)
            if symbol
            else None
        )
        orders = []
        raw_pages = []
        current_page = 1
        total_page = 1
        page_size = 100

        try:

            while current_page <= total_page:

                params = {
                    "status": "active",
                    "currentPage": current_page,
                    "pageSize": page_size,
                }

                if normalized_symbol:
                    params["symbol"] = normalized_symbol

                endpoint = (
                    "/api/v1/orders?"
                    + urlencode(params)
                )

                headers = self._headers(
                    "GET",
                    endpoint
                )

                res = self.session.get(
                    self.base_url + endpoint,
                    headers=headers,
                    timeout=10,
                )

                data = res.json()
                raw_pages.append(data)

                if data.get("code") != "200000":
                    return {
                        "success": False,
                        "exchange": "kucoin",
                        "symbol": normalized_symbol,
                        "orders": [],
                        "count": 0,
                        "error": str(data),
                        "raw": data,
                        "timestamp": time.time(),
                    }

                payload = data.get(
                    "data",
                    {}
                )
                items = (
                    payload
                    if isinstance(payload, list)
                    else payload.get("items", [])
                )

                for item in items or []:
                    orders.append(
                        self._normalize_open_order(
                            item
                        )
                    )

                if not isinstance(payload, dict):
                    break

                total_page = int(
                    payload.get("totalPage")
                    or payload.get("total_page")
                    or current_page
                    or 1
                )
                current_page = int(
                    payload.get("currentPage")
                    or payload.get("current_page")
                    or current_page
                    or 1
                )

                if current_page >= total_page:
                    break

                current_page += 1

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "orders": orders,
                "count": len(orders),
                "raw": (
                    raw_pages[0]
                    if len(raw_pages) == 1
                    else {"pages": raw_pages}
                ),
                "pagination": {
                    "pagesFetched": len(raw_pages),
                    "pageSize": page_size,
                    "totalPage": total_page,
                },
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin open orders result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN OPEN ORDERS EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "orders": [],
                "count": 0,
                "error": str(e),
                "raw": (
                    raw_pages[-1]
                    if raw_pages
                    else None
                ),
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin open orders result=%s", result)

            return result

    @staticmethod
    def _normalize_open_order(order):

        def as_float(value):
            if value in [None, ""]:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        side = order.get("side")

        return {
            "order_id": (
                order.get("id")
                or order.get("orderId")
            ),
            "symbol": order.get("symbol"),
            "side": (
                str(side).upper()
                if side
                else None
            ),
            "type": (
                order.get("type")
                or order.get("orderType")
            ),
            "price": as_float(order.get("price")),
            "size": as_float(
                order.get("size")
                or order.get("qty")
            ),
            "status": order.get("status"),
            "raw": order,
        }

    def cancel_order(
        self,
        order_id,
        symbol=None
    ):

        normalized_symbol = (
            self.normalize_symbol(symbol)
            if symbol
            else None
        )
        normalized_order_id = (
            str(order_id).strip()
            if order_id is not None
            else ""
        )

        if not normalized_order_id:

            result = {
                "success": False,
                "exchange": "kucoin",
                "order_id": None,
                "symbol": normalized_symbol,
                "cancelled": False,
                "error": "INVALID_ORDER_ID",
                "raw": None,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel order result=%s", result)

            return result

        endpoint = (
            "/api/v1/orders/"
            + quote(normalized_order_id, safe="")
        )
        raw = None

        try:

            headers = self._headers(
                "DELETE",
                endpoint
            )

            res = self.session.delete(
                self.base_url + endpoint,
                headers=headers,
                timeout=10,
            )

            raw = res.json()

            if raw.get("code") != "200000":
                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "order_id": normalized_order_id,
                    "symbol": normalized_symbol,
                    "cancelled": False,
                    "error": str(raw),
                    "raw": raw,
                    "timestamp": time.time(),
                }

                runtime_debug("KuCoin cancel order result=%s", result)

                return result

            result = {
                "success": True,
                "exchange": "kucoin",
                "order_id": normalized_order_id,
                "symbol": normalized_symbol,
                "cancelled": True,
                "raw": raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel order result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN CANCEL ORDER EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "order_id": normalized_order_id,
                "symbol": normalized_symbol,
                "cancelled": False,
                "error": str(e),
                "raw": raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel order result=%s", result)

            return result

    def cancel_all_orders(
        self,
        symbol
    ):

        raw_symbol = (
            str(symbol).strip()
            if symbol is not None
            else ""
        )

        if not raw_symbol:

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": None,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": False,
                "results": [],
                "error": "INVALID_SYMBOL",
                "open_orders_raw": None,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        normalized_symbol = self.normalize_symbol(raw_symbol)

        try:
            open_result = self.get_open_orders(normalized_symbol)
        except Exception as e:
            self.logger.exception("KUCOIN CANCEL ALL OPEN ORDERS EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": False,
                "results": [],
                "error": str(e),
                "open_orders_raw": None,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        open_orders_raw = (
            open_result.get("raw")
            if isinstance(open_result, dict)
            else open_result
        )

        if not isinstance(open_result, dict) or not open_result.get("success"):

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": False,
                "results": [],
                "error": (
                    open_result.get("error")
                    if isinstance(open_result, dict)
                    else "OPEN_ORDERS_FAILED"
                ),
                "open_orders_raw": open_orders_raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        orders = (
            open_result.get("orders")
            or []
        )

        if not orders:

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": True,
                "results": [],
                "error": None,
                "open_orders_raw": open_orders_raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        results = []
        cancelled = 0
        failed = 0

        for order in orders:

            order_id = None

            try:
                if isinstance(order, dict):
                    order_id = (
                        order.get("order_id")
                        or order.get("id")
                        or order.get("orderId")
                    )

                order_id = (
                    str(order_id).strip()
                    if order_id is not None
                    else ""
                )

                if not order_id:
                    failed += 1
                    results.append({
                        "order_id": None,
                        "success": False,
                        "cancelled": False,
                        "error": "MISSING_ORDER_ID",
                        "raw": order,
                    })
                    continue

                try:
                    cancel_result = self.cancel_order(
                        order_id,
                        normalized_symbol
                    )
                except Exception as e:
                    self.logger.exception("KUCOIN CANCEL ALL ITEM EXCEPTION")
                    cancel_result = {
                        "success": False,
                        "order_id": order_id,
                        "cancelled": False,
                        "error": str(e),
                        "raw": None,
                    }

                item_cancelled = bool(
                    cancel_result.get("success")
                    and cancel_result.get("cancelled")
                )

                if item_cancelled:
                    cancelled += 1
                else:
                    failed += 1

                results.append({
                    "order_id": (
                        cancel_result.get("order_id")
                        or order_id
                    ),
                    "success": bool(cancel_result.get("success")),
                    "cancelled": bool(cancel_result.get("cancelled")),
                    "error": cancel_result.get("error"),
                    "raw": cancel_result.get("raw"),
                })

            except Exception as e:
                failed += 1
                results.append({
                    "order_id": order_id,
                    "success": False,
                    "cancelled": False,
                    "error": str(e),
                    "raw": order,
                })

        result = {
            "success": failed == 0,
            "exchange": "kucoin",
            "symbol": normalized_symbol,
            "requested": len(orders),
            "cancelled": cancelled,
            "failed": failed,
            "skipped": False,
            "results": results,
            "error": (
                None
                if failed == 0
                else "CANCEL_ALL_PARTIAL_FAILURE"
            ),
            "open_orders_raw": open_orders_raw,
            "timestamp": time.time(),
        }

        runtime_debug("KuCoin cancel all orders result=%s", result)

        return result

    def get_price(
        self,
        symbol: str
    ):

        symbol = self.normalize_symbol(symbol)

        endpoint = (
            f"/api/v1/ticker?symbol={symbol}"
        )

        res = self.session.get(
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

        res = self.session.get(
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

        res = self.session.post(
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

            res = self.session.post(
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

            res = self.session.post(
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
