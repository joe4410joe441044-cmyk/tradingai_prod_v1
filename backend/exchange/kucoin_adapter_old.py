# -*- coding: utf-8 -*-

from typing import List, Dict
import os

from dotenv import load_dotenv
from kucoin.client import User, Trade, Market

from Bot.exchanges.base_exchange import BaseExchange

load_dotenv()


class KuCoinExchange(BaseExchange):

    def __init__(self):
        self.user = User(
            key=os.getenv("KUCOIN_API_KEY"),
            secret=os.getenv("KUCOIN_API_SECRET"),
            passphrase=os.getenv("KUCOIN_API_PASSPHRASE")
        )

        self.trade = Trade(
            key=os.getenv("KUCOIN_API_KEY"),
            secret=os.getenv("KUCOIN_API_SECRET"),
            passphrase=os.getenv("KUCOIN_API_PASSPHRASE")
        )

        self.market = Market()

    # =========================
    # Positions
    # =========================
    def get_positions(self) -> List[Dict]:
        return []

    # =========================
    # Balance（🔥修正）
    # =========================
    def get_balance(self, currency: str = "USDT") -> float:
        try:
            accounts = self.user.get_account_list()

            for acc in accounts:
                if acc["currency"] == currency and acc["type"] == "trade":
                    return float(acc["balance"])

            return 0.0

        except Exception as e:
            print("[KUCOIN BALANCE ERROR]", e)
            return 0.0

    # =========================
    # PnL
    # =========================
    def get_pnl(self) -> float:
        return 0.0

    # =========================
    # Price
    # =========================
    def get_price(self, symbol: str) -> float:
        try:
            ticker = self.market.get_ticker(symbol)
            return float(ticker["price"])
        except Exception:
            return 0.0

    # =========================
    # Order
    # =========================
    def create_order(self, symbol: str, side: str, size: float):

        try:
            side_conv = "buy" if side == "LONG" else "sell"

            return self.trade.create_market_order(
                symbol=symbol,
                side=side_conv,
                size=str(size)
            )

        except Exception as e:
            print("[KUCOIN ORDER ERROR]", e)
            return None

    def close_position(self, symbol: str):
        return None