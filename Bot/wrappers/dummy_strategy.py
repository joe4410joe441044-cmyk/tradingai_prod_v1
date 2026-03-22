
from strategies.base_strategy import BaseStrategy
class DummyStrategy:
    """
    MarketEngineチE��ト用のダミ�EストラチE��ー
    on_bar() で受け取ったローソク足を表示するだぁE
    """
    def on_bar(self, candle):
        print(f"[DummyStrategy] Received candle: {candle}")
