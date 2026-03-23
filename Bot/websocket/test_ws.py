# -*- coding: utf-8 -*-
# test_ws.py
from ws_client import BinanceWSClient

def on_candle(candle):
    print(f"[TEST] Candle received: {candle}")

def main():
    client = BinanceWSClient(symbol="BTCUSDT", on_message=on_candle)
    client.start()

    try:
        print("[INFO] WebSocket client started. Press Ctrl+C to stop.")
        while True:
            pass
    except KeyboardInterrupt:
        print("[INFO] Stopping WebSocket...")
        client.stop()

if __name__ == "__main__":
    main()