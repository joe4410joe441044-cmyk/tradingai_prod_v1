# -*- coding: utf-8 -*-
# main_personal.py・域悽逡ｪ/WebSocket + 繝繝溘・繝・・繧ｿ邨ｱ蜷育沿・・

import asyncio
from datetime import datetime
from core.trade_core import TradeCore
from engine.market_engine import MarketEngine
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy
from utils.logger import BotLogger
from utils.telegram_notifier import TelegramNotifier

# WebSocket逕ｨ・・ython-binance・・
from binance import AsyncClient, BinanceSocketManager

# --------------------------
# 險ｭ螳・
# --------------------------
USE_DUMMY = True  # True: 繝繝溘・繝・・繧ｿ縺ｧ繝・せ繝・/ False: 譛ｬ逡ｪWebSocket
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "1m"
API_KEY = "YOUR_BINANCE_API_KEY"
API_SECRET = "YOUR_BINANCE_SECRET"

TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# --------------------------
# 繝ｭ繧ｬ繝ｼ繝ｻ騾夂衍繝ｻTradeCore蛻晄悄蛹・
# --------------------------
logger = BotLogger()
notifier = TelegramNotifier(token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
trade_core = TradeCore(logger=logger, notifier=notifier)

# --------------------------
# 謌ｦ逡･蛻晄悄蛹・
# --------------------------
strategies = []
for symbol in SYMBOLS:
    strategies.append(FVGStrategy(trade_core=trade_core, logger=logger, notifier=notifier))
    strategies.append(RSIStrategy(trade_core=trade_core, logger=logger, notifier=notifier))

# --------------------------
# MarketEngine蛻晄悄蛹・
# --------------------------
engine = MarketEngine(strategies=strategies, debug=True)

# --------------------------
# 繝繝溘・繝・・繧ｿ繝ｫ繝ｼ繝暦ｼ医ユ繧ｹ繝育畑・・
# --------------------------
async def run_dummy():
    logger.info("=== 繝繝溘・繝・・繧ｿ繝・せ繝磯幕蟋・===")
    dummy_candles = [
        {"symbol": "BTCUSDT", "time": "2026-03-22 00:00:00", "open": 30000, "high": 30100, "low": 29950, "close": 30100, "volume": 10},
        {"symbol": "BTCUSDT", "time": "2026-03-22 00:01:00", "open": 30200, "high": 30250, "low": 30100, "close": 30150, "volume": 12},
        {"symbol": "ETHUSDT", "time": "2026-03-22 00:02:00", "open": 2000, "high": 2010, "low": 1995, "close": 2005, "volume": 5},
    ]
    for candle in dummy_candles:
        engine.process_data(candle)
        trade_core.check_orders()
        await asyncio.sleep(0.1)  # 驕ｩ蠎ｦ縺ｫ髢馴囈繧帝幕縺代ｋ
    logger.info("=== 繝繝溘・繝・・繧ｿ繝・せ繝育ｵゆｺ・===")

# --------------------------
# WebSocket繝ｫ繝ｼ繝暦ｼ域悽逡ｪ逕ｨ・・
# --------------------------
async def run_websocket():
    client = await AsyncClient.create(API_KEY, API_SECRET)
    bm = BinanceSocketManager(client)
    sockets = [bm.kline_socket(symbol=symbol, interval=INTERVAL) for symbol in SYMBOLS]

    logger.info("=== WebSocket閾ｪ蜍募喧BOT髢句ｧ・===")

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
                # 騾夂衍
                for order in trade_core.active_orders:
                    notifier.send(f"Active order: {order}")

    await asyncio.gather(*(handle_socket(s) for s in sockets))

# --------------------------
# 螳溯｡・
# --------------------------
if __name__ == "__main__":
    if USE_DUMMY:
        asyncio.run(run_dummy())
    else:
        asyncio.run(run_websocket())
