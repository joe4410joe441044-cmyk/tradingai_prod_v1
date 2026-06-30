# -*- coding: utf-8 -*-

from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from typing import List

import asyncio
import math

from backend.bot_manager import get_bot_manager
from backend.utils.log_buffer import logger, ws_debug

# =========================
# ROUTER
# =========================

router = APIRouter()

# =========================
# CONNECTIONS
# =========================

connections: List[WebSocket] = []

# =========================
# JSON SAFE
# =========================

def safe_json(obj):

    try:

        # =========================
        # FLOAT SAFE
        # =========================

        if isinstance(obj, float):

            if math.isnan(obj):

                return 0

            if math.isinf(obj):

                return 0

            return obj

        # =========================
        # PRIMITIVE SAFE
        # =========================

        if isinstance(
            obj,
            (int, str, bool)
        ) or obj is None:

            return obj

        # =========================
        # LIST SAFE
        # =========================

        if isinstance(obj, list):

            return [
                safe_json(x)
                for x in obj
            ]

        # =========================
        # DICT SAFE
        # =========================

        if isinstance(obj, dict):

            return {
                k: safe_json(v)
                for k, v in obj.items()
            }

        # =========================
        # FALLBACK
        # =========================

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

    ws_debug("API WebSocket route opened")

    # =========================
    # CONNECT
    # =========================

    await connect(ws)

    bot = get_bot_manager()

    ws_debug("API WebSocket bot id=%s", id(bot))

    try:

        while True:

            # =========================
            # BOT STATUS
            # =========================

            data = bot.get_result()

            data = safe_json(data)


            # =========================
            # DEBUG
            # =========================



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
