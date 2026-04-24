import asyncio
from backend.core.redis_pubsub import RedisPubSub

pubsub = RedisPubSub()

CHANNEL = "orders:executed"

class OrderWS:

    def __init__(self, websocket):
        self.ws = websocket

    async def run(self):
        await self.ws.accept()

        def send(data):
            asyncio.create_task(self.ws.send_json(data))

        pubsub.subscribe(CHANNEL, send)

        while True:
            await asyncio.sleep(1)