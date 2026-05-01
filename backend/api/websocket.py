# -*- coding: utf-8 -*-

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import logging

from backend.bot_manager import get_bot_manager

logger = logging.getLogger(__name__)

router = APIRouter()
connections: List[WebSocket] = []


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await connect(ws)

    bot = get_bot_manager()

    try:
        while True:
            try:
                engine = bot.get_engine()

                # =========================
                # 基本データ
                # =========================
                price = float(getattr(engine, "price", 0) or 0)
                balance = float(getattr(engine, "balance", 0) or 0)
                pnl = float(getattr(engine, "pnl", 0) or 0)

                equity = balance + pnl
                positions = getattr(engine, "positions", []) or []
                active = bool(getattr(engine, "active", False))

                # =========================
                # Risk
                # =========================
                r = getattr(engine, "risk", None)
                risk = None

                if r:
                    risk = {
                        "kill_switch": r.kill_switch.active,
                        "reason": r.kill_switch.reason,
                        "dd_limit": r.max_drawdown_pct,
                        "loss_limit": r.max_loss_streak,
                        "loss_count": r.consecutive_losses
                    }

                data = {
                    "price": price,
                    "balance": balance,
                    "pnl": pnl,
                    "equity": equity,
                    "positions": positions,
                    "status": "RUNNING" if active else "STOPPED",
                    "connection": "ONLINE",
                    "risk": risk
                }

                logger.info(f"[WS SEND] {data}")

                # 🔥 ここが最重要修正
                try:
                    await ws.send_json(data)
                except Exception as send_error:
                    logger.error(f"[WS SEND ERROR] {send_error}")
                    break  # ← ここでループ終了

            except Exception as e:
                logger.error(f"[WS INNER ERROR] {type(e).__name__}: {e}")
                break  # ← ここも止める（重要）

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        logger.warning("[WS DISCONNECTED]")
        disconnect(ws)

    except Exception as e:
        logger.error(f"[WS LOOP ERROR] {type(e).__name__}: {e}")
        disconnect(ws)


async def connect(ws: WebSocket):
    try:
        await ws.accept()
        connections.append(ws)
        logger.info(f"[WS CONNECT] total={len(connections)}")
    except Exception as e:
        logger.error(f"[WS CONNECT ERROR] {type(e).__name__}: {e}")


def disconnect(ws: WebSocket):
    try:
        if ws in connections:
            connections.remove(ws)
            logger.info(f"[WS DISCONNECT] total={len(connections)}")
    except Exception as e:
        logger.error(f"[WS DISCONNECT ERROR] {type(e).__name__}: {e}")