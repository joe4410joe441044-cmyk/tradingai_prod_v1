# -*- coding: utf-8 -*-

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import logging

from backend.bot_manager import get_bot_manager

router = APIRouter()

logger = logging.getLogger(__name__)

connections: List[WebSocket] = []

# 🔥 デバッグ制御
DEBUG_WS = False


# =========================
# JSON安全化
# =========================
def safe_json(obj):
    try:
        if isinstance(obj, (int, float, str, bool)) or obj is None:
            return obj
        if isinstance(obj, list):
            return [safe_json(x) for x in obj]
        if isinstance(obj, dict):
            return {k: safe_json(v) for k, v in obj.items()}
        return str(obj)
    except Exception:
        return str(obj)


# =========================
# 接続管理
# =========================
async def connect(ws: WebSocket):
    await ws.accept()
    connections.append(ws)
    logger.info(f"[WS CONNECT] total={len(connections)}")


def disconnect(ws: WebSocket):
    if ws in connections:
        connections.remove(ws)
        logger.info(f"[WS DISCONNECT] total={len(connections)}")


# =========================
# WebSocket
# =========================
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):

    await connect(ws)

    bot = get_bot_manager()
    print("WS BOT ID:", id(bot))

    try:
        while True:

            data = bot.get_status()
            data = safe_json(data)

            # 🔥 ログ制御
            if DEBUG_WS:
                print("WS SEND:", data)

            # 🔥 STOPでも切断しない
            await ws.send_json(data)

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        logger.warning("[WS DISCONNECTED]")

    except Exception as e:
        logger.error(f"[WS LOOP ERROR] {type(e).__name__}: {e}")

    finally:
        disconnect(ws)