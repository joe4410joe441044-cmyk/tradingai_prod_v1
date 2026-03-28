# -*- coding: utf-8 -*-

from typing import List
import pandas as pd

from Bot.strategies.base_strategy import BaseStrategy
from Bot.core.trade_core import TradeCore
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.utils.safety import safe_run


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

        # ★ 同一足制御
        self.last_signal_time = None

        if self.logger:
            self.logger.info("FVGStrategy initialized.")

    # --------------------------
    @safe_run
    def on_bar(self, market_data):

        print("[FVG] on_bar called")

        is_closed = market_data.get("is_closed", None)
        current_time = market_data.get("time")

        print(f"[FVG DEBUG] time={current_time} is_closed={is_closed}")

        # --------------------------
        # ★ 確定足のみ
        # --------------------------
        if not is_closed:
            print("[FVG] SKIP: not closed candle")
            return None

        # --------------------------
        # ★ 同一足1回のみ
        # --------------------------
        if current_time == self.last_signal_time:
            print("[FVG] SKIP: already processed this candle")
            return None

        self.last_signal_time = current_time

        print(f"[FVG] CLOSED CANDLE: {current_time}")

        # --------------------------
        # ★ 本番：ここではまだエントリーしない
        # --------------------------
        # FVGロジックが未実装のためシグナルは出さない
        return None

    # --------------------------
    # ↓↓↓ 以下は一旦使わない（残してOK）
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

    def generate_signals(self):
        return []