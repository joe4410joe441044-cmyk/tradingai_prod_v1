# -*- coding: utf-8 -*-

import asyncio
import logging
from fastapi import WebSocketDisconnect


class EventRouter:

    def __init__(self):
        self.clients = set()
        self.lock = asyncio.Lock()

    # =========================
    # REGISTER
    # =========================
    async def register(self, ws):
        async with self.lock:
            self.clients.add(ws)
        logging.info(f"[WS] client registered ({len(self.clients)})")

    # =========================
    # UNREGISTER
    # =========================
    async def unregister(self, ws):
        async with self.lock:
            self.clients.discard(ws)
        logging.info(f"[WS] client unregistered ({len(self.clients)})")

    # =========================
    # BROADCAST
    # =========================
    async def broadcast(self, event):

        dead = []

        async with self.lock:
            clients_snapshot = list(self.clients)

        for ws in clients_snapshot:
            try:
                await ws.send_json(event)

            except WebSocketDisconnect:
                # 正常切断
                logging.info("[WS] client disconnected during broadcast")
                dead.append(ws)

            except Exception as e:
                # ❌ 隠さない
                logging.error(f"[WS BROADCAST ERROR] {e}")
                dead.append(ws)

        # 切断クライアント削除
        if dead:
            async with self.lock:
                for d in dead:
                    self.clients.discard(d)

            logging.info(f"[WS] cleaned {len(dead)} dead clients")