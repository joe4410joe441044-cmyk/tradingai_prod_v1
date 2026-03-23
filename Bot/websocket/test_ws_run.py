# -*- coding: utf-8 -*-
# test_ws_run.py
import json
import threading
from websocket import WebSocketApp

# 1. EE
def on_candle(candle):
    print(f"[WS] New candle: {candle}")

def _on_message(ws, message):
    data = json.loads(message)
    k = data['k']
    candle = {
        "open_time": k['t'],
        "open": float(k['o']),
        "high": float(k['h']),
        "low": float(k['l']),
        "close": float(k['c']),
        "volume": float(k['v']),
        "is_closed": k['x'],
    }
    on_candle(candle)

def _on_open(ws):
    print("[WS] Connected")

def _on_error(ws, error):
    print(f"[WS] Error: {error}")

def _on_close(ws, close_status_code, close_msg):
    print(f"[WS] Closed: {close_status_code} / {close_msg}")

# 2. WebSocket E
symbol = "btcusdt"
interval = "1m"  # 1E
url = f"wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}"

ws_app = WebSocketApp(
    url,
    on_message=_on_message,
    on_open=_on_open,
    on_error=_on_error,
    on_close=_on_close
)

# 3. E WS E
thread = threading.Thread(target=ws_app.run_forever, daemon=True)
thread.start()

# 4. EEE
import time
print("[WS] Thread started, receiving candles...")
while True:
    time.sleep(1)