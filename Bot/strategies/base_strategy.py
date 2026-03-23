# -*- coding: utf-8 -*-
from Bot.utils.logger import BotLogger


class BaseStrategy:
    """
    E
    TradeCore, Logger, Notifier 
    on_bar() EEE
    """

    def __init__(self, trade_core, logger=None, notifier=None):
        self.trade_core = trade_core

        #  loggerEE
        self.logger = logger if logger else BotLogger().get_logger()

        #  notifierEE
        self.notifier = notifier

    def on_bar(self, market_data: dict):
        """
        MarketEngine EEE
        EEE
        """
        raise NotImplementedError