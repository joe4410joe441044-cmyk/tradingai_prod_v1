# main_personal.py（本番/WebSocket + ダミーデータ統合版）

import asyncio
from datetime import datetime
from core.trade_core import TradeCore
from engine.market_engine import MarketEngine
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy
from utils.logger import BotLogger
from utils.telegram_notifier import TelegramNotifier

# WebSocket用（python-binance）
from binance import AsyncClient, BinanceSocketManager

# --------------------------
# 設定
# --------------------------
USE_DUMMY = True  # True: ダミーデータでテスト / False: 本番WebSocket
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "1m"
API_KEY = "YOUR_BINANCE_API_KEY"
API_SECRET = "YOUR_BINANCE_SECRET"

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
# ダミーデータループ（テスト用）
# --------------------------
async def run_dummy():
    logger.info("=== ダミーデータテスト開始 ===")
    dummy_candles = [
        {"symbol": "BTCUSDT", "time": "2026-03-22 00:00:00", "open": 30000, "high": 30100, "low": 29950, "close": 30100, "volume": 10},
        {"symbol": "BTCUSDT", "time": "2026-03-22 00:01:00", "open": 30200, "high": 30250, "low": 30100, "close": 30150, "volume": 12},
        {"symbol": "ETHUSDT", "time": "2026-03-22 00:02:00", "open": 2000, "high": 2010, "low": 1995, "close": 2005, "volume": 5},
    ]
    for candle in dummy_candles:
        engine.process_data(candle)
        trade_core.check_orders()
        await asyncio.sleep(0.1)  # 適度に間隔を開ける
    logger.info("=== ダミーデータテスト終了 ===")

# --------------------------
# WebSocketループ（本番用）
# --------------------------
async def run_websocket():
    client = await AsyncClient.create(API_KEY, API_SECRET)
    bm = BinanceSocketManager(client)
    sockets = [bm.kline_socket(symbol=symbol, interval=INTERVAL) for symbol in SYMBOLS]

    logger.info("=== WebSocket自動化BOT開始 ===")

    async def handle_socket(socket):
        async with socket as stream:
            while True:
                res = await stream.recv()
                kline = res['k']
                candle = {
                    "symbol": res['s'],
                    "time": datetime.fromtimestamp(kline['t'] / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(kline['o']),
                    "high": float(kline['h']),
                    "low": float(kline['l']),
                    "close": float(kline['c']),
                    "volume": float(kline['v']),
                }
                engine.process_data(candle)
                trade_core.check_orders()
                # 通知
                for order in trade_core.active_orders:
                    notifier.send(f"Active order: {order}")

    await asyncio.gather(*(handle_socket(s) for s in sockets))

# --------------------------
# 実行
# --------------------------
if __name__ == "__main__":
    if USE_DUMMY:
        asyncio.run(run_dummy())
    else:
        asyncio.run(run_websocket())