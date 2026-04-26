# -*- coding: utf-8 -*-

from fastapi import WebSocket, WebSocketDisconnect
import logging

from backend.core.realtime.ws_router import EventRouter

router = EventRouter()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):

    await ws.accept()
    router.register(ws)

    try:
        while True:
            # クライアントからのping / keepalive
            await ws.receive_text()

    except WebSocketDisconnect:
        # 正常切断
        logging.info("[WS] client disconnected")

    except Exception as e:
        # ❌ 隠さない（重要）
        logging.error(f"[WS ERROR] {e}")
        raise

    finally:
        # 必ず実行される（最重要）
        router.unregister(ws)