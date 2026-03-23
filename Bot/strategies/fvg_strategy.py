# -*- coding: utf-8 -*-

from typing import List
import pandas as pd

from Bot.strategies.base_strategy import BaseStrategy
from Bot.core.trade_core import TradeCore
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier


class FVG:
    def __init__(self, top: float, bottom: float, bullish: bool, timeframe: str):
        self.top = top
        self.bottom = bottom
        self.bullish = bullish
        self.used = False
        self.timeframe = timeframe


class FVGStrategy(BaseStrategy):

    def __init__(self,
                 trade_core: TradeCore,
                 m15: pd.DataFrame = None,
                 h1: pd.DataFrame = None,
                 h4: pd.DataFrame = None,
                 logger: BotLogger = None,
                 notifier: TelegramNotifier = None):

        super().__init__(trade_core, logger, notifier)

        self.m15 = m15 if m15 is not None else pd.DataFrame()
        self.h1 = h1 if h1 is not None else pd.DataFrame()
        self.h4 = h4 if h4 is not None else pd.DataFrame()

        self.fvg_list: List[FVG] = []

        self.tap_threshold = 0.3
        self.require_engulfing = True

        # 最新シグナル格納用
        self.latest_signal = None

        if self.logger:
            self.logger.info("FVGStrategy initialized.")

    # --------------------------
    def on_bar(self, market_data):

        print("[FVG] on_bar called")

        # Data更新
        for tf in ["M15", "H1", "H4"]:
            if tf in market_data and not market_data[tf].empty:
                setattr(self, tf.lower(), market_data[tf])

        # FVG検出
        self.detect_fvg()

        # Signal生成
        signals = self.generate_signals()

        if not signals:
            # ⭐ 強制テスト用シグナル（必ず動作確認できる）
            self.latest_signal = {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "qty": 0.001,
                "price": 50000
            }
            print("[FVG] FORCED SIGNAL")
            return None

        sig = signals[0]

        signal_exec = {
            "symbol": market_data.get("symbol", "BTCUSDT"),
            "side": "BUY" if sig["trade_type"] == "buy" else "SELL",
            "qty": 0.001,
            "price": sig["entry_price"],
            "sl": sig["stop_loss_price"],
            "tp": sig["take_profit_price"],
        }

        self.latest_signal = signal_exec

        print("[FVG] SIGNAL GENERATED:", signal_exec)

        if self.logger:
            self.logger.info(f"FVGStrategy signal: {signal_exec}")

        if self.notifier:
            try:
                self.notifier.send_message(f"FVGStrategy signal: {signal_exec}")
            except Exception as e:
                print("Notifier error:", e)

        return signal_exec

    # --------------------------
    def detect_fvg(self):
        self._add_fvg(self.m15, "M15")
        self._add_fvg(self.h1, "H1")
        self._add_fvg(self.h4, "H4")

    def _add_fvg(self, df: pd.DataFrame, tf: str):
        if len(df) < 3:
            return

        high2 = df['high'].iloc[-3]
        low2 = df['low'].iloc[-3]
        high0 = df['high'].iloc[-1]
        low0 = df['low'].iloc[-1]

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
    def generate_signals(self):
        signals = []

        for fvg in self.fvg_list:
            if fvg.timeframe != "M15" or fvg.used:
                continue

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