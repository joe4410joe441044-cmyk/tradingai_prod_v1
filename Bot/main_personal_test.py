# main_personal_test.py（FVG本番ロジックを壊さずテスト用に修正済み）

import pandas as pd
from engine.market_engine import MarketEngine
from core.trade_core import TradeCore
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy
from utils.logger import BotLogger

# --------------------------
# ロガー初期化
# --------------------------
logger = BotLogger()  # 引数なしで初期化（本番仕様に合わせる）

# --------------------------
# TradeCore 初期化（戦略は一旦空リスト）
# --------------------------
trade_core = TradeCore(logger=logger)

# --------------------------
# FVGStrategy用テストラッパー
# 本番の on_bar を使って process_data のように呼び出せる
# --------------------------
def fvg_process_data(self, df, timeframe="M15"):
    market_data = {timeframe: df, "symbol": "BTCUSDT"}
    self.on_bar(market_data)

FVGStrategy.process_data = fvg_process_data

# --------------------------
# 戦略初期化
# --------------------------
fvg_strategy = FVGStrategy(trade_core=trade_core, logger=logger)
rsi_strategy = RSIStrategy(trade_core=trade_core, logger=logger)  # RSIStrategyも trade_core 必須

strategies = [fvg_strategy, rsi_strategy]

# TradeCore に戦略をセット
trade_core.strategies = strategies

# --------------------------
# MarketEngine 初期化（logger 引数なしに合わせる）
# --------------------------
engine = MarketEngine(strategies=strategies)

# --------------------------
# ダミーCandle作成（本番フォーマットのDataFrameに変換）
# --------------------------
dummy_candles = [
    {"symbol": "BTCUSDT", "Open": 30000, "high": 30100, "low": 29950, "Close": 30100, "Volume": 10},
    {"symbol": "BTCUSDT", "Open": 30200, "high": 30250, "low": 30100, "Close": 30150, "Volume": 12},
    {"symbol": "BTCUSDT", "Open": 30150, "high": 30300, "low": 30100, "Close": 30300, "Volume": 15},
]

df_dummy = pd.DataFrame(dummy_candles)

timeframes = ["M15", "H1", "H4"]

# --------------------------
# 各時間足にデータを追加して戦略を実行
# --------------------------
for tf in timeframes:
    # FVGStrategyはprocess_dataを経由してon_barを呼ぶ
    fvg_strategy.process_data(df_dummy, timeframe=tf)
    logger.info(f"FVGStrategy - {tf} データ行数: {len(df_dummy)}")

# RSIStrategyも同様にテスト可能
# rsi_strategy.process_data(df_dummy, timeframe=tf)  # 必要に応じて追加

logger.info("=== ダミーデータによる戦略動作確認終了 ===")