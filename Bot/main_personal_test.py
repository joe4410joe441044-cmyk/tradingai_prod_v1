# main_personal_test.py・・VG譛ｬ逡ｪ繝ｭ繧ｸ繝・け繧貞｣翫＆縺壹ユ繧ｹ繝育畑縺ｫ菫ｮ豁｣貂医∩・・

import pandas as pd
from engine.market_engine import MarketEngine
from core.trade_core import TradeCore
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy
from utils.logger import BotLogger

# --------------------------
# 繝ｭ繧ｬ繝ｼ蛻晄悄蛹・
# --------------------------
logger = BotLogger()  # 蠑墓焚縺ｪ縺励〒蛻晄悄蛹厄ｼ域悽逡ｪ莉墓ｧ倥↓蜷医ｏ縺帙ｋ・・

# --------------------------
# TradeCore 蛻晄悄蛹厄ｼ域姶逡･縺ｯ荳譌ｦ遨ｺ繝ｪ繧ｹ繝茨ｼ・
# --------------------------
trade_core = TradeCore(logger=logger)

# --------------------------
# FVGStrategy逕ｨ繝・せ繝医Λ繝・ヱ繝ｼ
# 譛ｬ逡ｪ縺ｮ on_bar 繧剃ｽｿ縺｣縺ｦ process_data 縺ｮ繧医≧縺ｫ蜻ｼ縺ｳ蜃ｺ縺帙ｋ
# --------------------------
def fvg_process_data(self, df, timeframe="M15"):
    market_data = {timeframe: df, "symbol": "BTCUSDT"}
    self.on_bar(market_data)

FVGStrategy.process_data = fvg_process_data

# --------------------------
# 謌ｦ逡･蛻晄悄蛹・
# --------------------------
fvg_strategy = FVGStrategy(trade_core=trade_core, logger=logger)
rsi_strategy = RSIStrategy(trade_core=trade_core, logger=logger)  # RSIStrategy繧・trade_core 蠢・・

strategies = [fvg_strategy, rsi_strategy]

# TradeCore 縺ｫ謌ｦ逡･繧偵そ繝・ヨ
trade_core.strategies = strategies

# --------------------------
# MarketEngine 蛻晄悄蛹厄ｼ・ogger 蠑墓焚縺ｪ縺励↓蜷医ｏ縺帙ｋ・・
# --------------------------
engine = MarketEngine(strategies=strategies)

# --------------------------
# 繝繝溘・Candle菴懈・・域悽逡ｪ繝輔か繝ｼ繝槭ャ繝医・DataFrame縺ｫ螟画鋤・・
# --------------------------
dummy_candles = [
    {"symbol": "BTCUSDT", "Open": 30000, "high": 30100, "low": 29950, "Close": 30100, "Volume": 10},
    {"symbol": "BTCUSDT", "Open": 30200, "high": 30250, "low": 30100, "Close": 30150, "Volume": 12},
    {"symbol": "BTCUSDT", "Open": 30150, "high": 30300, "low": 30100, "Close": 30300, "Volume": 15},
]

df_dummy = pd.DataFrame(dummy_candles)

timeframes = ["M15", "H1", "H4"]

# --------------------------
# 蜷・凾髢楢ｶｳ縺ｫ繝・・繧ｿ繧定ｿｽ蜉縺励※謌ｦ逡･繧貞ｮ溯｡・
# --------------------------
for tf in timeframes:
    # FVGStrategy縺ｯprocess_data繧堤ｵ檎罰縺励※on_bar繧貞他縺ｶ
    fvg_strategy.process_data(df_dummy, timeframe=tf)
    logger.info(f"FVGStrategy - {tf} 繝・・繧ｿ陦梧焚: {len(df_dummy)}")

# RSIStrategy繧ょ酔讒倥↓繝・せ繝亥庄閭ｽ
# rsi_strategy.process_data(df_dummy, timeframe=tf)  # 蠢・ｦ√↓蠢懊§縺ｦ霑ｽ蜉

logger.info("=== 繝繝溘・繝・・繧ｿ縺ｫ繧医ｋ謌ｦ逡･蜍穂ｽ懃｢ｺ隱咲ｵゆｺ・===")
