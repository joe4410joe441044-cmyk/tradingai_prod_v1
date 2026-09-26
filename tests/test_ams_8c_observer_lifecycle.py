"""Focused coverage for the read-only selection observation thread lifecycle.

The observer loop is intentionally independent of the trading runtime so a
STOPPED bot keeps a fresh selection preview.  These tests pin the lifecycle
safety properties: single instance, clean stop, restart without orphan threads,
exception containment, and no self-join deadlock.  They never touch an order
path.
"""

import threading
import time

from backend.bot_manager.bot_manager import BotManager


def make_host(calls, *, interval=0.005, on_observe=None):
    host = BotManager.__new__(BotManager)
    host.selection_observation_lock = threading.Lock()
    host.selection_observation_stop = threading.Event()
    host.selection_observation_thread = None
    host.selection_observation_interval_seconds = interval

    def observe(*args, **kwargs):
        calls.append(1)
        if on_observe is not None:
            on_observe()
        return {"accepted": True}

    host.observe_auto_market_selection = observe
    return host


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_observer_start_runs_and_stop_terminates_thread():
    calls = []
    host = make_host(calls)
    assert host.start_selection_observation() == {"accepted": True}
    thread = host.selection_observation_thread
    try:
        assert thread is not None and thread.is_alive()
        assert wait_until(lambda: len(calls) >= 2)
    finally:
        assert host.stop_selection_observation() == {"accepted": True}
    assert host.selection_observation_thread is None
    assert wait_until(lambda: not thread.is_alive())
    settled = len(calls)
    time.sleep(0.05)
    assert len(calls) == settled


def test_observer_duplicate_start_is_rejected():
    calls = []
    host = make_host(calls)
    assert host.start_selection_observation() == {"accepted": True}
    try:
        assert wait_until(lambda: len(calls) >= 1)
        duplicate = host.start_selection_observation()
        assert duplicate == {
            "accepted": False,
            "reason": "SELECTION_OBSERVATION_ALREADY_RUNNING",
        }
    finally:
        host.stop_selection_observation()


def test_observer_restart_after_stop_leaves_no_orphan_threads():
    calls = []
    host = make_host(calls)
    host.start_selection_observation()
    first = host.selection_observation_thread
    host.stop_selection_observation()
    assert wait_until(lambda: not first.is_alive())

    host.start_selection_observation()
    second = host.selection_observation_thread
    try:
        assert second is not None and second is not first
        assert wait_until(lambda: len(calls) >= 2)
    finally:
        host.stop_selection_observation()
    assert wait_until(lambda: not second.is_alive())


def test_observer_exception_does_not_terminate_loop():
    calls = []

    def fail():
        raise RuntimeError("observation failure")

    host = make_host(calls, on_observe=fail)
    host.start_selection_observation()
    try:
        assert wait_until(lambda: len(calls) >= 3)
        assert host.selection_observation_thread.is_alive()
    finally:
        host.stop_selection_observation()


def test_observer_self_join_does_not_deadlock():
    calls = []
    holder = {}
    proceed = threading.Event()

    def stop_from_within():
        # Wait until the main thread has captured the observer thread handle so
        # the stop call genuinely originates from inside the observer thread.
        proceed.wait(1.0)
        holder["host"].stop_selection_observation()

    host = make_host(calls, interval=0.005, on_observe=stop_from_within)
    holder["host"] = host
    host.start_selection_observation()
    thread = host.selection_observation_thread
    assert thread is not None
    proceed.set()
    assert wait_until(lambda: not thread.is_alive())
    assert host.selection_observation_thread is None
