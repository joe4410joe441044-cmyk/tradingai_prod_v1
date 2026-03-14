# Bot/strategies/fvg_strategy.py
from typing import List
from Bot.core.trade_core import TradeCore
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier

class FVGStrategy:
    """
    本番用 FVGStrategy
    初期シグナル生成ロジックを含む
    """
    def __init__(self, trade_core: TradeCore, logger: BotLogger = None, notifier: TelegramNotifier = None):
        self.trade_core = trade_core
        self.logger = logger
        self.notifier = notifier
        self.active_positions = []

        self.logger and self.logger.info("FVGStrategy initialized.")

    def scan_market(self, market_data) -> List[dict]:
        """
        市場データを解析してトレードシグナルを生成
        market_data: dict with keys 'open', 'high', 'low', 'close'
        """
        signals = []

        # === 簡易 FVG ロジック ===
        # 前の足とのギャップでシグナル
        # bullish: 現在のローソク足の高値 > 前足の終値 + 閾値
        # bearish: 現在のローソク足の安値 < 前足の終値 - 閾値
        GAP_THRESHOLD = 0.5  # USD単位の簡易閾値（必要に応じ調整）

        prev_close = market_data.get('prev_close')
        curr_open = market_data.get('open')
        curr_high = market_data.get('high')
        curr_low = market_data.get('low')
        curr_close = market_data.get('close')

        if prev_close is not None:
            # Bullish FVG シグナル
            if curr_low > prev_close + GAP_THRESHOLD:
                signals.append({
                    'type': 'buy',
                    'price': curr_close,
                    'volume': 0.1,  # 本番は適切な数量に調整
                    'sl': curr_low - GAP_THRESHOLD,
                    'tp': curr_close + GAP_THRESHOLD*2
                })

            # Bearish FVG シグナル
            elif curr_high < prev_close - GAP_THRESHOLD:
                signals.append({
                    'type': 'sell',
                    'price': curr_close,
                    'volume': 0.1,
                    'sl': curr_high + GAP_THRESHOLD,
                    'tp': curr_close - GAP_THRESHOLD*2
                })

        if signals:
            self.logger and self.logger.info(f"FVGStrategy signals: {signals}")
            self.notifier and self.notifier.send(f"FVGStrategy signals: {signals}")

        return signals

    def execute_signals(self, signals: List[dict]):
        """
        TradeCore 経由でポジションをオープン
        """
        for sig in signals:
            try:
                self.trade_core.open_position(
                    trade_type=sig['type'],
                    price=sig['price'],
                    volume=sig['volume'],
                    sl=sig.get('sl'),
                    tp=sig.get('tp')
                )
                self.active_positions.append(sig)
                self.logger and self.logger.info(f"Executed signal: {sig}")
            except Exception as e:
                self.logger and self.logger.error(f"Failed to execute signal: {sig}, error: {e}")
                self.notifier and self.notifier.send(f"Failed to execute signal: {sig}, error: {e}")

    def update(self, market_data):
        """
        MarketEngine ループから定期的に呼ばれる
        """
        signals = self.scan_market(market_data)
        if signals:
            self.execute_signals(signals)