# -*- coding: utf-8 -*-
"""Persistent-store abstraction layer for Market Recorder control endpoints.

This module defines the repository boundary for replay protection and rate
limiting.  Control-layer code depends only on the Protocol interfaces; the
concrete backend is injected via standard constructor DI.

Current backend: in-memory (thread-safe).
Future backends: Redis, SQLite, PostgreSQL (NOT IMPLEMENTED).
"""

from collections import defaultdict, deque
from threading import Lock
from typing import Callable, Deque, Dict, Protocol

from backend.services.recorder_proxy.control_security_models import (
    RateLimitResult,
    RateLimitVerdict,
    ReplayResult,
    ReplayVerdict,
)


# ---------------------------------------------------------------------------
# ReplayStore
# ---------------------------------------------------------------------------

class ReplayStore(Protocol):
    """Repository boundary for nonce-based replay protection.

    A single atomic ``check_and_record`` operation rejects duplicates
    (fail-closed) and accepts first-seen keys bound to an expiry.

    Future persistent backends MUST implement the same contract with
    equivalent atomicity semantics.
    """

    def check_and_record(self, key: str, ttl_seconds: float) -> ReplayResult:
        """Atomically test and register a request key.

        Returns:
            ACCEPTED  – first observation; the key is now recorded.
            DUPLICATE – the key was already observed within its TTL.
            STORE_FAILURE – the store is unavailable; fail-closed.

        Raises:
            Never.  All failures are normalised to STORE_FAILURE.
        """


class ReplayStoreError(Exception):
    """Raised when a ReplayStore backend operation fails irrecoverably."""


# ---------------------------------------------------------------------------
# InMemoryReplayStore
# ---------------------------------------------------------------------------


class InMemoryReplayStore:
    """Thread-safe in-memory replay store (current adapter)."""

    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._entries: Dict[str, float] = {}
        self._lock = Lock()

    def check_and_record(self, key: str, ttl_seconds: float) -> ReplayResult:
        try:
            now = self._clock()
            expires_at = now + float(ttl_seconds)
            with self._lock:
                if key in self._entries and self._entries[key] > now:
                    return ReplayResult(
                        verdict=ReplayVerdict.DUPLICATE,
                        key=key,
                        expires_at_epoch=self._entries[key],
                    )
                self._entries[key] = expires_at
            return ReplayResult(
                verdict=ReplayVerdict.ACCEPTED,
                key=key,
                expires_at_epoch=expires_at,
            )
        except Exception:
            return ReplayResult(
                verdict=ReplayVerdict.STORE_FAILURE,
                key=key,
                expires_at_epoch=0.0,
            )


# ---------------------------------------------------------------------------
# RateLimitStore
# ---------------------------------------------------------------------------

class RateLimitStore(Protocol):
    """Repository boundary for rate-limit event accounting.

    A single atomic ``consume`` operation records a timestamped event
    against a logical key and returns whether the rate limit was exceeded.

    The *sliding-window* algorithm is the caller's responsibility; the
    store only provides atomic append + count semantics within a window
    boundary.

    Future persistent backends MUST implement the same contract with
    equivalent atomicity semantics.
    """

    def consume(
        self,
        key: str,
        limit: int,
        window_seconds: float,
        timestamp: float,
    ) -> RateLimitResult:
        """Atomically record a rate-limit event and return a verdict.

        Args:
            key: logical rate-limit identity.
            limit: maximum number of events within *window_seconds*.
            window_seconds: sliding-window duration (seconds).
            timestamp: monotonic epoch (injected clock value).

        Returns:
            ALLOWED  – within limit; event recorded.
            EXCEEDED – limit exhausted; event *not* recorded.
            STORE_FAILURE – store unavailable; fail-closed.

        Raises:
            Never.  All failures are normalised to STORE_FAILURE.
        """


class RateLimitStoreError(Exception):
    """Raised when a RateLimitStore backend operation fails irrecoverably."""


# ---------------------------------------------------------------------------
# InMemoryRateLimitStore
# ---------------------------------------------------------------------------

class InMemoryRateLimitStore:
    """Thread-safe in-memory rate-limit store (current adapter).

    Maintains a sliding-window deque per key.  Expired timestamps are
    lazily pruned during ``consume`` before counting.
    """

    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._entries: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def consume(
        self,
        key: str,
        limit: int,
        window_seconds: float,
        timestamp: float,
    ) -> RateLimitResult:
        try:
            window = float(window_seconds)
            with self._lock:
                events = self._entries[key]
                boundary = timestamp - window
                while events and events[0] <= boundary:
                    events.popleft()
                if len(events) >= int(limit):
                    oldest = events[0]
                    retry = max(0.0, (oldest + window) - timestamp)
                    return RateLimitResult(
                        verdict=RateLimitVerdict.EXCEEDED,
                        key=key,
                        current_count=len(events),
                        limit=int(limit),
                        window_seconds=window,
                        retry_after_seconds=retry,
                    )
                events.append(timestamp)
            return RateLimitResult(
                verdict=RateLimitVerdict.ALLOWED,
                key=key,
                current_count=len(events),
                limit=int(limit),
                window_seconds=window,
                retry_after_seconds=0.0,
            )
        except Exception:
            return RateLimitResult(
                verdict=RateLimitVerdict.STORE_FAILURE,
                key=key,
                current_count=0,
                limit=int(limit),
                window_seconds=float(window_seconds),
                retry_after_seconds=0.0,
            )
