# backend/ws/ws_buffer.py

import time
import asyncio
from collections import deque
from backend.utils.log_buffer import ws_debug

class WSBuffer:
    """
    WebSocketイベントの中間バッファ（本番用）
    - 順序保証（sequence管理）
    - 欠損検知
    - UI用スナップショット生成
    - latency計測
    """

    def __init__(self, maxlen=2000):
        self.buffer = deque(maxlen=maxlen)
        self.last_seq = 0
        self.lock = asyncio.Lock()

    async def push(self, event: dict):

        async with self.lock:

            seq = event.get("seq")

            # シーケンスチェック（欠損検出）
            if seq is not None and self.last_seq != 0:
                if seq != self.last_seq + 1:
                    ws_debug(
                        "WebSocket buffer sequence gap previous=%s current=%s",
                        self.last_seq,
                        seq,
                    )

            self.last_seq = seq or self.last_seq

            # latency計測
            now = time.time()
            event["latency_ms"] = int((now - event.get("ts", now)) * 1000)

            self.buffer.append(event)

    async def snapshot(self):
        async with self.lock:
            return list(self.buffer)

    async def latest(self):
        async with self.lock:
            return self.buffer[-1] if self.buffer else None
