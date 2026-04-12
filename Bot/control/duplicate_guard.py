# Bot/control/duplicate_guard.py

import time
import threading
import hashlib


# =========================================================
# 🟡 GLOBAL SIGNAL REGISTRY
# =========================================================
class GlobalSignalRegistry:

    _lock = threading.Lock()
    _signals = {}

    @classmethod
    def _now(cls):
        return time.time()

    @classmethod
    def generate_fingerprint(cls, symbol, strategy, timeframe, direction, price_bucket):
        raw = f"{symbol}:{strategy}:{timeframe}:{direction}:{price_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def is_duplicate(cls, fingerprint, cooldown_sec=60):

        with cls._lock:
            now = cls._now()

            if fingerprint in cls._signals:
                if now - cls._signals[fingerprint] < cooldown_sec:
                    return True

            cls._signals[fingerprint] = now
            return False

    @classmethod
    def cleanup(cls, expire_sec=3600):

        with cls._lock:
            now = cls._now()
            cls._signals = {
                k: v for k, v in cls._signals.items()
                if now - v <= expire_sec
            }


# =========================================================
# 🟢 EXECUTION GUARD
# =========================================================
class ExecutionGuard:

    def __init__(self, state_manager=None):
        self.state_manager = state_manager
        self._lock = threading.Lock()
        self._execution_flag = False

    # -----------------------------
    def acquire(self):
        if self._execution_flag:
            return False

        if not self._lock.acquire(blocking=False):
            return False

        self._execution_flag = True
        return True

    def release(self):
        self._execution_flag = False
        if self._lock.locked():
            self._lock.release()

    # -----------------------------
    def has_position(self, symbol, direction):
        """
        ⚠️ StateManager依存を避ける安全版
        """
        if not self.state_manager:
            return False

        # safe fallback（saveベース）
        state = self.state_manager.state.save()

        # もしpositions構造がない場合は無視
        positions = state.get("positions", [])

        for p in positions:
            if p.get("symbol") == symbol and p.get("direction") == direction:
                return True

        return False

    # -----------------------------
    def can_execute(self, symbol, direction):

        if self._execution_flag:
            return False

        if self.has_position(symbol, direction):
            return False

        return True