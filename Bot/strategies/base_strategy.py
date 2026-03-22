from utils.logger import BotLogger


class BaseStrategy:
    """
    全戦略共通の基盤
    TradeCore, Logger, Notifier を保持
    on_bar() は各戦略でオーバーライド
    """

    def __init__(self, trade_core, logger=None, notifier=None):
        self.trade_core = trade_core

        # 🔥 logger統一（なければ自動生成）
        self.logger = logger if logger else BotLogger().get_logger()

        # 🔥 notifierは任意（本番のみ使用）
        self.notifier = notifier

    def on_bar(self, market_data: dict):
        """
        MarketEngine から渡される最新データを受け取る
        各戦略でオーバーライドして処理
        """
        raise NotImplementedError