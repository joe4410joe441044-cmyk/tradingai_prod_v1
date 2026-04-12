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
    def generate_fingerprint(
        cls,
        symbol: str,
        strategy: str,
        timeframe: str,
        direction: str,
        price_bucket: str
    ) -> str:
        raw = f"{symbol}:{strategy}:{timeframe}:{direction}:{price_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def is_duplicate(cls, fingerprint: str, cooldown_sec: int = 60) -> bool:

        with cls._lock:
            now = cls._now()

            if fingerprint in cls._signals:
                if now - cls._signals[fingerprint] < cooldown_sec:
                    return True

            cls._signals[fingerprint] = now
            return False

    @classmethod
    def cleanup(cls, expire_sec: int = 3600):

        with cls._lock:
            now = cls._now()
            cls._signals = {
                k: v for k, v in cls._signals.items()
                if now - v <= expire_sec
            }


# =========================================================
# 🟢 EXECUTION GUARD（PRODUCTION SAFE VERSION）
# =========================================================
class ExecutionGuard:

    def __init__(self, state_manager=None):
        self.state_manager = state_manager
        self._lock = threading.Lock()
        self._execution_flag = False

    # -----------------------------------------------------
    def acquire(self) -> bool:
        if self._execution_flag:
            return False

        if not self._lock.acquire(blocking=False):
            return False

        self._execution_flag = True
        return True

    # -----------------------------------------------------
    def release(self):
        self._execution_flag = False

        try:
            if self._lock.locked():
                self._lock.release()
        except Exception:
            pass

    # -----------------------------------------------------
    def _get_state_safe(self):
        """
        🛡 StateManager構造揺れ対策（ここが重要）
        """
        if not self.state_manager:
            return {}

        # ① 新設計：save()がある場合
        if hasattr(self.state_manager, "save"):
            try:
                state = self.state_manager.save()
                if isinstance(state, dict):
                    return state
            except Exception:
                pass

        # ② 旧設計：state.save()構造
        if hasattr(self.state_manager, "state"):
            try:
                state_obj = self.state_manager.state
                if hasattr(state_obj, "save"):
                    state = state_obj.save()
                    if isinstance(state, dict):
                        return state
            except Exception:
                pass

        # ③ フォールバック
        return {}

    # -----------------------------------------------------
    def has_position(self, symbol: str, direction: str) -> bool:

        state = self._get_state_safe()
        positions = state.get("positions", [])

        if not isinstance(positions, list):
            return False

        for p in positions:
            if not isinstance(p, dict):
                continue

            if p.get("symbol") == symbol and p.get("direction") == direction:
                return True

        return False

    # -----------------------------------------------------
    def can_execute(self, symbol: str, direction: str) -> bool:

        # ① 実行中フラグ
        if self._execution_flag:
            return False

        # ② ポジション重複チェック
        if self.has_position(symbol, direction):
            return False

        return True