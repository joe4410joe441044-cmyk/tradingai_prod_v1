# -*- coding: utf-8 -*-
from utils.logger import BotLogger


class BaseStrategy:
    """
    蜈ｨ謌ｦ逡･蜈ｱ騾壹・蝓ｺ逶､
    TradeCore, Logger, Notifier 繧剃ｿ晄戟
    on_bar() 縺ｯ蜷・姶逡･縺ｧ繧ｪ繝ｼ繝舌・繝ｩ繧､繝・
    """

    def __init__(self, trade_core, logger=None, notifier=None):
        self.trade_core = trade_core

        # 櫨 logger邨ｱ荳・医↑縺代ｌ縺ｰ閾ｪ蜍慕函謌撰ｼ・
        self.logger = logger if logger else BotLogger().get_logger()

        # 櫨 notifier縺ｯ莉ｻ諢擾ｼ域悽逡ｪ縺ｮ縺ｿ菴ｿ逕ｨ・・
        self.notifier = notifier

    def on_bar(self, market_data: dict):
        """
        MarketEngine 縺九ｉ貂｡縺輔ｌ繧区怙譁ｰ繝・・繧ｿ繧貞女縺大叙繧・
        蜷・姶逡･縺ｧ繧ｪ繝ｼ繝舌・繝ｩ繧､繝峨＠縺ｦ蜃ｦ逅・
        """
        raise NotImplementedError
