"""MM baseline authority across PAPER session transitions.

Root cause (proven in TRADINGAI-MM-BASELINE-SESSION-TRANSITION-FIX-1):

* A KuCoin WS orderbook callback that was already past the top-of-callback
  identity checks could keep running across a STOP boundary and reach
  ``_observe_money_management_runtime_metrics``.  Because the observation
  source_state is ``self.lifecycle_state``, that stale callback overwrote the
  last valid RUNNING MM runtime metrics with a STOPPING/STOPPED source_state
  (available=False -> is_complete=False).

* The next PAPER session's ``begin_paper_session`` re-keyed session/identity
  but never returned the carried snapshot to a fresh RUNNING observation, so
  the carried STOPPING/STOPPED snapshot survived.  The post-RUNNING baseline
  handoff only re-observed when the carried source_state was exactly
  "STARTING", so START failed with MONEY_MANAGEMENT_BASELINE_INCOMPLETE even
  though monitoring/runtime/feed were safe.

All tests are isolated mocks / in-process doubles.  No network, no real order.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("TEST_MODE", "1")

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.enums import (
    MoneyManagementProfile,
    TradingMode,
)
from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetricsState,
)
from backend.money_management.models import MoneyManagementConfig
from backend.money_management.loss_runtime_integration_models import StateSource
from tests.test_money_management_loss_authoritative_runtime_metrics import persisted


def D(value):
    return Decimal(str(value))


NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


def _mm_config(maximum_drawdown_pct=D("7.00")):
    return MoneyManagementConfig(
        MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
        TradingMode.PAPER,
        D("1000"), D(".50"), D("100"),
        maximum_drawdown_pct,
        D("20"), D("10"),
        D("5"), False,
    )


def _paper_config():
    return {
        "symbol": "XRPUSDT", "exchange": "kucoin",
        "mode": "paper", "dry_run": True, "risk_percent": 1,
        "position_size": 100, "max_drawdown_pct": 7,
        "sl_percent": 0.5, "tp_percent": 1, "timeframe": "5m",
        "trailing_stop": True, "leverage": 4.0,
        "selection_mode": "MANUAL",
    }


def _dispatch_result(value="DISPATCHED"):
    return SimpleNamespace(status=SimpleNamespace(value=value))


def _observing_capture(manager):
    """Override account capture so MM observe reads authoritative values."""
    manager._capture_account_snapshot = lambda: {
        "balance": D("1000"),
        "equity": D("1000"),
        "availableBalance": D("1000"),
        "realizedPnl": D("0"),
        "unrealizedPnl": D("0"),
        "position": None,
    }


def _complete_snapshot_state(manager, session_id):
    """Return an authoritative accumulator seeded complete for one session."""
    state = AuthoritativeLossRuntimeMetricsState(manager.runtime_instance_id)
    state.restore(
        persisted(at=NOW),
        StateSource.INITIAL_STATE,
        NOW,
    )
    state.begin_paper_session(session_id, NOW + _tick(1))
    state.observe(
        as_of=NOW + _tick(2),
        session_id=session_id,
        balance=D("1000"),
        equity=D("1000"),
        available_balance=D("1000"),
        realized_pnl=D("0"),
        unrealized_pnl=D("0"),
        position=None,
        mark_price=D("100"),
        engine_peak_equity=D("1000"),
        source_state="RUNNING",
    )
    return state


def _carried_stopping_state(manager, session_id):
    """Simulate a STOP-time stale WS observation carried into a next session.

    Values/observation_valid exist, but source_state=STOPPING makes the
    snapshot available=False -> is_complete=False.
    """
    state = AuthoritativeLossRuntimeMetricsState(manager.runtime_instance_id)
    state.restore(
        persisted(at=NOW),
        StateSource.INITIAL_STATE,
        NOW,
    )
    state.begin_paper_session(session_id, NOW + _tick(1))
    state.observe(
        as_of=NOW + _tick(2),
        session_id=session_id,
        balance=D("1000"),
        equity=D("1000"),
        available_balance=D("1000"),
        realized_pnl=D("0"),
        unrealized_pnl=D("0"),
        position=None,
        mark_price=D("100"),
        engine_peak_equity=D("1000"),
        source_state="STOPPING",
    )
    return state


def _tick(seconds):
    return timedelta(seconds=seconds)


def _next_session_state(state, next_session):
    """Advance the accumulator to a fresh PAPER session without re-observing."""
    state.begin_paper_session(next_session, NOW + _tick(3))
    return state.snapshot()


def _started_manager():
    """A real PAPER BotManager started with a captured (non-firing) WS feed."""
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )

    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("7.00"))
    )
    captured = {}

    def create_ws(**kwargs):
        captured["callback"] = kwargs["on_update"]
        captured["runtime_id"] = kwargs["runtime_id"]
        return SimpleNamespace(
            MARKET_TYPE="spot",
            connected=False,
            start=lambda: None,
            stop=lambda: None,
        )

    return manager, captured, previous_positions_engine, execution_runtime, previous_runtime_engine, create_ws


# =========================
# FIX A — STOP-TIME WS RACE
# =========================

def test_stop_boundary_ws_callback_never_overwrites_active_mm_authority():
    """A callback past its identity checks must not observe after a STOP."""
    (manager, captured, previous_positions_engine,
     execution_runtime, previous_runtime_engine, create_ws) = _started_manager()
    config = _paper_config()
    try:
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            side_effect=create_ws,
        ):
            result = manager.start(config)
        assert result["status"] == "started"

        manager.money_management_runtime_metrics = _complete_snapshot_state(
            manager, manager.session_id
        )
        before = manager.money_management_runtime_metrics.snapshot()
        assert before.available is True
        assert before.is_complete is True
        assert before.source_state == "RUNNING"

        original_observe = manager._observe_money_management_runtime_metrics
        called = []

        def spy(*args, **kwargs):
            called.append(manager.lifecycle_state)
            return original_observe(*args, **kwargs)

        manager._observe_money_management_runtime_metrics = spy

        # Simulate the STOP boundary: the callback already passed the top
        # identity checks (runtime/session/symbol still match) but the
        # lifecycle is now STOPPING.
        manager._running = False
        manager.lifecycle_state = "STOPPING"

        callback = captured["callback"]
        callback(
            manager.symbol,
            {
                "symbol": manager.symbol,
                "bids": {"99": "1"},
                "asks": {"101": "1"},
                "price": 100,
                "best_bid": 99,
                "best_ask": 101,
            },
            captured["runtime_id"],
        )

        assert called == []
        after = manager.money_management_runtime_metrics.snapshot()
        assert after.source_state == "RUNNING"
        assert after.available is True
        assert after.is_complete is True
    finally:
        positions_router_cleanup(manager, previous_positions_engine,
                                 execution_runtime, previous_runtime_engine)


def test_run_boundary_ws_callback_still_observes_when_authority_active():
    """The recheck must not block a legitimate RUNNING callback."""
    (manager, captured, previous_positions_engine,
     execution_runtime, previous_runtime_engine, create_ws) = _started_manager()
    config = _paper_config()
    try:
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            side_effect=create_ws,
        ):
            result = manager.start(config)
        assert result["status"] == "started"

        manager.money_management_runtime_metrics = _carried_stopping_state(
            manager, manager.session_id
        )
        before = manager.money_management_runtime_metrics.snapshot()
        assert before.available is False

        manager._running = True
        manager.lifecycle_state = "RUNNING"
        _observing_capture(manager)

        original_observe = manager._observe_money_management_runtime_metrics
        called = []

        def spy(*args, **kwargs):
            called.append(manager.lifecycle_state)
            return original_observe(*args, **kwargs)

        manager._observe_money_management_runtime_metrics = spy

        callback = captured["callback"]
        callback(
            manager.symbol,
            {
                "symbol": manager.symbol,
                "bids": {"99": "1"},
                "asks": {"101": "1"},
                "price": 100,
                "best_bid": 99,
                "best_ask": 101,
            },
            captured["runtime_id"],
        )

        assert called == ["RUNNING"]
        after = manager.money_management_runtime_metrics.snapshot()
        assert after.source_state == "RUNNING"
        assert after.available is True
    finally:
        positions_router_cleanup(manager, previous_positions_engine,
                                 execution_runtime, previous_runtime_engine)


def test_mm_observation_authority_identity_contract():
    """Observation authority requires active runtime/session and lifecycle."""
    manager = BotManager()
    manager.active_runtime_id = "runtime-A"
    manager.session_id = 3

    cases = (
        # (lifecycle, runtime_id, session_id, expected)
        ("RUNNING", "runtime-A", 3, True),
        ("STARTING", "runtime-A", 3, True),
        ("STOPPING", "runtime-A", 3, False),
        ("STOPPED", "runtime-A", 3, False),
        ("RUNNING", None, 3, False),
        ("RUNNING", "runtime-A", None, False),
        ("RUNNING", "runtime-B", 3, False),
        ("RUNNING", "runtime-A", 2, False),
        (None, "runtime-A", 3, False),
    )
    for lifecycle, runtime_id, session_id, expected in cases:
        manager.lifecycle_state = lifecycle
        actual = manager._money_management_runtime_observation_authority(
            runtime_id, session_id
        )
        assert actual is expected, (lifecycle, runtime_id, session_id, actual)


def test_post_stop_stale_callback_is_inert_even_if_runtime_id_survives():
    """Even STOPPED (not just STOPPING) must not publish an observation."""
    manager = BotManager()
    manager.active_runtime_id = "runtime-A"
    manager.session_id = 5
    manager._running = False
    manager.lifecycle_state = "STOPPED"
    assert not manager._money_management_runtime_observation_authority(
        "runtime-A", 5
    )


# =========================
# FIX B + C — SESSION TRANSITION
# =========================

def test_carried_stopping_state_is_reobserved_at_next_session():
    """A carried STOPPING snapshot must not block the next baseline handoff."""
    manager = BotManager()
    manager.session_id = 1
    manager.money_management_runtime_metrics = _carried_stopping_state(
        manager, 1
    )
    # begin_paper_session(2) advances identity but leaves STOPPING carry.
    carried = _next_session_state(
        manager.money_management_runtime_metrics, 2
    )
    assert carried.session_id == 2
    assert carried.source_state == "STOPPING"
    assert carried.available is False
    assert carried.is_complete is False

    manager.session_id = 2
    manager.lifecycle_state = "RUNNING"
    _observing_capture(manager)
    manager.engine = SimpleNamespace(mode="paper")
    manager.money_management_runtime_baseline_session = None
    dispatched = []

    manager._notify_money_management_runtime_event = (
        lambda event_type, event_key: dispatched.append(event_key)
        or _dispatch_result()
    )

    result = manager._handoff_money_management_runtime_baseline(2)

    assert result.status.value == "DISPATCHED"
    assert manager.money_management_runtime_baseline_session == 2
    assert dispatched == [
        f"{manager.runtime_instance_id}:2:BASELINE:BALANCE_UPDATE"
    ]
    fresh = manager.money_management_runtime_metrics.snapshot()
    assert fresh.session_id == 2
    assert fresh.source_state == "RUNNING"
    assert fresh.available is True
    assert fresh.is_complete is True


def test_fresh_observation_remaining_incomplete_never_dispatches_baseline():
    """No fake baseline: an incomplete fresh observation keeps ENTRY closed."""
    manager = BotManager()
    manager.session_id = 3
    manager.money_management_runtime_metrics = _carried_stopping_state(
        manager, 2
    )
    manager.money_management_runtime_metrics.begin_paper_session(
        3, NOW + _tick(1)
    )
    manager.lifecycle_state = "RUNNING"
    manager.money_management_runtime_baseline_session = None
    manager._notify_money_management_runtime_event = (
        lambda event_type, event_key: (_ for _ in ()).throw(
            AssertionError("baseline must not be dispatched while incomplete")
        )
    )

    def incomplete_fresh(*args, **kwargs):
        return SimpleNamespace(
            runtime_instance_id=manager.runtime_instance_id,
            session_id=3,
            is_complete=False,
            source_state="RUNNING",
            available=True,
        )

    manager._observe_money_management_runtime_metrics = incomplete_fresh

    assert manager._handoff_money_management_runtime_baseline(3) is None
    assert manager.money_management_runtime_baseline_session is None
    assert manager.money_management_runtime_baseline_session != manager.session_id


def test_handoff_authority_correlation_rejects_stale_or_wrong_identity():
    """Baseline dispatch requires current complete runtime/session authority."""
    manager = BotManager()
    manager.session_id = 7
    manager.lifecycle_state = "RUNNING"
    manager.money_management_runtime_baseline_session = None
    manager._observe_money_management_runtime_metrics = (
        lambda *args, **kwargs: None
    )

    rejections = (
        # runtime mismatch
        SimpleNamespace(
            runtime_instance_id="other-runtime",
            session_id=7,
            is_complete=True,
        ),
        # previous session baseline
        SimpleNamespace(
            runtime_instance_id=manager.runtime_instance_id,
            session_id=6,
            is_complete=True,
        ),
        # incomplete metrics
        SimpleNamespace(
            runtime_instance_id=manager.runtime_instance_id,
            session_id=7,
            is_complete=False,
        ),
        # unavailable / not observed
        SimpleNamespace(
            runtime_instance_id=manager.runtime_instance_id,
            session_id=7,
            is_complete=False,
            available=False,
        ),
    )
    for snapshot in rejections:
        manager.money_management_runtime_metrics.snapshot = lambda: snapshot
        assert manager._handoff_money_management_runtime_baseline(7) is None

    # current complete baseline -> eligible (subject to later guards)
    manager.money_management_runtime_metrics.snapshot = lambda: SimpleNamespace(
        runtime_instance_id=manager.runtime_instance_id,
        session_id=7,
        is_complete=True,
    )
    manager._notify_money_management_runtime_event = (
        lambda event_type, event_key: _dispatch_result()
    )
    result = manager._handoff_money_management_runtime_baseline(7)
    assert result.status.value == "DISPATCHED"
    assert manager.money_management_runtime_baseline_session == 7


def _start_paper_session(manager, config, dispatched, patch_path):
    """One full PAPER session START; returns the start result."""
    manager.set_money_management_runtime_hook(
        lambda event_type, event_key: dispatched.append(event_key)
        or _dispatch_result()
    )
    with patch(
        "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
        side_effect=patch_path,
    ), patch("backend.bot_manager.bot_manager.time.sleep"):
        return manager.start(config)


def test_session_1_stop_2_stop_3_start_recovers_with_fresh_baseline():
    """Historical regression: S1 -> STOP -> S2 -> STOP -> S3 must start."""
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("7.00"))
    )
    config = _paper_config()

    def create_ws(**kwargs):
        return SimpleNamespace(
            MARKET_TYPE="spot",
            connected=False,
            start=lambda: None,
            stop=lambda: None,
        )

    dispatched = []
    now = datetime.now(timezone.utc)
    try:
        manager.money_management_runtime_metrics.restore(
            persisted(at=now),
            StateSource.INITIAL_STATE,
            now,
        )
        # Session 1
        r1 = _start_paper_session(manager, config, dispatched, create_ws)
        assert r1["status"] == "started", r1
        session1 = manager.session_id
        assert manager.money_management_runtime_baseline_session == session1
        assert r1["baselineComplete"] is True
        with patch("backend.bot_manager.bot_manager.time.sleep"):
            s1_stop = manager.stop()
        assert s1_stop["status"] == "stopped", s1_stop
        assert manager.lifecycle_state == "STOPPED"

        # Session 2
        r2 = _start_paper_session(manager, config, dispatched, create_ws)
        assert r2["status"] == "started", r2
        session2 = manager.session_id
        assert session2 == session1 + 1
        assert manager.money_management_runtime_baseline_session == session2
        assert r2["baselineComplete"] is True
        with patch("backend.bot_manager.bot_manager.time.sleep"):
            s2_stop = manager.stop()
        assert s2_stop["status"] == "stopped", s2_stop
        assert manager.lifecycle_state == "STOPPED"

        # Session 2 ended with a STOP-time stale WS observation: seed the
        # same carried STOPPING snapshot the historical race produced.
        manager.money_management_runtime_metrics.observe(
            as_of=datetime.now(timezone.utc),
            session_id=manager.session_id,
            balance=D("1000"),
            equity=D("1000"),
            available_balance=D("1000"),
            realized_pnl=D("0"),
            unrealized_pnl=D("0"),
            position=None,
            mark_price=D("100"),
            engine_peak_equity=D("1000"),
            source_state="STOPPING",
        )
        carried = manager.money_management_runtime_metrics.snapshot()
        assert carried.source_state == "STOPPING"
        assert carried.is_complete is False

        # Session 3 monitoring START must not fail on the carried snapshot.
        r3 = _start_paper_session(manager, config, dispatched, create_ws)
        assert r3["status"] == "started", r3
        session3 = manager.session_id
        assert session3 == session2 + 1
        assert r3["baselineComplete"] is True
        assert manager.money_management_runtime_baseline_session == session3
        fresh = manager.money_management_runtime_metrics.snapshot()
        assert fresh.session_id == session3
        assert fresh.source_state == "RUNNING"
        assert fresh.available is True
        assert fresh.is_complete is True
    finally:
        positions_router_cleanup(manager, previous_positions_engine,
                                 execution_runtime, previous_runtime_engine)


def test_monitoring_start_allowed_with_incomplete_pre_runtime_baseline():
    """START (monitoring) is not blocked; ENTRY remains fail-closed."""
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry
    from backend.runtime.governance_runtime import governance_state

    previous_positions_engine = positions_router.engine
    execution_runtime = (
        getattr(runtime_registry.trading_runtime, "execution_runtime", None)
        if runtime_registry.trading_runtime is not None
        else None
    )
    previous_runtime_engine = (
        getattr(execution_runtime, "engine", None)
        if execution_runtime is not None
        else None
    )
    manager = BotManager()
    manager.configure_money_management_config_provider(
        lambda: _mm_config(D("7.00"))
    )

    def create_ws(**kwargs):
        return SimpleNamespace(
            MARKET_TYPE="spot",
            connected=False,
            start=lambda: None,
            stop=lambda: None,
        )

    manager.set_money_management_runtime_hook(
        lambda event_type, event_key: _dispatch_result("FAILED")
    )
    config = _paper_config()
    governance_previous = dict(governance_state)
    try:
        governance_state.update(governance_previous)
        governance_state["execution_enabled"] = False
        with patch(
            "backend.bot_manager.bot_manager.ExchangeFactory.create_market_ws",
            side_effect=create_ws,
        ), patch("backend.bot_manager.bot_manager.time.sleep"):
            result = manager.start(config)

        assert result["status"] == "started", result
        assert result["baselineComplete"] is False
        assert manager.lifecycle_state == "RUNNING"
        assert governance_state.get("execution_enabled") is False
        assert (
            manager.money_management_runtime_baseline_session
            != manager.session_id
        )
    finally:
        governance_state.clear()
        governance_state.update(governance_previous)
        positions_router_cleanup(manager, previous_positions_engine,
                                 execution_runtime, previous_runtime_engine)


def positions_router_cleanup(manager, previous_positions_engine,
                             execution_runtime, previous_runtime_engine):
    from backend.routers import positions as positions_router
    try:
        positions_router.set_engine(previous_positions_engine)
    except Exception:
        pass
    if execution_runtime is not None:
        try:
            execution_runtime.set_engine(previous_runtime_engine)
        except Exception:
            pass
