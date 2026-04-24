import asyncio

class EventRouter:

    def __init__(self):
        self.clients = set()

    def register(self, ws):
        self.clients.add(ws)

    def unregister(self, ws):
        self.clients.discard(ws)

    async def broadcast(self, event):

        dead = []

        for ws in self.clients:
            try:
                await ws.send_json(event)
            except:
                dead.append(ws)

        for d in dead:
            self.clients.discard(d)