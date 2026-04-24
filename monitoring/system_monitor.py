# -*- coding: utf-8 -*-

import time
import threading
import asyncio
from collections import deque


class SystemMonitor:

    def __init__(self):

        self.lock = threading.Lock()
        self.logs = deque(maxlen=2000)

        # =========================
        # STATUS
        # =========================
        self.status = {
            "backend": False,
            "trade_core": False,
            "risk_manager": False,
            "execution_engine": False,
            "websocket": False
        }

        # =========================
        # METRICS
        # =========================
        self.metrics = {
            "errors": 0,
            "events": 0,
            "risk_blocks": 0,
            "orders": 0,
            "heartbeat": 0
        }

        # =========================
        # 🔥 DASHBOARD（追加）
        # =========================
        self.dashboard_data = {
            "price": 0,
            "balance": 0,
            "equity": 0,
            "pnl": 0,
            "positions": [],
            "logs": [],
            "status": "RUNNING",
            "connection": "ONLINE"
        }

        # =========================
        # WS
        # =========================
        self.ws_clients = []

        # asyncio loop
        self.loop = None

    # =====================================================
    # LOOP
    # =====================================================
    def set_loop(self, loop):
        print("🧠 LOOP REGISTERED")
        self.loop = loop

    # =====================================================
    # WS管理
    # =====================================================
    def register_ws(self, websocket):
        print("🔌 WS REGISTERED")
        self.ws_clients.append(websocket)

    def unregister_ws(self, websocket):
        if websocket in self.ws_clients:
            self.ws_clients.remove(websocket)
            print("❌ WS REMOVED")

    # =====================================================
    # 内部送信
    # =====================================================
    async def _send(self, ws, event):
        try:
            await ws.send_json(event)
        except Exception:
            self.unregister_ws(ws)

    # =====================================================
    # BROADCAST
    # =====================================================
    def _broadcast(self, event):

        if not self.ws_clients or not self.loop:
            return

        for ws in list(self.ws_clients):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send(ws, event),
                    self.loop
                )
            except Exception:
                self.unregister_ws(ws)

    # =====================================================
    # 🔥 ダッシュボード更新（最重要追加）
    # =====================================================
    def update_dashboard(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                if k in self.dashboard_data:
                    self.dashboard_data[k] = v

    def get_dashboard_data(self):
        with self.lock:
            data = dict(self.dashboard_data)
            data["logs"] = list(self.logs)[-20:]
            return data

    # =====================================================
    # EVENT
    # =====================================================
    def log_event(self, event_type, data=None):

        log = {
            "time": time.strftime("%H:%M:%S"),
            "type": event_type,
            "message": str(data) if data else "",
            "timestamp": time.time()
        }

        with self.lock:
            self.logs.append(log)
            self.metrics["events"] += 1

        print("📡 EVENT:", log)

        self._broadcast(log)

    # =====================================================
    # ERROR
    # =====================================================
    def log_error(self, source, error, context=None):

        log = {
            "time": time.strftime("%H:%M:%S"),
            "type": "ERROR",
            "source": source,
            "message": str(error),
            "context": context or {},
            "timestamp": time.time()
        }

        with self.lock:
            self.logs.append(log)
            self.metrics["errors"] += 1

        print("[ERROR]", log)

        self._broadcast(log)

    # =====================================================
    # SPECIAL
    # =====================================================
    def log_order(self, data):
        self.metrics["orders"] += 1
        self.log_event("ORDER", data)

    def log_risk_block(self, data):
        self.metrics["risk_blocks"] += 1
        self.log_event("RISK_BLOCK", data)

    def heartbeat(self):
        self.metrics["heartbeat"] += 1
        self.log_event("HEARTBEAT")

    # =====================================================
    # STATUS
    # =====================================================
    def update_status(self, key: str, value: bool):
        with self.lock:
            if key in self.status:
                self.status[key] = value

    # =====================================================
    # HEALTH
    # =====================================================
    def health_score(self):
        total = len(self.status)
        ok = sum(1 for v in self.status.values() if v)
        return round(ok / total, 2) if total else 0.0

    def health_check(self):
        with self.lock:
            return {
                "status": self.status,
                "health_score": self.health_score(),
                "metrics": self.metrics,
                "last_logs": list(self.logs)[-50:]
            }

    # =====================================================
    # LOG取得
    # =====================================================
    def get_logs(self):
        with self.lock:
            return list(self.logs)