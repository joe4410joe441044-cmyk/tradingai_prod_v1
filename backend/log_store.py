# -*- coding: utf-8 -*-

from threading import Lock
from datetime import datetime

# =========================
# 内部ログストレージ
# =========================
_logs = []
_lock = Lock()

# =========================
# 設定
# =========================
MAX_LOGS = 500  # 最大保持数

# =========================
# ログ追加
# =========================
def add_log(msg: str):
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] {msg}"

    print(formatted)  # VPSコンソールにも出す

    with _lock:
        _logs.append(formatted)

        # 古いログ削除（メモリ対策）
        if len(_logs) > MAX_LOGS:
            _logs.pop(0)

# =========================
# ログ取得
# =========================
def get_logs():
    with _lock:
        return list(_logs)  # コピー返す（安全）