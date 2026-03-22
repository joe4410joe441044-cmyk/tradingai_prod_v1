# Bot/websocket/test_ws.py
import time
from Bot.websocket.ws_client import BinanceWSClient
from Bot.utils.telegram import TelegramNotifier

# ------------------------------
# Telegramテスト用
# ------------------------------
# 実際のトークン・チャットIDに置き換えてください
tg = TelegramNotifier(token="YOUR_BOT_TOKEN", chat_id="YOUR_CHAT_ID")

# ------------------------------
# 受信時のコールバック
# ------------------------------
def on_candle(candle):
    print(f"[TEST] Candle received: {candle}")
    tg.send(f"[TEST] Candle: {candle}")

# ------------------------------
# WebSocket クライアント起動
# ------------------------------
if __name__ == "__main__":
    client = BinanceWSClient(symbol="BTCUSDT", on_message=on_candle)
    client.start()

    print("[INFO] WebSocket client started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[INFO] Stopping WebSocket...")
        client.stop()
        print("[INFO] WebSocket stopped.")