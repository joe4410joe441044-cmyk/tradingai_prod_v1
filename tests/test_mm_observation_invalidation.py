"""Isolated checks for mm observation invalidation.

These tests do not refresh a live account, evaluate risk, or send an order.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory

import backend.config as config
from backend.auth.dependencies import require_operator_session
from backend.bot_manager.bot_manager import BotManager
from backend.context.api_contract import PUBLIC_ENDPOINT_ENABLED
from backend.context.api_router import context_router, create_isolated_context_app
from backend.context.owner_context_bridge import collection_from_owner_document
from backend.context.runtime_evidence import collect_runtime_evidence
from backend.context.shared_answer_context import (
    load_shared_operator_context,
    render_canonical_context_block,
)
from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetricsState,
)
from backend.money_management.loss_persistence_models import (
    AccountingRebaseAuthoritySource,
)
from backend.routers import positions as positions_router
from backend.routers.mode import ModeRequest, set_mode
from backend.runtime import runtime_registry
from backend.runtime.governance_runtime import governance_state
from backend.runtime.paper_account_store import PaperAccountStore
from fastapi.testclient import TestClient
from tests.test_mm_observation_completion_evidence import (
    PAST,
    _live_manager,
    _live_snapshot,
    _observe,
    _operator_app,
    _paper_manager,
    _publish,
)
from tests.test_mm_stopped_paper_recovery_metrics import persisted as stopped_persisted

D = Decimal


def _metrics(manager):
    return manager.money_management_runtime_metrics.snapshot()


def _fragment(manager):
    payload = _publish(manager)["payload"]
    return payload.get("money_management")


def _noted_state():
    state = AuthoritativeLossRuntimeMetricsState("runtime-invalidation")
    observed = state.observe(
        as_of=PAST,
        session_id=1,
        balance=D("1000"),
        equity=D("900"),
        available_balance=D("800"),
        realized_pnl=D("-10"),
        unrealized_pnl=D("-5"),
        position=[],
        mark_price=D("100"),
        engine_peak_equity=D("1000"),
        source_state="RUNNING",
    )
    noted = state.note_mm_observation_completed(
        completed_at=PAST + timedelta(seconds=5),
        metrics_revision=observed.revision,
        input_scope="PAPER_ENGINE_ACCOUNT",
        input_completeness="COMPLETE",
    )
    return state, noted


class _EntryEngine:
    def __init__(self, mode="paper", *, fill=True):
        self.mode = mode
        self.balance = 1000.0
        self.pnl = 0.0
        self.unrealized_pnl = 0.0
        self.actual_position = None
        self.peak_equity = D("1000")
        self.latest_price = D("100")
        self.calls = []
        self.config = {"mode": mode, "dry_run": mode == "paper"}
        self.fill = fill
        self.portfolio = None

    def place_order(self, *args, **kwargs):
        self.calls.append("place_order")

    def create_order(self, *args, **kwargs):
        self.calls.append("create_order")

    def submit_order(self, *args, **kwargs):
        self.calls.append("submit_order")

    def get_price(self):
        return 100

    def preflight_execution_entry(self, action, trace_id):
        return {"allowed": True, "approvedQuantity": 1}

    def clear_execution_entry_preflight(self, trace_id):
        return None

    def try_entry(self, signal):
        if not self.fill:
            return {"reason": "MANUAL_ENTRY_NOT_FILLED"}
        self.actual_position = {
            "entry_authority": "MANUAL",
            "request_id": signal.get("requestId"),
            "position_id": "pos-1",
            "side": signal.get("side"),
            "qty": 1,
        }
        self.balance = 990.0
        return {"filled": True}


class _CloseEngine:
    def __init__(self, *, close=True):
        self.mode = "paper"
        self.balance = 1000.0
        self.pnl = 0.0
        self.unrealized_pnl = 0.0
        self.actual_position = {
            "position_id": "pos-1",
            "side": "LONG",
            "qty": 1,
            "coin_qty": 1,
        }
        self.peak_equity = D("1000")
        self.latest_price = D("100")
        self.calls = []
        self.trade_history = []
        self.pending_order = False
        self.open_orders = []
        self.config = {"mode": "paper", "dry_run": True}
        self.close = close
        self.portfolio = None

    def get_price(self):
        return 100

    def close_position(self, price, reason):
        if not self.close:
            return {"reason": "MANUAL_CLOSE_UNCONFIRMED"}
        self.trade_history.append({"tradeId": "pos-1", "reason": reason})
        self.actual_position = None
        self.balance = 1010.0
        self.pnl = 10.0
        return {"closed": True}

    def place_order(self, *args, **kwargs):
        self.calls.append("place_order")


def _allow_governance(monkeypatch):
    class _Decision:
        def evaluate_entry(self, *args, **kwargs):
            return {"allowed": True}

    monkeypatch.setattr(
        "backend.bot_manager.bot_manager.GovernanceRuntime",
        lambda: _Decision(),
    )


def _prepare_manual(manager):
    manager.pending_order = False
    manager.loop_state = "RUNNING"
    manager.config = {"mode": "paper", "dry_run": True}
    manager._manual_preparation_margin_mode_authority = (
        lambda symbol=None: {
            "known": True,
            "compatible": True,
            "actualMode": "CROSS",
        }
    )
    manager._reconcile_manual_close_quantity = lambda engine, position: True


def test_t01_invalidation_method_first_call_advances_revision():
    state, noted = _noted_state()
    invalidated = state.invalidate_mm_observation_evidence()
    assert invalidated.revision == noted.revision + 1
    assert invalidated.mm_observation_evidence_revision == noted.revision


def test_t02_invalidation_method_second_call_is_a_no_op():
    state, noted = _noted_state()
    first = state.invalidate_mm_observation_evidence()
    second = state.invalidate_mm_observation_evidence()
    assert second.revision == first.revision
    assert second.revision == noted.revision + 1


def test_t03_no_active_evidence_is_a_no_op():
    state = AuthoritativeLossRuntimeMetricsState("runtime-empty")
    before = state.snapshot()
    after = state.invalidate_mm_observation_evidence()
    assert after.revision == before.revision
    assert after.mm_observation_completed_at is None


def test_t04_revision_mismatch_is_a_no_op():
    state, noted = _noted_state()
    state.invalidate_mm_observation_evidence()
    mismatched = state.snapshot()
    assert mismatched.revision != noted.mm_observation_evidence_revision
    again = state.invalidate_mm_observation_evidence()
    assert again.revision == mismatched.revision


def test_t05_timestamp_is_unchanged():
    state, noted = _noted_state()
    invalidated = state.invalidate_mm_observation_evidence()
    assert invalidated.mm_observation_completed_at == noted.mm_observation_completed_at
    assert invalidated.mm_observation_input_scope == "PAPER_ENGINE_ACCOUNT"
    assert invalidated.mm_observation_input_completeness == "COMPLETE"


def test_t06_as_of_is_unchanged():
    state, noted = _noted_state()
    invalidated = state.invalidate_mm_observation_evidence()
    assert invalidated.as_of == noted.as_of


def test_t07_mm_metrics_are_unchanged():
    state, noted = _noted_state()
    invalidated = state.invalidate_mm_observation_evidence()
    assert invalidated.current_equity == noted.current_equity
    assert invalidated.available_balance == noted.available_balance
    assert invalidated.peak_equity == noted.peak_equity
    assert invalidated.current_drawdown_amount == noted.current_drawdown_amount
    assert invalidated.current_drawdown_pct == noted.current_drawdown_pct
    assert invalidated.open_exposure == noted.open_exposure
    assert invalidated.position_count == noted.position_count
    assert invalidated.observation_valid is True


def test_t08_paper_auto_entry_invalidates_before_observe():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    before = manager._money_management_runtime_event_signature()
    manager.engine.actual_position = {
        "side": "LONG",
        "qty": 1,
        "multiplier": 1,
        "coin_qty": 1,
    }
    manager.engine.balance = 990.0
    order = []
    original_observe = manager._observe_money_management_runtime_metrics

    def _observe_later(*args, **kwargs):
        order.append("observe")
        assert "mmObservationCompletedAt" not in _fragment(manager)
        return original_observe(*args, **kwargs)

    manager._observe_money_management_runtime_metrics = _observe_later
    hidden = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before,
        manager.engine.latest_price,
        manager.engine.unrealized_pnl,
    )
    order.append("invalidate")
    assert hidden.revision == noted.revision + 1
    assert hidden.mm_observation_completed_at == original
    manager._observe_money_management_runtime_metrics(
        before,
        "POSITION_UPDATE",
        "auto-entry",
    )
    assert order == ["invalidate", "observe"]
    published = _fragment(manager).get("mmObservationCompletedAt")
    assert published != original.isoformat().replace("+00:00", "Z")


def test_t09_paper_auto_close_invalidates_before_observe():
    manager = _paper_manager()
    manager.engine.actual_position = {
        "side": "LONG",
        "qty": 1,
        "multiplier": 1,
        "coin_qty": 1,
    }
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    before = manager._money_management_runtime_event_signature()
    manager.engine.actual_position = None
    manager.engine.pnl = 10.0
    hidden = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before, manager.engine.latest_price, manager.engine.unrealized_pnl
    )
    assert hidden.mm_observation_completed_at == original
    assert "mmObservationCompletedAt" not in _fragment(manager)
    _observe(manager, "TRADE_CLOSE", "auto-close")
    assert _fragment(manager)["mmObservationCompletedAt"] != (
        original.isoformat().replace("+00:00", "Z")
    )


def test_t10_paper_price_update_invalidates_before_observe():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    before = manager._money_management_runtime_event_signature()
    price_before = manager.engine.latest_price
    unrealized_before = manager.engine.unrealized_pnl
    unchanged = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before, price_before, unrealized_before
    )
    assert unchanged is None
    assert _metrics(manager).revision == noted.revision
    manager.engine.latest_price = D("101")
    manager.engine.unrealized_pnl = 4.0
    hidden = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before, price_before, unrealized_before
    )
    assert hidden.mm_observation_completed_at == original
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t11_paper_manual_entry_invalidates_without_observe(monkeypatch):
    _allow_governance(monkeypatch)
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    manager.engine = _EntryEngine()
    _prepare_manual(manager)
    observed = []
    manager._observe_money_management_runtime_metrics = (
        lambda *args, **kwargs: observed.append("observe")
    )
    result = manager._manual_entry_locked(
        "req-1", "BUY", {}, "BTC-USDT", "paper"
    )
    assert result["reason"] == "MANUAL_ENTRY_FILLED"
    assert observed == []
    current = _metrics(manager)
    assert current.revision == noted.revision + 1
    assert current.mm_observation_completed_at == original
    assert current.current_equity == noted.current_equity
    assert "mmObservationCompletedAt" not in _fragment(manager)
    assert manager.engine.calls == []


def test_t12_paper_manual_entry_rejection_does_not_invalidate(monkeypatch):
    _allow_governance(monkeypatch)
    manager = _paper_manager()
    noted = _observe(manager)
    manager.engine = _EntryEngine(fill=False)
    _prepare_manual(manager)
    result = manager._manual_entry_locked(
        "req-2", "BUY", {}, "BTC-USDT", "paper"
    )
    assert result["denied"] is True
    current = _metrics(manager)
    assert current.revision == noted.revision
    assert _fragment(manager)["evidenceRevision"] == noted.revision


def test_t13_paper_manual_close_invalidates_before_observe():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    manager.engine = _CloseEngine()
    _prepare_manual(manager)
    order = []
    original_observe = manager._observe_money_management_runtime_metrics

    def _observe_later(*args, **kwargs):
        order.append("observe")
        assert "mmObservationCompletedAt" not in _fragment(manager)
        return original_observe(*args, **kwargs)

    manager._observe_money_management_runtime_metrics = _observe_later
    result = manager._manual_close_locked("req-close", {}, None, "paper")
    assert result["reason"] == "MANUAL_CLOSE_FILLED"
    assert order == ["observe"]
    assert _metrics(manager).mm_observation_completed_at != original
    assert manager.engine.calls == []


def test_t14_paper_manual_close_rejection_does_not_invalidate():
    manager = _paper_manager()
    noted = _observe(manager)
    manager.engine = _CloseEngine(close=False)
    _prepare_manual(manager)
    result = manager._manual_close_locked("req-close", {}, None, "paper")
    assert result["denied"] is True
    assert _metrics(manager).revision == noted.revision
    assert _fragment(manager)["evidenceRevision"] == noted.revision


def test_t15_paper_emergency_flatten_invalidates_before_observe():
    saved = dict(governance_state)
    governance_state["execution_enabled"] = False
    try:
        manager = _paper_manager()
        manager.engine.actual_position = {
            "side": "LONG",
            "qty": 1,
            "multiplier": 1,
            "coin_qty": 1,
        }
        noted = _observe(manager)
        original = noted.mm_observation_completed_at

        def flatten_paper_position(reason):
            manager.engine.actual_position = None
            manager.engine.balance = 1100.0
            return {"success": True}

        manager.engine.flatten_paper_position = flatten_paper_position
        manager.stop = lambda: {
            "status": "error",
            "success": False,
            "completed": False,
            "stateUnknown": True,
            "reason": "TEST_STOP_SKIPPED",
        }
        order = []
        original_observe = manager._observe_money_management_runtime_metrics

        def _observe_later(*args, **kwargs):
            order.append("observe")
            assert "mmObservationCompletedAt" not in _fragment(manager)
            assert _metrics(manager).mm_observation_completed_at == original
            return original_observe(*args, **kwargs)

        manager._observe_money_management_runtime_metrics = _observe_later
        manager._run_emergency_orchestrator_locked(
            {"operation_id": "emergency-1"}
        )
        assert order == ["observe"]
        assert manager.engine.calls == []
    finally:
        governance_state.clear()
        governance_state.update(saved)


def test_t16_paper_capital_reset_hides_the_pre_reset_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    temp = TemporaryDirectory()
    try:
        store = PaperAccountStore(f"{temp.name}/paper.json")
        manager.paper_account_store = store
        manager.paper_account_state = store.load()
        manager.pending_order = False
        manager.engine.portfolio = None
        seen = {}
        original_publish = manager._publish_context_snapshot

        def _publish_later(**kwargs):
            seen["fragment"] = _fragment(manager)
            return original_publish(**kwargs)

        manager._publish_context_snapshot = _publish_later
        result = manager.reset_paper_capital(500, "DASHBOARD_MANUAL")
        assert result["success"] is True
        assert "mmObservationCompletedAt" not in seen["fragment"]
        published = _fragment(manager).get("mmObservationCompletedAt")
        assert published != original.isoformat().replace("+00:00", "Z")
        assert manager.engine.calls == []
    finally:
        temp.cleanup()


def test_t17_paper_stop_invalidates_without_a_new_observation():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    manager.engine.stop = lambda: {"status": "stopped"}
    manager.engine.pending_order = False
    manager.ws = None
    manager._preserve_stopped_paper_engine_safety_snapshot = (
        lambda *args, **kwargs: {"preserved": True}
    )
    manager._stopped_paper_snapshot_authority_state = lambda snapshot: {
        "valid": True,
        "position_state": "flat",
        "pending_order_state": "flat",
        "open_order_state": "flat",
    }
    manager._notify_money_management_lifecycle = lambda state: True
    previous_engine = positions_router.engine
    previous_runtime = runtime_registry.trading_runtime
    positions_router.engine = None
    runtime_registry.trading_runtime = None
    try:
        result = manager._stop_locked()
    finally:
        positions_router.engine = previous_engine
        runtime_registry.trading_runtime = previous_runtime
    assert result["status"] == "stopped"
    current = _metrics(manager)
    assert current.revision == noted.revision + 1
    assert current.mm_observation_completed_at == original
    assert current.current_equity == noted.current_equity
    assert "mmObservationCompletedAt" not in _fragment(manager)


def _noted_live():
    manager = _live_manager(_live_snapshot(exchange="kucoin", generation=0))
    noted = _observe(manager)
    assert noted.mm_observation_completed_at is not None
    return manager, noted


def test_t18_live_balance_cache_change_invalidates():
    manager, noted = _noted_live()
    original = noted.mm_observation_completed_at
    updated = dict(manager.real_account_snapshot)
    updated["balance"] = D("11")
    manager._assign_real_account_snapshot(updated)
    current = _metrics(manager)
    assert current.revision == noted.revision + 1
    assert current.mm_observation_completed_at == original
    assert current.current_equity == noted.current_equity
    assert "mmObservationCompletedAt" not in _fragment(manager)
    assert manager.refresh_calls == 0


def test_t19_live_position_cache_change_invalidates():
    manager, noted = _noted_live()
    updated = dict(manager.real_account_snapshot)
    updated["positions"] = [{"side": "LONG", "qty": 1}]
    manager._assign_real_account_snapshot(updated)
    assert _metrics(manager).revision == noted.revision + 1
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t20_live_partial_cache_change_invalidates_and_does_not_note():
    manager, noted = _noted_live()
    original = noted.mm_observation_completed_at
    updated = dict(manager.real_account_snapshot)
    updated["positionSource"] = None
    updated["positions"] = None
    manager._assign_real_account_snapshot(updated)
    observed = _observe(manager)
    assert observed.mm_observation_completed_at == original
    assert observed.mm_observation_evidence_revision == noted.revision
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t21_live_source_change_invalidates():
    manager, noted = _noted_live()
    original = noted.mm_observation_completed_at
    manager._prepare_real_account_snapshot_for_exchange("other-exchange")
    current = _metrics(manager)
    assert current.revision == noted.revision + 1
    assert current.mm_observation_completed_at == original
    assert manager.real_account_snapshot.get("balanceSource") is None
    assert "mmObservationCompletedAt" not in _fragment(manager)
    assert manager.refresh_calls == 0


def test_t22_live_authentication_change_invalidates():
    manager, noted = _noted_live()
    updated = dict(manager.real_account_snapshot)
    updated["authenticated"] = False
    manager._assign_real_account_snapshot(updated)
    assert _metrics(manager).revision == noted.revision + 1
    assert _metrics(manager).mm_observation_completed_at == (
        noted.mm_observation_completed_at
    )
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t23_live_stale_change_invalidates():
    manager, noted = _noted_live()
    import time

    manager.real_account_snapshot["lastSync"] = time.time() - 1000
    manager.real_account_snapshot["stale"] = False
    manager._mark_real_account_stale_if_needed(manager.real_account_snapshot)
    assert manager.real_account_snapshot["stale"] is True
    assert _metrics(manager).revision == noted.revision + 1
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t24_live_loading_only_change_is_a_no_op():
    manager, noted = _noted_live()
    BotManager._refresh_real_account_snapshot(manager, "other")
    # The loading copy does not change the MM projection, so only the
    # following empty commit advances revision once.
    assert _metrics(manager).revision == noted.revision + 1
    assert manager.refresh_calls == 0


def test_t25_live_generation_only_change_is_a_no_op():
    manager, noted = _noted_live()
    manager.account_snapshot_generation = 4
    manager.real_account_snapshot["exchange"] = "kucoin"
    manager.real_account_snapshot["generation"] = 0
    returned = manager._prepare_real_account_snapshot_for_exchange("kucoin")
    assert returned["generation"] == 4
    assert _metrics(manager).revision == noted.revision
    assert _fragment(manager)["evidenceRevision"] == noted.revision


def test_t26_live_identical_copy_is_a_no_op():
    manager, noted = _noted_live()
    import time

    manager.real_account_snapshot["lastSync"] = time.time()
    manager.real_account_snapshot["stale"] = False
    manager._mark_real_account_stale_if_needed(manager.real_account_snapshot)
    assert _metrics(manager).revision == noted.revision
    assert _fragment(manager)["mmObservationCompletedAt"]


def test_t27_live_engine_position_only_is_a_no_op(monkeypatch):
    _allow_governance(monkeypatch)
    manager, noted = _noted_live()
    before = manager._money_management_runtime_event_signature()
    price_before = manager.engine.latest_price
    unrealized_before = manager.engine.unrealized_pnl
    manager.engine.actual_position = {"side": "LONG", "qty": 1}
    manager.engine.latest_price = D("50")
    assert (
        manager._invalidate_mm_observation_if_paper_inputs_changed(
            before, price_before, unrealized_before
        )
        is None
    )
    manager.engine = _EntryEngine("live")
    manager.config = {"mode": "live", "dry_run": False}
    result = manager._manual_entry_locked(
        "req-live", "BUY", {}, "BTC-USDT", "live"
    )
    assert result["reason"] == "MANUAL_ENTRY_FILLED"
    assert _metrics(manager).revision == noted.revision
    assert _fragment(manager)["evidenceRevision"] == noted.revision
    assert manager.refresh_calls == 0


def test_t28_mode_config_only_is_a_no_op():
    manager = _paper_manager()
    noted = _observe(manager)
    previous_mode = config.TRADE_MODE
    previous_allow = config.ALLOW_LIVE
    try:
        result = set_mode(ModeRequest(mode="live"), _operator="tester")
        assert result["success"] is True
        assert _metrics(manager).revision == noted.revision
        assert _fragment(manager)["evidenceRevision"] == noted.revision
    finally:
        config.TRADE_MODE = previous_mode
        config.ALLOW_LIVE = previous_allow


def test_t29_session_start_uses_the_existing_revision_increment():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    calls = []
    manager.money_management_runtime_metrics.invalidate_mm_observation_evidence = (
        lambda: calls.append("invalidate")
    )
    started = manager.money_management_runtime_metrics.begin_runtime_session(
        2,
        PAST + timedelta(days=1),
    )
    assert calls == []
    assert started.revision != noted.revision
    assert started.mm_observation_completed_at == original
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t30_restore_uses_the_existing_revision_increment():
    state = AuthoritativeLossRuntimeMetricsState("runtime-restore")
    restored = state.restore(stopped_persisted(PAST), "PERSISTED_STATE", PAST)
    assert restored.mm_observation_completed_at is None
    assert restored.revision == 1
    again = state.invalidate_mm_observation_evidence()
    assert again.revision == restored.revision


def test_t31_peak_recovery_uses_the_existing_revision_increment():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    calls = []
    manager.money_management_runtime_metrics.invalidate_mm_observation_evidence = (
        lambda: calls.append("invalidate")
    )
    recovered = manager.money_management_runtime_metrics.apply_validated_peak_recovery(
        authority_source=AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY,
        high_water_mark=D("900"),
        current_equity=D("800"),
        as_of=PAST + timedelta(days=2),
    )
    assert calls == []
    assert recovered.revision != noted.revision
    assert recovered.mm_observation_completed_at == original
    assert recovered.current_equity == noted.current_equity
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t32_observation_failure_does_not_republish_the_old_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    before = manager._money_management_runtime_event_signature()
    manager.engine.unrealized_pnl = 7.0
    hidden = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before, manager.engine.latest_price, 0.0
    )
    assert hidden.mm_observation_completed_at == original

    def _fail(*args, **kwargs):
        raise RuntimeError("observe failed")

    manager._observe_money_management_runtime_metrics = _fail
    try:
        manager._observe_money_management_runtime_metrics(before, None, "fail")
    except RuntimeError:
        pass
    current = _metrics(manager)
    assert current.mm_observation_completed_at == original
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t33_partial_observation_does_not_note_a_new_clock():
    manager, noted = _noted_live()
    original = noted.mm_observation_completed_at
    partial = _live_snapshot(positionSource=None, positions=None)
    manager._assign_real_account_snapshot(partial)
    observed = _observe(manager)
    assert observed.mm_observation_input_completeness != "COMPLETE" or (
        observed.mm_observation_completed_at == original
    )
    assert observed.mm_observation_completed_at == original
    assert "mmObservationCompletedAt" not in _fragment(manager)


def test_t34_matching_revision_publishes_the_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    fragment = _fragment(manager)
    assert fragment["evidenceRevision"] == noted.revision
    assert fragment["mmObservationCompletedAt"].endswith("Z")
    assert fragment["inputCompleteness"] == "COMPLETE"
    assert fragment["inputScope"] == "PAPER_ENGINE_ACCOUNT"


def test_t35_revision_mismatch_suppresses_the_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    manager._invalidate_mm_observation_evidence()
    current = _metrics(manager)
    assert current.mm_observation_completed_at == original
    assert current.mm_observation_evidence_revision != current.revision
    assert "mmObservationCompletedAt" not in _fragment(manager)
    assert _fragment(manager)["freshness"] == "UNKNOWN"


def test_t36_owner_snapshot_keeps_numbers_and_hides_the_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    equity = _fragment(manager)["equity"]
    position_size = _fragment(manager)["positionSize"]
    manager._invalidate_mm_observation_evidence()
    fragment = _fragment(manager)
    assert fragment["equity"] == equity
    assert fragment["positionSize"] == position_size
    assert fragment["producerObservedAt"]
    assert "mmObservationCompletedAt" not in fragment
    assert "freshnessPolicy" not in fragment


def test_t37_runtime_evidence_stays_unknown_after_invalidation():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence()
    evidence = collect_runtime_evidence(_publish(manager))
    domain = evidence["domains"]["moneyManagement"]
    assert domain["runtimeStatus"] == "UNKNOWN"
    assert domain["runtimeFreshness"] == "UNKNOWN"
    assert domain["runtimeStatus"] != "CURRENT"
    assert "mmObservationCompletedAt" not in domain["runtimeValues"]
    assert evidence["authority"] == "NONE"
    assert evidence["tradingControl"] == "FORBIDDEN"


def test_t38_missing_fragment_stays_unavailable():
    from backend.bot_manager.owner_snapshot import unavailable_owner_snapshot

    evidence = collect_runtime_evidence(unavailable_owner_snapshot())
    domain = evidence["domains"]["moneyManagement"]
    assert domain["runtimeStatus"] == "UNAVAILABLE"
    assert domain["runtimeValues"] is None
    assert domain["runtimeStatus"] != "CURRENT"


def test_t39_advisor_context_does_not_promote_invalidated_evidence():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence()
    document = _publish(manager)
    attachment = load_shared_operator_context(
        _operator_app(document),
        question="現在のRuntime状態は？",
    )
    block = render_canonical_context_block(attachment)
    evidence = attachment["runtimeEvidence"]
    assert attachment["authority"] == "NONE"
    assert attachment["tradingControl"] == "FORBIDDEN"
    assert evidence["domains"]["moneyManagement"]["runtimeStatus"] == "UNKNOWN"
    assert "mmObservationCompletedAt" not in block
    assert evidence["tradingControl"] == "FORBIDDEN"


def test_t40_supervisor_context_does_not_promote_invalidated_evidence():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence()
    document = _publish(manager)
    attachment = load_shared_operator_context(
        _operator_app(document),
        question="Supervisorはどのような設計？",
    )
    evidence = attachment["runtimeEvidence"]
    assert attachment["authority"] == "NONE"
    assert attachment["tradingControl"] == "FORBIDDEN"
    assert evidence["domains"]["moneyManagement"]["runtimeStatus"] == "UNKNOWN"
    assert evidence["domains"]["executionAuthority"]["runtimeStatus"] != "CURRENT"
    assert evidence["productionRuntimeConnected"] is False


def test_t41_operator_route_requires_authentication():
    assert PUBLIC_ENDPOINT_ENABLED is False
    assert require_operator_session in {
        getattr(item, "dependency", None) for item in context_router.dependencies
    }
    client = TestClient(create_isolated_context_app())
    response = client.get("/api/ai-context/operator")
    assert response.status_code == 401


def test_t42_public_view_does_not_receive_operator_runtime_evidence():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence()
    document = _publish(manager)
    public = collection_from_owner_document(
        document,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
    ).public_view
    rendered = json.dumps(public)
    assert "mmObservationCompletedAt" not in rendered
    assert "runtimeEvidence" not in public
    assert "evidenceRevision" not in rendered


def test_t43_null_zero_and_false_stay_unchanged():
    state = AuthoritativeLossRuntimeMetricsState("runtime-null")
    observed = state.observe(
        as_of=PAST,
        session_id=1,
        balance=None,
        equity=None,
        available_balance=None,
        realized_pnl=None,
        unrealized_pnl=None,
        position=[],
        mark_price=D("100"),
        source_state="RUNNING",
    )
    noted = state.note_mm_observation_completed(
        completed_at=PAST + timedelta(seconds=1),
        metrics_revision=observed.revision,
        input_scope="PAPER_ENGINE_ACCOUNT",
        input_completeness="COMPLETE",
    )
    invalidated = state.invalidate_mm_observation_evidence()
    assert invalidated.current_equity is None
    assert invalidated.position_count == 0
    assert invalidated.observation_valid is True
    assert invalidated.mm_observation_completed_at == noted.mm_observation_completed_at
    manager, noted_live = _noted_live()
    updated = dict(manager.real_account_snapshot)
    updated["authenticated"] = False
    updated["stale"] = False
    manager._assign_real_account_snapshot(updated)
    assert manager.real_account_snapshot["authenticated"] is False
    assert manager.real_account_snapshot["stale"] is False
    assert _metrics(manager).current_equity == noted_live.current_equity


def test_t44_invalidation_does_not_change_mm_calculation():
    left, noted = _noted_state()
    right, _compared = _noted_state()
    invalidated = left.invalidate_mm_observation_evidence()
    assert invalidated.current_equity == right.snapshot().current_equity
    assert invalidated.current_drawdown_amount == noted.current_drawdown_amount
    assert invalidated.current_drawdown_pct == noted.current_drawdown_pct
    assert invalidated.peak_equity == noted.peak_equity
    assert invalidated.position_count == noted.position_count
    assert invalidated.as_of == noted.as_of
    assert invalidated.revision == noted.revision + 1


def test_t45_invalidation_does_not_sync_an_account():
    manager, _noted = _noted_live()
    updated = dict(manager.real_account_snapshot)
    updated["balance"] = D("12")
    manager._assign_real_account_snapshot(updated)
    assert manager.refresh_calls == 0
    assert manager.engine.calls == []


def test_t46_invalidation_does_not_send_orders(monkeypatch):
    _allow_governance(monkeypatch)
    manager = _paper_manager()
    _observe(manager)
    manager.engine = _EntryEngine()
    _prepare_manual(manager)
    result = manager._manual_entry_locked(
        "req-orders", "BUY", {}, "BTC-USDT", "paper"
    )
    assert result["reason"] == "MANUAL_ENTRY_FILLED"
    assert manager.engine.calls == []
    assert manager.refresh_calls == 0
