from fastapi import WebSocket
from backend.core.realtime.ws_router import EventRouter

router = EventRouter()

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    router.register(ws)

    try:
        while True:
            await ws.receive_text()

    except:
        router.unregister(ws)