
from strategies.base_strategy import BaseStrategy
class DummyStrategy:
    """
    MarketEngineテスト用のダミーストラテジー
    on_bar() で受け取ったローソク足を表示するだけ
    """
    def on_bar(self, candle):
        print(f"[DummyStrategy] Received candle: {candle}")