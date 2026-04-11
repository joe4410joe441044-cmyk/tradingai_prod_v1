# Bot/control/duplicate_guard.py

import time
import threading
import hashlib


# =========================================================
# 🟡 GLOBAL SIGNAL REGISTRY（全BOT共有）
# =========================================================
class GlobalSignalRegistry:
    """
    全BOT共通のシグナル重複防止レイヤー
    """

    _lock = threading.Lock()
    _signals = {}  # fingerprint -> timestamp

    @classmethod
    def _now(cls):
        return time.time()

    @classmethod
    def generate_fingerprint(cls, symbol, strategy, timeframe, direction, price_bucket):
        raw = f"{symbol}:{strategy}:{timeframe}:{direction}:{price_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def is_duplicate(cls, fingerprint, cooldown_sec=60):
        """
        True = 重複（無視すべき）
        """
        with cls._lock:
            now = cls._now()

            if fingerprint in cls._signals:
                last_time = cls._signals[fingerprint]
                if now - last_time < cooldown_sec:
                    return True

            # update
            cls._signals[fingerprint] = now
            return False

    @classmethod
    def cleanup(cls, expire_sec=3600):
        """
        古いシグナル削除（メモリリーク防止）
        """
        with cls._lock:
            now = cls._now()
            keys_to_delete = [
                k for k, v in cls._signals.items()
                if now - v > expire_sec
            ]
            for k in keys_to_delete:
                del cls._signals[k]


# =========================================================
# 🟢 EXECUTION GUARD（BOTローカル）
# =========================================================
class ExecutionGuard:
    """
    各BOT単位の実行制御
    """

    def __init__(self, state_manager):
        self.state_manager = state_manager
        self._lock = threading.Lock()
        self._execution_flag = False

    # -----------------------------
    # 実行ロック
    # -----------------------------
    def acquire(self):
        if self._execution_flag:
            return False

        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return False

        self._execution_flag = True
        return True

    def release(self):
        self._execution_flag = False
        self._lock.release()

    # -----------------------------
    # ポジションチェック
    # -----------------------------
    def has_position(self, symbol, direction):
        """
        StateManager参照で既存ポジション確認
        """
        positions = self.state_manager.get_open_positions()

        for p in positions:
            if p["symbol"] == symbol and p["direction"] == direction:
                return True

        return False

    # -----------------------------
    # 総合判定
    # -----------------------------
    def can_execute(self, symbol, direction):
        """
        最終実行許可チェック
        """

        # ① 実行中チェック
        if self._execution_flag:
            return False

        # ② ポジションチェック
        if self.has_position(symbol, direction):
            return False

        return True