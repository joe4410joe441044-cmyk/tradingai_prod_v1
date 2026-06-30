# -*- coding: utf-8 -*-
import asyncio
import logging
from typing import Set, Dict, Any

from fastapi import WebSocket

class WebSocketManager:
    """
    Central WebSocket Hub
    - event broadcast
    - client management
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.clients: Set[WebSocket] = set()

    # =================================================
    # CONNECT / DISCONNECT
    # =================================================
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.clients.add(websocket)
        self.logger.info(f"[WS] client connected: {len(self.clients)}")

    def disconnect(self, websocket: WebSocket):
        self.clients.discard(websocket)
        self.logger.info(f"[WS] client disconnected: {len(self.clients)}")

    # =================================================
    # BROADCAST
    # =================================================
    async def broadcast(self, message: Dict[str, Any]):
        if not self.clients:
            return

        dead_clients = []

        for ws in self.clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead_clients.append(ws)

        for ws in dead_clients:
            self.disconnect(ws)

    # =================================================
    # SAFE SEND
    # =================================================
    async def send_to_all(self, event_type: str, data: Dict[str, Any]):
        payload = {
            "type": event_type,
            "data": data
        }
        await self.broadcast(payload)
