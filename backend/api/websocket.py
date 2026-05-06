# -*- coding: utf-8 -*-

from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from typing import List

import asyncio
import logging

from backend.bot_manager import get_bot_manager

# =========================
# ROUTER
# =========================

router = APIRouter()

logger = logging.getLogger(__name__)

# =========================
# CONNECTIONS
# =========================

connections: List[WebSocket] = []

# =========================
# DEBUG
# =========================

DEBUG_WS = False

# =========================
# JSON SAFE
# =========================

def safe_json(obj):

    try:

        if isinstance(
            obj,
            (int, float, str, bool)
        ) or obj is None:

            return obj

        if isinstance(obj, list):

            return [
                safe_json(x)
                for x in obj
            ]

        if isinstance(obj, dict):

            return {
                k: safe_json(v)
                for k, v in obj.items()
            }

        return str(obj)

    except Exception:

        return str(obj)

# =========================
# CONNECT
# =========================

async def connect(ws: WebSocket):

    await ws.accept()

    connections.append(ws)

    logger.info(
        f"[WS CONNECT] total={len(connections)}"
    )

# =========================
# DISCONNECT
# =========================

def disconnect(ws: WebSocket):

    if ws in connections:

        connections.remove(ws)

        logger.info(
            f"[WS DISCONNECT] total={len(connections)}"
        )

# =========================
# WEBSOCKET
# =========================

@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket
):

    # =========================
    # CONNECT
    # =========================

    await connect(ws)

    bot = get_bot_manager()

    print(
        "WS BOT ID:",
        id(bot)
    )

    try:

        while True:

            # =========================
            # BOT STATUS
            # =========================

            data = bot.get_status()

            data = safe_json(data)

            # =========================
            # DEBUG
            # =========================

            if DEBUG_WS:

                print(
                    "WS SEND:",
                    data
                )

            # =========================
            # SEND
            # =========================

            await ws.send_json(data)

            # =========================
            # LOOP WAIT
            # =========================

            await asyncio.sleep(1)

    # =========================
    # DISCONNECT
    # =========================

    except WebSocketDisconnect:

        logger.warning(
            "[WS DISCONNECTED]"
        )

    # =========================
    # ERROR
    # =========================

    except Exception as e:

        logger.error(
            f"[WS LOOP ERROR] "
            f"{type(e).__name__}: {e}"
        )

    # =========================
    # FINALLY
    # =========================

    finally:

        disconnect(ws)