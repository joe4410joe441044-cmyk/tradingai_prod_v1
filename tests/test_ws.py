import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print("WS:", data.get("symbol"), data.get("price"))

def on_error(ws, error):
    print("ERROR:", error)

def on_close(ws, close_status_code, close_msg):
    print("CLOSED")

def on_open(ws):
    print("CONNECTED")

if __name__ == "__main__":
    ws = websocket.WebSocketApp(
        "ws://127.0.0.1:8001/ws",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )

    ws.run_forever()