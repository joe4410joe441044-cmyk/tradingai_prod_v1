import requests
import time
import hmac
import hashlib
import json
from typing import Dict, List, Any

from exchanges.base_exchange import BaseExchange
from bybit_config import BybitConfig
from safe_mode import SafeModeController


class BybitClient(BaseExchange):

    def __init__(self):
        self.api_key = BybitConfig.API_KEY
        self.api_secret = BybitConfig.API_SECRET
        self.base_url = BybitConfig.BASE_URL
        self.market_type = BybitConfig.MARKET_TYPE
        self.safe_mode = SafeModeController(BybitConfig.SAFE_MODE)
        self.recv_window = "5000"

    # ---------------------------------
    # 鄂ｲ蜷咲函謌・
    # ---------------------------------
    def _generate_signature(self, timestamp: str, payload: str) -> str:
        param_str = timestamp + self.api_key + self.recv_window + payload
        return hmac.new(
            bytes(self.api_secret, "utf-8"),
            bytes(param_str, "utf-8"),
            hashlib.sha256
        ).hexdigest()

    # ---------------------------------
    # 繝倥ャ繝繝ｼ逕滓・
    # ---------------------------------
    def _get_headers(self, payload: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        sign = self._generate_signature(timestamp, payload)

        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "Content-Type": "application/json"
        }

    # ---------------------------------
    # 謗･邯夂｢ｺ隱・
    # ---------------------------------
    def connect(self) -> None:
        balance = self.get_balance()
        print("Bybit謗･邯壽・蜉・", balance)

    # ---------------------------------
    # 谿矩ｫ伜叙蠕・
    # ---------------------------------
    def get_balance(self) -> Dict[str, Any]:

        endpoint = "/v5/account/wallet-balance"
        params = f"accountType=UNIFIED"

        headers = self._get_headers(params)

        response = requests.get(
            self.base_url + endpoint + "?" + params,
            headers=headers
        )

        return response.json()

    # ---------------------------------
    # 繝昴ず繧ｷ繝ｧ繝ｳ蜿門ｾ・
    # ---------------------------------
    def get_positions(self) -> List[Dict[str, Any]]:

        if self.market_type == "linear":
            endpoint = "/v5/position/list"
            params = f"category=linear"

            headers = self._get_headers(params)

            response = requests.get(
                self.base_url + endpoint + "?" + params,
                headers=headers
            )

            return response.json()

        else:
            return []

    # ---------------------------------
    # 迴ｾ蝨ｨ萓｡譬ｼ蜿門ｾ暦ｼ亥・髢帰PI・・
    # ---------------------------------
    def get_price(self, symbol: str) -> float:

        endpoint = "/v5/market/tickers"
        url = f"{self.base_url}{endpoint}?category={self.market_type}&symbol={symbol}"

        response = requests.get(url)
        data = response.json()

        return float(data["result"]["list"][0]["lastPrice"])

    # ---------------------------------
    # 豕ｨ譁・ｼ・AFE_MODE莉倥″・・
    # ---------------------------------
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "Market",
        stop_loss: float = None,
        take_profit: float = None
    ) -> Dict[str, Any]:

        self.safe_mode.validate_order()

        endpoint = "/v5/order/create"

        payload = {
            "category": self.market_type,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(quantity),
            "timeInForce": "IOC"
        }

        payload_str = json.dumps(payload)
        headers = self._get_headers(payload_str)

        response = requests.post(
            self.base_url + endpoint,
            headers=headers,
            data=payload_str
        )

        return response.json()

    # ---------------------------------
    # 繧ｭ繝｣繝ｳ繧ｻ繝ｫ
    # ---------------------------------
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:

        self.safe_mode.validate_order()

        endpoint = "/v5/order/cancel"

        payload = {
            "category": self.market_type,
            "symbol": symbol,
            "orderId": order_id
        }

        payload_str = json.dumps(payload)
        headers = self._get_headers(payload_str)

        response = requests.post(
            self.base_url + endpoint,
            headers=headers,
            data=payload_str
        )

        return response.json()

    # ---------------------------------
    # 繝昴ず繧ｷ繝ｧ繝ｳ繧ｯ繝ｭ繝ｼ繧ｺ
    # ---------------------------------
    def close_position(self, symbol: str) -> Dict[str, Any]:
        self.safe_mode.validate_order()
        return {"status": "close_called"}
