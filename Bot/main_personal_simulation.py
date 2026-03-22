# main_personal_simulation.py（大量ダミーデータによるシミュレーション）
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from core.trade_core import TradeCore
from engine.market_engine import MarketEngine
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy
from utils.logger import BotLogger
from utils.telegram_notifier import TelegramNotifier

# --------------------------
# 設定
# --------------------------
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
NUM_CANDLES = 200  # 生成するローソク足数
BASE_PRICE = {"BTCUSDT": 30000, "ETHUSDT": 2000}

TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# --------------------------
# ロガー・通知・TradeCore初期化
# --------------------------
logger = BotLogger()
notifier = TelegramNotifier(token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
trade_core = TradeCore(logger=logger, notifier=notifier)

# --------------------------
# 戦略初期化
# --------------------------
strategies = []
for symbol in SYMBOLS:
    strategies.append(FVGStrategy(trade_core=trade_core, logger=logger, notifier=notifier))
    strategies.append(RSIStrategy(trade_core=trade_core, logger=logger, notifier=notifier))

# --------------------------
# MarketEngine初期化
# --------------------------
engine = MarketEngine(strategies=strategies, debug=True)

# --------------------------
# ダミーデータ生成関数
# --------------------------
def generate_candles(symbol, num_candles, base_price):
    candles = []
    current_time = datetime.now() - timedelta(minutes=num_candles)
    price = base_price
    for _ in range(num_candles):
        open_p = price
        high_p = open_p + 50
        low_p = open_p - 50
        close_p = low_p + (high_p - low_p) * 0.5
        volume = 10
        candle = {
            "symbol": symbol,
            "time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": volume,
        }
        candles.append(candle)
        current_time += timedelta(minutes=1)
        price = close_p  # 次足の始値は前足終値
    return candles

# --------------------------
# ダミーデータループ（シミュレーション）
# --------------------------
async def run_simulation():
    logger.info("=== ダミーデータシミュレーション開始 ===")
    all_candles = []
    for symbol in SYMBOLS:
        all_candles.extend(generate_candles(symbol, NUM_CANDLES, BASE_PRICE[symbol]))

    # 時間順にソート
    all_candles.sort(key=lambda x: x['time'])

    for candle in all_candles:
        engine.process_data(candle)
        trade_core.check_orders()
        # 任意でログ出力（大量データの場合はコメントアウト可）
        # logger.info(f"Processed candle: {candle}")
        await asyncio.sleep(0.01)  # 適度に待機

    logger.info("=== ダミーデータシミュレーション終了 ===")

# --------------------------
# 非同期実行
# --------------------------
if __name__ == "__main__":
    asyncio.run(run_simulation())