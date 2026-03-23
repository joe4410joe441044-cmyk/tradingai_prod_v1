# -*- coding: utf-8 -*-
# Bot/start_engine.py
import time
from Bot.websocket.ws_client import BinanceWSClient
from Bot.engine.market_engine import MarketEngine
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.engine.execution_engine import ExecutionEngine
from Bot.websocket.telegram_notifier import TelegramNotifier  # 

# ---------------------------------
# Telegram ()
# ---------------------------------
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
telegram = TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)

# ---------------------------------
# ExecutionEngine ( OFF)
# ---------------------------------
execution_engine = ExecutionEngine(client=None, enable_trading=False)

# ---------------------------------
# 
# ---------------------------------
strategies = [
    FVGStrategy(execution_engine=execution_engine, debug=True)  # debug=TrueE
]

# ---------------------------------
# MarketEngine E
# ---------------------------------
engine = MarketEngine(strategies=strategies, debug=True)

# ---------------------------------
# WebSocket E
# ---------------------------------
def on_candle_received(candle):
    # MarketEngine E
    engine.process_data(candle)

# ---------------------------------
# Binance WebSocket Client
# ---------------------------------
ws_client = BinanceWSClient(
    symbol="BTCUSDT",
    on_message=on_candle_received,
    telegram=telegram
)

# ---------------------------------
# E
# ---------------------------------
if __name__ == "__main__":
    print("[INFO] WebSocket client started. Press Ctrl+C to stop.")
    ws_client.start()
    telegram.bot_started()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[INFO] Stopping WebSocket...")
        ws_client.stop()
        print("[INFO] Exited.")