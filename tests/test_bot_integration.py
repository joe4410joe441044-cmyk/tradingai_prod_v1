# -*- coding: utf-8 -*-
import requests
import websocket
import json
import threading
import time

API_BASE = "http://127.0.0.1:8001/api/bot"
WS_URL = "ws://127.0.0.1:8001/ws"

# =========================
# 設定
# =========================
TEST_CONFIG = {
    "symbol": "BTCUSDT",
    "risk_percent": 1,
    "sl_percent": 1,
    "leverage": 5,
    "mode": "paper"
}

# =========================
# WS監視
# =========================
latest_data = {}

def on_message(ws, message):
    global latest_data
    try:
        data = json.loads(message)
        payload = data.get("data") or data.get("bot") or data

        latest_data = payload

        print("📡 WS:", payload)

    except Exception as e:
        print("❌ WS parse error:", message)

def on_error(ws, error):
    print("🔴 WS ERROR:", error)

def on_close(ws, close_status_code, close_msg):
    print("🔴 WS CLOSED")

def on_open(ws):
    print("🟢 WS CONNECTED")

def start_ws():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )
    ws.run_forever()

# =========================
# テスト実行
# =========================
def run_test():
    print("🚀 TEST START")

    # WS開始
    ws_thread = threading.Thread(target=start_ws, daemon=True)
    ws_thread.start()

    time.sleep(2)

    # START
    print("▶ START BOT")
    res = requests.post(f"{API_BASE}/start", json=TEST_CONFIG)
    print("START RESPONSE:", res.text)

    # 状態確認
    time.sleep(5)

    print("\n🔍 CHECK RESULT")

    # -------------------------
    # CHECK 1: symbol
    # -------------------------
    symbol = latest_data.get("symbol")
    print("symbol:", symbol)

    # -------------------------
    # CHECK 2: price
    # -------------------------
    price = latest_data.get("price")
    print("price:", price)

    # -------------------------
    # CHECK 3: status
    # -------------------------
    status = latest_data.get("status")
    print("status:", status)

    # -------------------------
    # 判定
    # -------------------------
    print("\n🧪 RESULT")

    if symbol != TEST_CONFIG["symbol"]:
        print("❌ SYMBOL MISMATCH")
    elif not price or price == 0:
        print("❌ PRICE INVALID")
    elif status != "RUNNING":
        print("❌ STATUS NOT RUNNING")
    else:
        print("✅ BASIC OK")

    # STOP
    print("\n■ STOP BOT")
    requests.post(f"{API_BASE}/stop")

    time.sleep(2)
    print("🏁 TEST END")


if __name__ == "__main__":
    run_test()