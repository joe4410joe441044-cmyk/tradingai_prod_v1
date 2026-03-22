# -*- coding: utf-8 -*-
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
    蜊倅ｸ謌ｦ逡･・哥VG讀懷・繝ｻ繧ｷ繧ｰ繝翫Ν逕滓・
    BaseStrategy 繧堤ｶ呎価縺励※蜈ｱ騾夐Κ蛻・・隕ｪ縺ｫ莉ｻ縺帙ｋ
    """

    def __init__(self, trade_core: TradeCore,
                 m15: pd.DataFrame = pd.DataFrame(),
                 h1: pd.DataFrame = pd.DataFrame(),
                 h4: pd.DataFrame = pd.DataFrame(),
                 logger: BotLogger = None,
                 notifier: TelegramNotifier = None):
        # 蜈ｱ騾夐Κ蛻・・ BaseStrategy 縺ｫ莉ｻ縺帙ｋ
        super().__init__(trade_core, logger, notifier)

        # 繧ｿ繧､繝繝輔Ξ繝ｼ繝縺斐→縺ｮ繝・・繧ｿ
        self.m15 = m15
        self.h1 = h1
        self.h4 = h4

        # FVG繝ｪ繧ｹ繝・
        self.fvg_list: List[FVG] = []

        # 險ｭ螳壹ヱ繝ｩ繝｡繝ｼ繧ｿ
        self.tap_threshold = 0.3
        self.require_engulfing = True

        self.logger and self.logger.info("FVGStrategy initialized.")

    # --------------------------
    # MarketEngine縺九ｉ蜻ｼ縺ｰ繧後ｋ蜈･蜿｣
    # --------------------------
    def on_bar(self, market_data):
        """
        MarketEngine縺九ｉ譛譁ｰ繝・・繧ｿ繧貞女縺大叙繧翫・
        Execution蠖｢蠑上〒繧ｷ繧ｰ繝翫Ν繧定ｿ斐☆
        """
        # 繝・・繧ｿ譖ｴ譁ｰ
        for tf in ["M15", "H1", "H4"]:
            if tf in market_data and not market_data[tf].empty:
                setattr(self, tf.lower(), market_data[tf])

        # FVG讀懷・
        self.detect_fvg()

        # 繧ｷ繧ｰ繝翫Ν逕滓・
        signals = self.generate_signals()
        if not signals:
            return None

        # Execution蠖｢蠑上↓螟画鋤縺励※霑斐☆・・radeCore縺ｫ貂｡縺呻ｼ・
        sig = signals[0]  # 縺ｨ繧翫≠縺医★1縺､縺縺・
        signal_exec = {
            "action": "BUY" if sig["trade_type"] == "buy" else "SELL",
            "symbol": market_data.get("symbol", "BTCUSDT"),
            "price": sig["entry_price"],
            "sl": sig["stop_loss_price"],
            "tp": sig["take_profit_price"],
            "size": 0.001  # 蝗ｺ螳壹し繧､繧ｺ縲ょｿ・ｦ√↑繧益olume蟇ｾ蠢・
        }

        # 繝ｭ繧ｰ繝ｻ騾夂衍
        self.logger and self.logger.info(f"FVGStrategy signal: {signal_exec}")
        self.notifier and self.notifier.send(f"FVGStrategy signal: {signal_exec}")

        return signal_exec

    # --------------------------
    # FVG讀懷・
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
    # 繧ｷ繧ｰ繝翫Ν逕滓・
    # --------------------------
    def generate_signals(self):
        """
        StrategyContext逶ｸ蠖薙・dict繝ｪ繧ｹ繝医〒霑斐☆
        """
        signals = []
        for fvg in self.fvg_list:
            if fvg.timeframe != "M15" or fvg.used:
                continue
            # 繧ｷ繝ｳ繝励Ν縺ｫ荳ｭ蠢・ｾ｡譬ｼ縺ｧ繧ｨ繝ｳ繝医Μ繝ｼ
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
