# -*- coding: utf-8 -*-
# main_personal.pyE/WebSocket + EEEEE

import asyncio
from datetime import datetime
from Bot.core.trade_core import TradeCore
from engine.market_engine import MarketEngine
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.strategies.rsi_strategy import RSIStrategy
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier

# WebSocketEEython-binanceEE
from binance import AsyncClient, BinanceSocketManager

# --------------------------
# E
# --------------------------
USE_DUMMY = True  # True: EEEEE/ False: WebSocket
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "1m"
API_KEY = "YOUR_BINANCE_API_KEY"
API_SECRET = "YOUR_BINANCE_SECRET"

TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# --------------------------
# TradeCoreE
# --------------------------
logger = BotLogger()
notifier = TelegramNotifier(token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
trade_core = TradeCore(logger=logger, notifier=notifier)

# --------------------------
# E
# --------------------------
strategies = []
for symbol in SYMBOLS:
    strategies.append(FVGStrategy(trade_core=trade_core, logger=logger, notifier=notifier))
    strategies.append(RSIStrategy(trade_core=trade_core, logger=logger, notifier=notifier))

# --------------------------
# MarketEngineE
# --------------------------
engine = MarketEngine(strategies=strategies, debug=True)

# --------------------------
# EEEEE
# --------------------------
async def run_dummy():
    logger.info("=== EEEEE===")
    dummy_candles = [
        {"symbol": "BTCUSDT", "time": "2026-03-22 00:00:00", "open": 30000, "high": 30100, "low": 29950, "close": 30100, "volume": 10},
        {"symbol": "BTCUSDT", "time": "2026-03-22 00:01:00", "open": 30200, "high": 30250, "low": 30100, "close": 30150, "volume": 12},
        {"symbol": "ETHUSDT", "time": "2026-03-22 00:02:00", "open": 2000, "high": 2010, "low": 1995, "close": 2005, "volume": 5},
    ]
    for candle in dummy_candles:
        engine.process_data(candle)
        trade_core.check_orders()
        await asyncio.sleep(0.1)  # 
    logger.info("=== EEEEE===")

# --------------------------
# WebSocketEE
# --------------------------
async def run_websocket():
    client = await AsyncClient.create(API_KEY, API_SECRET)
    bm = BinanceSocketManager(client)
    sockets = [bm.kline_socket(symbol=symbol, interval=INTERVAL) for symbol in SYMBOLS]

    logger.info("=== WebSocketBOTE===")

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
                # 
                for order in trade_core.active_orders:
                    notifier.send(f"Active order: {order}")

    await asyncio.gather(*(handle_socket(s) for s in sockets))

# --------------------------
# E
# --------------------------
if __name__ == "__main__":
    if USE_DUMMY:
        asyncio.run(run_dummy())
    else:
        asyncio.run(run_websocket())