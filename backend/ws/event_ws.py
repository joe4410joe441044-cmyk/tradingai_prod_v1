import asyncio
from backend.core.redis_pubsub import RedisPubSub

pubsub = RedisPubSub()

CHANNEL = "bot:events"

class EventWS:

    def __init__(self, websocket):
        self.ws = websocket

    async def run(self):
        await self.ws.accept()

        def send_to_client(data):
            asyncio.create_task(self.ws.send_json(data))

        pubsub.subscribe(CHANNEL, send_to_client)

        while True:
            await asyncio.sleep(1)