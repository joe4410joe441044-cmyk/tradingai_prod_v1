# -*- coding: utf-8 -*-
# main_personal_test.pyEEVGEEE

import pandas as pd
from engine.market_engine import MarketEngine
from Bot.core.trade_core import TradeCore
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.strategies.rsi_strategy import RSIStrategy
from Bot.utils.logger import BotLogger

# --------------------------
# E
# --------------------------
logger = BotLogger()  # EE

# --------------------------
# TradeCore E
# --------------------------
trade_core = TradeCore(logger=logger)

# --------------------------
# FVGStrategyEE
#  on_bar  process_data 
# --------------------------
def fvg_process_data(self, df, timeframe="M15"):
    market_data = {timeframe: df, "symbol": "BTCUSDT"}
    self.on_bar(market_data)

FVGStrategy.process_data = fvg_process_data

# --------------------------
# E
# --------------------------
fvg_strategy = FVGStrategy(trade_core=trade_core, logger=logger)
rsi_strategy = RSIStrategy(trade_core=trade_core, logger=logger)  # RSIStrategyEtrade_core EE

strategies = [fvg_strategy, rsi_strategy]

# TradeCore E
trade_core.strategies = strategies

# --------------------------
# MarketEngine Eogger EE
# --------------------------
engine = MarketEngine(strategies=strategies)

# --------------------------
# ECandleEEEDataFrameEE
# --------------------------
dummy_candles = [
    {"symbol": "BTCUSDT", "Open": 30000, "high": 30100, "low": 29950, "Close": 30100, "Volume": 10},
    {"symbol": "BTCUSDT", "Open": 30200, "high": 30250, "low": 30100, "Close": 30150, "Volume": 12},
    {"symbol": "BTCUSDT", "Open": 30150, "high": 30300, "low": 30100, "Close": 30300, "Volume": 15},
]

df_dummy = pd.DataFrame(dummy_candles)

timeframes = ["M15", "H1", "H4"]

# --------------------------
# EEEE
# --------------------------
for tf in timeframes:
    # FVGStrategyprocess_dataon_bar
    fvg_strategy.process_data(df_dummy, timeframe=tf)
    logger.info(f"FVGStrategy - {tf} EE: {len(df_dummy)}")

# RSIStrategyE
# rsi_strategy.process_data(df_dummy, timeframe=tf)  # E

logger.info("=== EEEE===")