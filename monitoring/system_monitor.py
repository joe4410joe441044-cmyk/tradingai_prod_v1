# -*- coding: utf-8 -*-

import time
import traceback
import threading
from collections import deque
from typing import Dict, Any, List


# =====================================================
# SYSTEM MONITOR（PRODUCTION FULL VERSION）
# =====================================================
class SystemMonitor:

    def __init__(self):

        # =========================
        # THREAD SAFE
        # =========================
        self.lock = threading.Lock()

        # =========================
        # LOG STORAGE
        # =========================
        self.logs: deque = deque(maxlen=2000)

        # =========================
        # SYSTEM STATUS
        # =========================
        self.status = {
            "backend": False,
            "trade_core": False,
            "risk_manager": False,
            "execution_engine": False,
            "websocket": False
        }

        # =========================
        # ALERT STATE
        # =========================
        self.alert_active = False
        self.last_alert = None

        # =========================
        # METRICS
        # =========================
        self.metrics = {
            "errors": 0,
            "events": 0,
            "risk_blocks": 0,
            "orders": 0
        }

        # external hooks
        self.alert_service = None

    # =====================================================
    # CONNECT ALERT SERVICE
    # =====================================================
    def attach_alert_service(self, service):
        self.alert_service = service

    # =====================================================
    # ERROR LOG
    # =====================================================
    def log_error(self, source: str, error: Exception, context: dict = None):

        with self.lock:

            log = {
                "type": "ERROR",
                "source": source,
                "message": str(error),
                "trace": traceback.format_exc(),
                "context": context or {},
                "timestamp": time.time()
            }

            self.logs.append(log)
            self.metrics["errors"] += 1

        print(f"[ERROR:{source}] {error}")

    # =====================================================
    # EVENT LOG
    # =====================================================
    def log_event(self, event: str, data: dict = None):

        with self.lock:

            log = {
                "type": event,
                "data": data or {},
                "timestamp": time.time()
            }

            self.logs.append(log)
            self.metrics["events"] += 1

            # =========================
            # METRICS TRACKING
            # =========================
            if event == "ORDER_EXECUTE":
                self.metrics["orders"] += 1

            if event == "RISK_BLOCK":
                self.metrics["risk_blocks"] += 1

    # =====================================================
    # STATUS UPDATE
    # =====================================================
    def update_status(self, key: str, value: bool):

        with self.lock:
            if key in self.status:
                self.status[key] = value

    # =====================================================
    # HEALTH SCORE
    # =====================================================
    def health_score(self):

        total = len(self.status)
        ok = sum(1 for v in self.status.values() if v)

        return round(ok / total, 2) if total else 0.0

    # =====================================================
    # SYSTEM HEALTH (API OUTPUT)
    # =====================================================
    def health_check(self):

        with self.lock:

            return {
                "status": self.status,
                "health_score": self.health_score(),
                "metrics": self.metrics,
                "error_count": self.metrics["errors"],
                "event_count": self.metrics["events"],
                "last_logs": list(self.logs)[-20:]
            }

    # =====================================================
    # INTEGRATION CHECK
    # =====================================================
    def integration_check(self):

        issues = []

        for k, v in self.status.items():
            if not v:
                issues.append(f"{k} NOT CONNECTED")

        return {
            "ok": len(issues) == 0,
            "issues": issues
        }

    # =====================================================
    # ANOMALY DETECTION (CORE)
    # =====================================================
    def detect_anomaly(self):

        with self.lock:

            recent = list(self.logs)[-100:]

            errors = len([l for l in recent if l["type"] == "ERROR"])
            risk_blocks = len([l for l in recent if l["type"] == "RISK_BLOCK"])
            orders = len([l for l in recent if l["type"] == "ORDER_EXECUTE"])

            alert = None

            if errors >= 10:
                alert = {
                    "alert": True,
                    "level": "HIGH",
                    "reason": "HIGH_ERROR_RATE",
                    "errors": errors
                }

            elif risk_blocks >= 8:
                alert = {
                    "alert": True,
                    "level": "MEDIUM",
                    "reason": "RISK_SPIKE",
                    "risk_blocks": risk_blocks
                }

            elif orders == 0 and len(recent) > 50:
                alert = {
                    "alert": True,
                    "level": "LOW",
                    "reason": "NO_ACTIVITY"
                }

            if alert:
                self.alert_active = True
                self.last_alert = alert
                self.log_event("ALERT", alert)

                # =========================
                # EXTERNAL ALERT PUSH
                # =========================
                if self.alert_service:
                    try:
                        self.alert_service.send(alert)
                    except Exception:
                        pass

            return alert or {"alert": False}

    # =====================================================
    # GET LOGS
    # =====================================================
    def get_logs(self, limit: int = 200):

        with self.lock:
            return list(self.logs)[-limit:]

    # =====================================================
    # TEST ERROR
    # =====================================================
    def test_error(self):

        try:
            raise RuntimeError("SYSTEM MONITOR TEST ERROR")

        except Exception as e:
            self.log_error("test_error", e, {"test": True})