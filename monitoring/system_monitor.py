# -*- coding: utf-8 -*-

import time
import threading
import asyncio
from collections import deque
from copy import deepcopy

# =========================
# 🔥 Telegram（安全ロード）
# =========================
try:
    from Bot.utils.telegram_notifier import send_telegram
except Exception:
    send_telegram = None


class SystemMonitor:

    def __init__(self):

        self.lock = threading.Lock()

        # =========================
        # LOG
        # =========================
        self.logs = deque(maxlen=2000)
        self.error_logs = deque(maxlen=500)

        # スパム防止
        self._last_error_msg = None
        self._last_error_time = 0

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
        # DASHBOARD
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

        self._last_snapshot = dict(self.dashboard_data)

        # =========================
        # WS
        # =========================
        self.ws_clients = set()
        self.loop = None

    # =========================
    # LOOP
    # =========================
    def set_loop(self, loop):
        if loop and loop.is_running():
            print("🧠 LOOP REGISTERED")
            self.loop = loop

    # =========================
    # WS管理
    # =========================
    def register_ws(self, websocket):
        print("🔌 WS REGISTERED")
        self.ws_clients.add(websocket)

        self._send_initial_logs(websocket)
        self._send_initial_errors(websocket)

    def unregister_ws(self, websocket):
        if websocket in self.ws_clients:
            self.ws_clients.remove(websocket)
            print("❌ WS REMOVED")

    async def _send(self, ws, event):
        try:
            await ws.send_json(event)
        except Exception:
            self.unregister_ws(ws)

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

    # =========================
    # 初期送信
    # =========================
    def _send_initial_logs(self, ws):
        if not self.loop:
            return

        asyncio.run_coroutine_threadsafe(
            self._send(ws, {
                "type": "log_snapshot",
                "logs": list(self.logs)[-50:]
            }),
            self.loop
        )

    def _send_initial_errors(self, ws):
        if not self.loop:
            return

        asyncio.run_coroutine_threadsafe(
            self._send(ws, {
                "type": "error_snapshot",
                "errors": list(self.error_logs)[-50:]
            }),
            self.loop
        )

    # =========================
    # LOG配信
    # =========================
    def _broadcast_log_append(self, log):
        self._broadcast({"type": "log_append", "log": log})

    def _broadcast_error_append(self, log):
        self._broadcast({"type": "error_append", "error": log})

    # =========================
    # DASHBOARD
    # =========================
    def _compute_patch(self, new_data):
        return {
            k: v for k, v in new_data.items()
            if self._last_snapshot.get(k) != v
        }

    def update_dashboard(self, **kwargs):

        with self.lock:
            for k, v in kwargs.items():
                if k in self.dashboard_data:
                    self.dashboard_data[k] = v

            new_data = dict(self.dashboard_data)

        patch = self._compute_patch(new_data)

        if patch:
            self._broadcast({
                "type": "dashboard_patch",
                "patch": patch
            })
            self._last_snapshot = new_data  # deepcopy削除（高速化）

    def get_dashboard_data(self):
        with self.lock:
            return dict(self.dashboard_data)

    # =========================
    # EVENT
    # =========================
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
        self._broadcast_log_append(log)

    # =========================
    # 🔥 ERROR
    # =========================
    def log_error(self, source, error, context=None):

        err_str = str(error)

        log = {
            "time": time.strftime("%H:%M:%S"),
            "type": "ERROR",
            "source": source,
            "message": err_str,
            "context": context or {},
            "timestamp": time.time()
        }

        with self.lock:
            self.logs.append(log)
            self.error_logs.append(log)
            self.metrics["errors"] += 1

        print("[ERROR]", log)

        self._broadcast_log_append(log)
        self._broadcast_error_append(log)

        # =========================
        # 🔥 Telegram通知
        # =========================
        if send_telegram:

            now = time.time()

            is_critical = (
                "CRITICAL" in err_str.upper()
                or "FATAL" in err_str.upper()
            )

            if is_critical and (
                err_str != self._last_error_msg
                or now - self._last_error_time > 30
            ):
                try:
                    send_telegram(
                        f"🚨 CRITICAL ERROR\n"
                        f"{source}\n"
                        f"{err_str}\n"
                        f"{log['time']}"
                    )
                    self._last_error_msg = err_str
                    self._last_error_time = now
                except Exception as e:
                    print("[TELEGRAM ERROR]", e)

    # =========================
    # STATUS
    # =========================
    def update_status(self, key: str, value: bool):
        with self.lock:
            if key in self.status:
                self.status[key] = value

    # =========================
    # HEALTH
    # =========================
    def health_score(self):
        total = len(self.status)
        ok = sum(1 for v in self.status.values() if v)
        return round(ok / total, 2) if total else 0.0

    def health_check(self):
        with self.lock:
            return {
                "status": dict(self.status),
                "health_score": self.health_score(),
                "metrics": dict(self.metrics),
                "last_logs": list(self.logs)[-50:]
            }

    def get_logs(self):
        with self.lock:
            return list(self.logs)