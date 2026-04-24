import asyncio
from fastapi import WebSocket
from backend.core.redis_pubsub import RedisPubSub

pubsub = RedisPubSub()

CHANNEL = "market:price"

# =========================
# WS HANDLER
# =========================

async def price_ws_handler(websocket: WebSocket):
    await websocket.accept()

    queue = asyncio.Queue()

    # Redis受信 → Queueに流す
    def handle_price(data):
        asyncio.create_task(queue.put(data))

    pubsub.subscribe(CHANNEL, handle_price)

    try:
        while True:
            data = await queue.get()

            await websocket.send_json({
                "type": "price",
                "data": data
            })

    except Exception:
        await websocket.close()