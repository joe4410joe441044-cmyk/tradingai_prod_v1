# -*- coding: utf-8 -*-
"""Archived remote logger for the unmounted Legacy AI API."""

import requests
import threading
import time
import logging


class AILogger:

    def __init__(self):
        self.endpoint = "http://127.0.0.1:8010/api/ai/log"

        # 内部ログ（UI用）
        self.logs = []
        self.max_logs = 200

        # 送信失敗の連続カウント（簡易サーキットブレーカ）
        self.fail_count = 0
        self.fail_threshold = 5
        self.backoff_until = 0  # epoch秒

        self.lock = threading.Lock()

    # =========================
    # PUBLIC LOG
    # =========================
    def log(self, data: dict):
        """
        data:
        {
            "type": "INFO",
            "message": "entry signal detected"
        }
        """

        log_entry = {
            "time": time.strftime("%H:%M:%S"),
            "type": data.get("type", "INFO"),
            "message": data.get("message", "")
        }

        # ===== 内部保存（スレッド安全） =====
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]

        # ===== 外部送信（非同期） =====
        # backoff中は送信しない（スパム防止）
        now = time.time()
        if now < self.backoff_until:
            return

        threading.Thread(
            target=self._send,
            args=(log_entry,),
            daemon=True
        ).start()

    # =========================
    # INTERNAL SEND
    # =========================
    def _send(self, data):
        try:
            resp = requests.post(self.endpoint, json=data, timeout=1.0)

            # HTTPエラーも検知
            if resp.status_code >= 400:
                raise Exception(f"HTTP {resp.status_code}")

            # 成功時はカウンタリセット
            self.fail_count = 0

        except Exception as e:
            # ❌ 無視しない → ログに出す
            logging.error(f"[AI LOGGER ERROR] {e}")

            # サーキットブレーカ
            self.fail_count += 1
            if self.fail_count >= self.fail_threshold:
                # 一定時間送信停止
                self.backoff_until = time.time() + 10  # 10秒休止
                logging.warning("[AI LOGGER] backoff activated (10s)")

    # =========================
    # UI用
    # =========================
    def get_recent_logs(self, limit=50):
        with self.lock:
            return self.logs[-limit:]

    def clear(self):
        with self.lock:
            self.logs = []
