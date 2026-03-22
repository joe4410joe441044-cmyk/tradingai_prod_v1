import pandas as pd
from core.trade_core import TradeCore
from utils.logger import BotLogger
class BaseStrategy:
    """
    全戦略共通の基盤
    TradeCore, Logger, Notifier を保持
    on_bar() は各戦略でオーバーライド
    """
    def __init__(self, trade_core, logger, notifier):
        self.trade_core = trade_core
        self.logger = logger
        self.notifier = notifier

    def on_bar(self, market_data: dict):
        """
        MarketEngine から渡される最新データを受け取る
        各戦略でオーバーライドして処理
        """
        raise NotImplementedError
