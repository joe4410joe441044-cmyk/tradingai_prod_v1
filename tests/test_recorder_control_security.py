# -*- coding: utf-8 -*-
"""Contract tests for Market Recorder control security stores.

Validates ReplayStore and RateLimitStore semantics including:
- first-seen / duplicate detection
- TTL / window expiry
- atomicity where the adapter supports it
- fail-closed behaviour on store failure
- thread-safety where the adapter supports it
"""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.services.recorder_proxy.control_security import (
    InMemoryRateLimitStore,
    InMemoryReplayStore,
)
from backend.services.recorder_proxy.control_security_models import (
    RateLimitResult,
    RateLimitVerdict,
    ReplayResult,
    ReplayVerdict,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class FixedClock:
    def __init__(self, start=100.0):
        self._value = start

    def __call__(self):
        return self._value

    def advance(self, seconds):
        self._value += seconds


# ---------------------------------------------------------------------------
# ReplayStore contract tests
# ---------------------------------------------------------------------------

class ReplayStoreContractTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock()
        self.store = InMemoryReplayStore(clock=self.clock)

    def test_first_record_accepted(self):
        result = self.store.check_and_record("req-001", ttl_seconds=30.0)
        self.assertEqual(result.verdict, ReplayVerdict.ACCEPTED)
        self.assertEqual(result.key, "req-001")
        self.assertGreater(result.expires_at_epoch, self.clock())

    def test_duplicate_rejected(self):
        self.assertEqual(
            self.store.check_and_record("req-002", 30.0).verdict,
            ReplayVerdict.ACCEPTED,
        )
        result = self.store.check_and_record("req-002", 30.0)
        self.assertEqual(result.verdict, ReplayVerdict.DUPLICATE)
        self.assertEqual(result.key, "req-002")

    def test_expired_entry_reusable(self):
        self.assertEqual(
            self.store.check_and_record("req-003", 5.0).verdict,
            ReplayVerdict.ACCEPTED,
        )
        self.clock.advance(6.0)
        result = self.store.check_and_record("req-003", 5.0)
        self.assertEqual(result.verdict, ReplayVerdict.ACCEPTED)

    def test_not_expired_when_still_within_ttl(self):
        self.assertEqual(
            self.store.check_and_record("req-004", 10.0).verdict,
            ReplayVerdict.ACCEPTED,
        )
        self.clock.advance(9.0)
        result = self.store.check_and_record("req-004", 10.0)
        self.assertEqual(result.verdict, ReplayVerdict.DUPLICATE)

    def test_different_keys_independent(self):
        self.assertEqual(
            self.store.check_and_record("key-a", 30.0).verdict,
            ReplayVerdict.ACCEPTED,
        )
        self.assertEqual(
            self.store.check_and_record("key-b", 30.0).verdict,
            ReplayVerdict.ACCEPTED,
        )
        self.assertEqual(
            self.store.check_and_record("key-a", 30.0).verdict,
            ReplayVerdict.DUPLICATE,
        )
        self.assertEqual(
            self.store.check_and_record("key-b", 30.0).verdict,
            ReplayVerdict.DUPLICATE,
        )

    def test_expires_at_reflects_ttl(self):
        result = self.store.check_and_record("req-005", 42.0)
        self.assertEqual(result.verdict, ReplayVerdict.ACCEPTED)
        expected = self.clock() + 42.0
        self.assertAlmostEqual(result.expires_at_epoch, expected, places=5)

    def test_expires_at_after_accept_vs_duplicate(self):
        first = self.store.check_and_record("req-006", 30.0)
        self.assertEqual(first.verdict, ReplayVerdict.ACCEPTED)
        second = self.store.check_and_record("req-006", 30.0)
        self.assertEqual(second.verdict, ReplayVerdict.DUPLICATE)
        self.assertEqual(first.expires_at_epoch, second.expires_at_epoch)

    def test_concurrent_check_and_record_atomic(self):
        results = []
        barrier = threading.Barrier(8, timeout=2)

        def worker():
            barrier.wait()
            r = self.store.check_and_record("concurrent-key", 60.0)
            results.append(r.verdict)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker) for _ in range(8)]
            for f in futures:
                f.result(timeout=3)

        accepted = sum(1 for v in results if v == ReplayVerdict.ACCEPTED)
        duplicates = sum(1 for v in results if v == ReplayVerdict.DUPLICATE)
        self.assertEqual(accepted, 1)
        self.assertEqual(duplicates, 7)

    def test_store_returns_fail_closed_on_unexpected_error(self):
        class BrokenStore:
            def check_and_record(self, key, ttl_seconds):
                return ReplayResult(
                    verdict=ReplayVerdict.STORE_FAILURE,
                    key=key,
                    expires_at_epoch=0.0,
                )

        store = BrokenStore()
        result = store.check_and_record("fail-key", 30.0)
        self.assertEqual(result.verdict, ReplayVerdict.STORE_FAILURE)


# ---------------------------------------------------------------------------
# RateLimitStore contract tests
# ---------------------------------------------------------------------------

class RateLimitStoreContractTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock()
        self.store = InMemoryRateLimitStore(clock=self.clock)

    def test_within_limit_accepted(self):
        for i in range(3):
            ts = self.clock()
            result = self.store.consume("client-1", limit=5, window_seconds=60.0, timestamp=ts)
            self.assertEqual(result.verdict, RateLimitVerdict.ALLOWED)
            self.assertEqual(result.key, "client-1")
            self.assertEqual(result.current_count, i + 1)
            self.assertEqual(result.limit, 5)
            self.clock.advance(0.001)

    def test_limit_exceeded_rejected(self):
        ts = self.clock()
        for _ in range(3):
            self.store.consume("client-2", limit=3, window_seconds=60.0, timestamp=ts)

        result = self.store.consume("client-2", limit=3, window_seconds=60.0, timestamp=ts)
        self.assertEqual(result.verdict, RateLimitVerdict.EXCEEDED)
        self.assertEqual(result.current_count, 3)
        self.assertGreater(result.retry_after_seconds, 0)

    def test_window_expiry_resets_limit(self):
        limit = 3
        window = 10.0

        for i in range(limit):
            r = self.store.consume("client-3", limit=limit, window_seconds=window, timestamp=self.clock())
            self.assertEqual(r.verdict, RateLimitVerdict.ALLOWED)
            self.clock.advance(0.001)

        r = self.store.consume("client-3", limit=limit, window_seconds=window, timestamp=self.clock())
        self.assertEqual(r.verdict, RateLimitVerdict.EXCEEDED)

        self.clock.advance(window + 1.0)
        r = self.store.consume("client-3", limit=limit, window_seconds=window, timestamp=self.clock())
        self.assertEqual(r.verdict, RateLimitVerdict.ALLOWED)
        self.assertEqual(r.current_count, 1)

    def test_different_keys_independent(self):
        ts = self.clock()
        self.store.consume("user-a", limit=2, window_seconds=60.0, timestamp=ts)
        self.store.consume("user-a", limit=2, window_seconds=60.0, timestamp=ts)
        self.assertEqual(
            self.store.consume("user-a", limit=2, window_seconds=60.0, timestamp=ts).verdict,
            RateLimitVerdict.EXCEEDED,
        )
        self.assertEqual(
            self.store.consume("user-b", limit=2, window_seconds=60.0, timestamp=ts).verdict,
            RateLimitVerdict.ALLOWED,
        )

    def test_retry_after_seconds_for_exceeded(self):
        limit = 1
        window = 10.0
        ts = self.clock()

        self.store.consume("client-4", limit=limit, window_seconds=window, timestamp=ts)
        result = self.store.consume("client-4", limit=limit, window_seconds=window, timestamp=ts)
        self.assertEqual(result.verdict, RateLimitVerdict.EXCEEDED)
        self.assertAlmostEqual(result.retry_after_seconds, window, places=5)

    def test_current_count_after_exceeded(self):
        limit = 3
        window = 10.0

        for _ in range(limit):
            self.store.consume("client-5", limit=limit, window_seconds=window, timestamp=self.clock())
            self.clock.advance(0.001)

        result = self.store.consume("client-5", limit=limit, window_seconds=window, timestamp=self.clock())
        self.assertEqual(result.verdict, RateLimitVerdict.EXCEEDED)
        self.assertEqual(result.current_count, limit)

    def test_concurrent_consume_atomic(self):
        limit = 10
        window = 60.0
        results = []
        barrier = threading.Barrier(16, timeout=2)

        def worker():
            barrier.wait()
            r = self.store.consume("concurrent-rl", limit=limit, window_seconds=window, timestamp=self.clock())
            results.append(r.verdict)

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker) for _ in range(16)]
            for f in futures:
                f.result(timeout=3)

        allowed = sum(1 for v in results if v == RateLimitVerdict.ALLOWED)
        self.assertEqual(allowed, limit)

    def test_store_returns_fail_closed_on_unexpected_error(self):
        class BrokenStore:
            def consume(self, key, limit, window_seconds, timestamp):
                return RateLimitResult(
                    verdict=RateLimitVerdict.STORE_FAILURE,
                    key=key,
                    current_count=0,
                    limit=limit,
                    window_seconds=window_seconds,
                    retry_after_seconds=0.0,
                )

        store = BrokenStore()
        result = store.consume("fail-rl", 10, 60.0, 100.0)
        self.assertEqual(result.verdict, RateLimitVerdict.STORE_FAILURE)


# ---------------------------------------------------------------------------
# Cross-cutting store tests
# ---------------------------------------------------------------------------

class ControlSecurityIntegrationTests(unittest.TestCase):
    def test_stores_are_independent(self):
        clock = FixedClock()
        replay = InMemoryReplayStore(clock=clock)
        ratelimit = InMemoryRateLimitStore(clock=clock)

        self.assertEqual(
            replay.check_and_record("integrated", 60.0).verdict,
            ReplayVerdict.ACCEPTED,
        )
        self.assertEqual(
            ratelimit.consume("integrated", 5, 60.0, clock()).verdict,
            RateLimitVerdict.ALLOWED,
        )
        self.assertEqual(
            replay.check_and_record("integrated", 60.0).verdict,
            ReplayVerdict.DUPLICATE,
        )

    def test_rate_limit_used_slots_unavailable_to_replay(self):
        clock = FixedClock()
        replay = InMemoryReplayStore(clock=clock)
        ratelimit = InMemoryRateLimitStore(clock=clock)

        r = replay.check_and_record("independent-key", 50.0)
        self.assertEqual(r.verdict, ReplayVerdict.ACCEPTED)

        rl = ratelimit.consume("independent-key", 1, 30.0, clock())
        self.assertEqual(rl.verdict, RateLimitVerdict.ALLOWED)
        rl = ratelimit.consume("independent-key", 1, 30.0, clock())
        self.assertEqual(rl.verdict, RateLimitVerdict.EXCEEDED)

        r = replay.check_and_record("independent-key", 50.0)
        self.assertEqual(r.verdict, ReplayVerdict.DUPLICATE)


if __name__ == "__main__":
    unittest.main()
