"""Deterministic single-process rate and concurrency protection."""

import asyncio
from collections import defaultdict, deque
from threading import Lock
from typing import Callable, Deque, Dict


class AdvisorRateLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float],
    ):
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or not isinstance(window_seconds, (int, float))
            or isinstance(window_seconds, bool)
            or window_seconds <= 0
        ):
            raise ValueError("rate limit configuration invalid")
        self._limit = limit
        self._window = float(window_seconds)
        self._clock = clock
        self._entries: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @property
    def retryAfterSeconds(self) -> int:
        return max(1, int(self._window))

    def allow(self, principal_id: str) -> bool:
        now = self._clock()
        with self._lock:
            entries = self._entries[principal_id]
            boundary = now - self._window
            while entries and entries[0] <= boundary:
                entries.popleft()
            if len(entries) >= self._limit:
                return False
            entries.append(now)
            return True


class AdvisorConcurrencyLimiter:
    def __init__(self, *, limit: int, acquire_timeout_seconds: float):
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or not isinstance(acquire_timeout_seconds, (int, float))
            or isinstance(acquire_timeout_seconds, bool)
            or acquire_timeout_seconds < 0
        ):
            raise ValueError("concurrency configuration invalid")
        self._semaphore = asyncio.Semaphore(limit)
        self._acquire_timeout = float(acquire_timeout_seconds)

    async def acquire(self) -> bool:
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._acquire_timeout,
            )
            return True
        except TimeoutError:
            return False

    def release(self) -> None:
        self._semaphore.release()
