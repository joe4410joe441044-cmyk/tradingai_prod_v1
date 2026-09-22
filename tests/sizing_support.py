"""Explicit offline sizing authorities for execution integration fixtures."""
import time
from unittest.mock import Mock
from backend.money_management.loss_application_registration import build_default_money_management_config
from backend.market.kucoin_futures_public import to_kucoin_futures_symbol


def contract_rules(symbol, multiplier=0.001):
    return {"symbol": to_kucoin_futures_symbol(symbol), "status": "Open", "isInverse": False,
            "settle_currency": "USDT", "quote_currency": "USDT", "multiplier": multiplier, "min_size": 1, "qty_step": 1,
            "max_size": 1000000, "max_leverage": 75, "taker_fee_rate": 0}


def account(equity=1000):
    return {"source": "KUCOIN_FUTURES_READ_ONLY", "lastSync": time.time(),
            "currency": "USDT", "equity": equity, "availableBalance": equity, "positionMargin": 0, "orderMargin": 0}


def install_sizing(engine):
    engine.sizing_policy_provider = build_default_money_management_config
    engine.sizing_contract_provider = contract_rules
    if engine.exchange is not None:
        if isinstance(engine.exchange, Mock):
            engine.exchange.get_account_overview.return_value = account()
            engine.exchange.get_symbol_rules.return_value = contract_rules(engine.symbol)
        else:
            engine.exchange.get_account_overview = lambda: account()
            engine.exchange.get_symbol_rules = contract_rules
