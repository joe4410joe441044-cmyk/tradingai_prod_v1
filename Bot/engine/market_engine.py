from typing import List
from strategies.base_strategy import BaseStrategy
from market.candle_buffer import CandleBuffer
from utils.multi_timeframe_manager import MultiTimeFrameManager


class MarketEngine:
    """
    MarketEngine（本番用／ダミーデータ兼用）
    - CandleBuffer更新
    - MultiTimeFrameManagerで任意時間足生成
    - 戦略に on_bar データを渡す
    """

    def __init__(self, strategies: List[BaseStrategy], debug: bool = True):
        self.strategies = strategies
        self.debug = debug

        # 生足バッファ
        self.candle_buffer = CandleBuffer()

        # マルチタイムフレーム管理（1分足ベース）
        self.mtf_manager = MultiTimeFrameManager(base_timeframe="1m")

        # 対応時間足
        self.timeframes = ["M15", "H1", "H4"]

    def process_data(self, data: dict):
        """
        WSやダミーデータを受け取り
        CandleBuffer と MTFManager を更新して戦略に渡す
        data フォーマット例:
        {
            "symbol": "BTCUSDT",
            "time": 1679452800000,
            "open": 30000,
            "high": 30100,
            "low": 29950,
            "close": 30050,
            "volume": 12.34
        }
        """

        # 受信データを既存形式に合わせて整理
        candle = {
            "time": data.get("time"),
            "open": float(data.get("open", 0)),
            "high": float(data.get("high", 0)),
            "low": float(data.get("low", 0)),
            "close": float(data.get("close", 0)),
            "volume": float(data.get("volume", 0))
        }

        if self.debug:
            print(f"[MarketEngine] New candle: {candle}")

        # CandleBuffer に追加
        self.candle_buffer.add_candle(candle)

        # MultiTimeFrameManager を更新
        self.mtf_manager.update_candle(
            symbol=data.get("symbol", "BTCUSDT"),
            candle=candle
        )

        # 各時間足を取得して戦略に渡す
        market_data = self.mtf_manager.get_all_timeframes(
            symbol=data.get("symbol", "BTCUSDT"),
            timeframes=self.timeframes
        )
        market_data["symbol"] = data.get("symbol", "BTCUSDT")

        # 戦略にデータを渡す（既存構造維持）
        for strategy in self.strategies:
            strategy.on_bar(market_data)