# Bot/strategies/fvg_strategy.py

import pandas as pd
from typing import List
from strategies.base_strategy import BaseStrategy
from core.trade_core import TradeCore
from utils.logger import BotLogger
from utils.telegram_notifier import TelegramNotifier


class FVG:
    def __init__(self, top: float, bottom: float, bullish: bool, timeframe: str):
        self.top = top
        self.bottom = bottom
        self.bullish = bullish
        self.used = False
        self.timeframe = timeframe


class FVGStrategy(BaseStrategy):
    """
    単一戦略：FVG検出・シグナル生成
    BaseStrategy を継承して共通部分は親に任せる
    """

    def __init__(self, trade_core: TradeCore,
                 m15: pd.DataFrame = pd.DataFrame(),
                 h1: pd.DataFrame = pd.DataFrame(),
                 h4: pd.DataFrame = pd.DataFrame(),
                 logger: BotLogger = None,
                 notifier: TelegramNotifier = None):
        # 共通部分は BaseStrategy に任せる
        super().__init__(trade_core, logger, notifier)

        # タイムフレームごとのデータ
        self.m15 = m15
        self.h1 = h1
        self.h4 = h4

        # FVGリスト
        self.fvg_list: List[FVG] = []

        # 設定パラメータ
        self.tap_threshold = 0.3
        self.require_engulfing = True

        self.logger and self.logger.info("FVGStrategy initialized.")

    # --------------------------
    # MarketEngineから呼ばれる入口
    # --------------------------
    def on_bar(self, market_data):
        """
        MarketEngineから最新データを受け取り、
        Execution形式でシグナルを返す
        """
        # データ更新
        for tf in ["M15", "H1", "H4"]:
            if tf in market_data and not market_data[tf].empty:
                setattr(self, tf.lower(), market_data[tf])

        # FVG検出
        self.detect_fvg()

        # シグナル生成
        signals = self.generate_signals()
        if not signals:
            return None

        # Execution形式に変換して返す（TradeCoreに渡す）
        sig = signals[0]  # とりあえず1つだけ
        signal_exec = {
            "action": "BUY" if sig["trade_type"] == "buy" else "SELL",
            "symbol": market_data.get("symbol", "BTCUSDT"),
            "price": sig["entry_price"],
            "sl": sig["stop_loss_price"],
            "tp": sig["take_profit_price"],
            "size": 0.001  # 固定サイズ。必要ならvolume対応
        }

        # ログ・通知
        self.logger and self.logger.info(f"FVGStrategy signal: {signal_exec}")
        self.notifier and self.notifier.send(f"FVGStrategy signal: {signal_exec}")

        return signal_exec

    # --------------------------
    # FVG検出
    # --------------------------
    def detect_fvg(self):
        self._add_fvg(self.m15, "M15")
        self._add_fvg(self.h1, "H1")
        self._add_fvg(self.h4, "H4")

    def _add_fvg(self, df: pd.DataFrame, tf: str):
        if len(df) < 3:
            return
        high2 = df['High'].iloc[-3]
        low2 = df['Low'].iloc[-3]
        high0 = df['High'].iloc[-1]
        low0 = df['Low'].iloc[-1]
        if low2 > high0:
            self._add_or_merge_fvg(low2, high0, False, tf)
        if high2 < low0:
            self._add_or_merge_fvg(low0, high2, True, tf)

    def _add_or_merge_fvg(self, top, bottom, bullish, tf):
        for f in self.fvg_list:
            if f.top == top and f.bottom == bottom and f.timeframe == tf:
                return
        self.fvg_list.append(FVG(top, bottom, bullish, tf))

    # --------------------------
    # シグナル生成
    # --------------------------
    def generate_signals(self):
        """
        StrategyContext相当のdictリストで返す
        """
        signals = []
        for fvg in self.fvg_list:
            if fvg.timeframe != "M15" or fvg.used:
                continue
            # シンプルに中心価格でエントリー
            center = (fvg.top + fvg.bottom) / 2
            signal = {
                "strategy_name": "FVG",
                "trade_type": "buy" if fvg.bullish else "sell",
                "entry_price": center,
                "stop_loss_price": center - 0.01 if fvg.bullish else center + 0.01,
                "take_profit_price": center + 0.03 if fvg.bullish else center - 0.03,
                "partial_close_percent": 50,
                "reason": "FVG_Tap"
            }
            signals.append(signal)
            fvg.used = True
        return signals