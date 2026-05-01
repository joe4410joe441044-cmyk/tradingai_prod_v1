import asyncio
import websockets
import json

WS_URL = "ws://127.0.0.1:8001/ws"


async def test_ws():
    print("🔌 Connecting to WebSocket...")

    try:
        async with websockets.connect(WS_URL) as ws:
            print("🟢 CONNECTED")

            while True:
                msg = await ws.recv()

                try:
                    data = json.loads(msg)
                    print("📩 RECEIVED:", data)
                except:
                    print("📩 RAW:", msg)

    except Exception as e:
        print("❌ ERROR:", e)


if __name__ == "__main__":
    asyncio.run(test_ws())