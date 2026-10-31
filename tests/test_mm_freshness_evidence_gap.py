"""Evidence gaps for MM runtime freshness. CURRENT stays disabled."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.auth.dependencies import require_operator_session
from backend.context.api_contract import PUBLIC_ENDPOINT_ENABLED
from backend.context.api_router import context_router, create_isolated_context_app
from backend.context.owner_context_bridge import collection_from_owner_document
from backend.context.runtime_evidence import collect_runtime_evidence
from backend.context.shared_answer_context import load_shared_operator_context
from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetricsState,
)
from backend.runtime.governance_runtime import governance_state
from backend.runtime.paper_account_store import PaperAccountStore
from tests.test_mm_observation_completion_evidence import (
    PAST,
    PUBLISHED_AT,
    _live_manager,
    _live_snapshot,
    _observe,
    _operator_app,
    _paper_manager,
    _publish,
)
from tests.test_mm_observation_invalidation import (
    _CloseEngine,
    _EntryEngine,
    _allow_governance,
    _fragment,
    _metrics,
    _noted_state,
    _prepare_manual,
)
from tempfile import TemporaryDirectory

SOURCE = "KUCOIN_FUTURES_READ_ONLY"


def _status(document):
    return collect_runtime_evidence(document)["domains"]["moneyManagement"]


def _values(manager):
    return _status(_publish(manager))["runtimeValues"] or {}


def test_t01_missing_fragment_is_unavailable():
    from backend.bot_manager.owner_snapshot import unavailable_owner_snapshot

    domain = _status(unavailable_owner_snapshot())
    assert domain["runtimeStatus"] == "UNAVAILABLE"
    assert domain["runtimeStatus"] != "CURRENT"


def test_t02_present_fragment_is_unknown():
    manager = _paper_manager()
    _observe(manager)
    domain = _status(_publish(manager))
    assert domain["runtimeStatus"] == "UNKNOWN"
    assert domain["runtimeStatus"] != "CURRENT"
    assert domain["runtimeValues"]["equity"] is not None


def test_t03_t05_policy_as_of_and_published_at_do_not_become_current():
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    document = {
        "schemaVersion": "tradingai-owner-snapshot/v1",
        "publishedAt": now,
        "payload": {
            "money_management": {
                "equity": "1",
                "producerObservedAt": now,
                "publishedAt": now,
                "freshnessPolicy": {
                    "source": "moneyManagement",
                    "maximumAgeSeconds": 86400,
                    "futureToleranceSeconds": 5,
                },
            },
            "execution_control": {
                "entryAllowed": False,
                "producerObservedAt": now,
                "freshness": "STALE",
            },
        },
    }
    evidence = collect_runtime_evidence(document)
    money = evidence["domains"]["moneyManagement"]
    execution = evidence["domains"]["executionAuthority"]
    assert money["runtimeStatus"] == "UNKNOWN"
    assert money["runtimeFreshness"] == "UNKNOWN"
    assert money["runtimeStatus"] != "CURRENT"
    assert execution["runtimeStatus"] == "STALE"
    assert execution["runtimeFreshness"] == "STALE"


def test_t06_other_domain_without_a_label_stays_unchanged():
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    document = {
        "schemaVersion": "tradingai-owner-snapshot/v1",
        "payload": {
            "market_selection": {
                "activeSymbol": "XRPUSDTM",
                "producerObservedAt": now,
                "freshnessPolicy": {
                    "source": "moneyManagement",
                    "maximumAgeSeconds": 86400,
                },
            }
        },
    }
    selection = collect_runtime_evidence(document)["domains"]["marketSelection"]
    assert selection["runtimeStatus"] == "UNKNOWN"
    assert selection["runtimeStatus"] != "CURRENT"


def test_t07_t08_reason_follows_revision_and_is_idempotent():
    state, noted = _noted_state()
    original = noted.mm_observation_completed_at
    equity = noted.current_equity
    first = state.invalidate_mm_observation_evidence("PAPER_INPUT_MUTATION")
    assert first.revision == noted.revision + 1
    assert first.mm_observation_completed_at == original
    assert first.as_of == noted.as_of
    assert first.current_equity == equity
    assert first.mm_invalidation_reason == "PAPER_INPUT_MUTATION"
    second = state.invalidate_mm_observation_evidence("PAPER_MANUAL_ENTRY")
    assert second.revision == first.revision
    assert second.mm_invalidation_reason == "PAPER_INPUT_MUTATION"
    assert second.mm_observation_completed_at == original


def test_t09_t10_successful_observe_clears_reason():
    manager = _paper_manager()
    _observe(manager)
    before = manager._money_management_runtime_event_signature()
    price_before = manager.engine.latest_price
    unrealized_before = manager.engine.unrealized_pnl
    manager.engine.latest_price = price_before + 1
    hidden = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before, price_before, unrealized_before
    )
    assert hidden.mm_invalidation_reason == "PAPER_INPUT_MUTATION"
    assert "mmInvalidationReason" in _fragment(manager)
    assert "mmObservationCompletedAt" not in _fragment(manager)
    _observe(manager)
    fragment = _fragment(manager)
    assert "mmObservationCompletedAt" in fragment
    assert "mmInvalidationReason" not in fragment
    assert _metrics(manager).mm_invalidation_reason is None
    assert _status(_publish(manager))["runtimeStatus"] == "UNKNOWN"


def test_t11_failed_observe_preserves_reason():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence("PAPER_INPUT_MUTATION")
    manager.engine.peak_equity = "not-a-number"
    observed = _observe(manager)
    assert observed.observation_valid is False
    assert observed.mm_invalidation_reason == "PAPER_INPUT_MUTATION"
    assert observed.mm_observation_completed_at is not None
    assert observed.revision != observed.mm_observation_evidence_revision
    assert _fragment(manager) is None
    assert _status(_publish(manager))["runtimeStatus"] == "UNAVAILABLE"


def test_t12_t14_paper_input_mutation_reason():
    manager = _paper_manager()
    _observe(manager)
    before = manager._money_management_runtime_event_signature()
    manager.engine.actual_position = {
        "side": "LONG",
        "qty": 1,
        "multiplier": 1,
        "coin_qty": 1,
    }
    hidden = manager._invalidate_mm_observation_if_paper_inputs_changed(
        before, manager.engine.latest_price, manager.engine.unrealized_pnl
    )
    assert hidden.mm_invalidation_reason == "PAPER_INPUT_MUTATION"
    close_manager = _paper_manager()
    close_manager.engine.actual_position = {
        "side": "LONG",
        "qty": 1,
        "multiplier": 1,
        "coin_qty": 1,
    }
    _observe(close_manager)
    before_close = close_manager._money_management_runtime_event_signature()
    close_manager.engine.actual_position = None
    close_manager.engine.pnl = 10.0
    closed = close_manager._invalidate_mm_observation_if_paper_inputs_changed(
        before_close,
        close_manager.engine.latest_price,
        close_manager.engine.unrealized_pnl,
    )
    assert closed.mm_invalidation_reason == "PAPER_INPUT_MUTATION"


def test_t15_paper_manual_entry_reason_remains(monkeypatch):
    _allow_governance(monkeypatch)
    manager = _paper_manager()
    _observe(manager)
    manager.engine = _EntryEngine()
    _prepare_manual(manager)
    result = manager._manual_entry_locked(
        "req-1", "BUY", {}, "BTC-USDT", "paper"
    )
    assert result["reason"] == "MANUAL_ENTRY_FILLED"
    fragment = _fragment(manager)
    assert fragment["mmInvalidationReason"] == "PAPER_MANUAL_ENTRY"
    assert "mmObservationCompletedAt" not in fragment
    assert _status(_publish(manager))["runtimeStatus"] == "UNKNOWN"
    assert manager.engine.calls == []


def test_t16_paper_manual_close_reason_is_cleared_by_the_new_note():
    manager = _paper_manager()
    _observe(manager)
    manager.engine = _CloseEngine()
    _prepare_manual(manager)
    seen = {}
    original = manager._observe_money_management_runtime_metrics

    def _observe_later(*args, **kwargs):
        seen["reason"] = _metrics(manager).mm_invalidation_reason
        return original(*args, **kwargs)

    manager._observe_money_management_runtime_metrics = _observe_later
    result = manager._manual_close_locked("req-close", {}, None, "paper")
    assert result["reason"] == "MANUAL_CLOSE_FILLED"
    assert seen["reason"] == "PAPER_MANUAL_CLOSE"
    assert _metrics(manager).mm_invalidation_reason is None
    assert "mmInvalidationReason" not in _fragment(manager)


def test_t17_paper_emergency_flatten_reason():
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
        _observe(manager)
        manager.engine.flatten_paper_position = lambda reason: (
            setattr(manager.engine, "actual_position", None)
            or setattr(manager.engine, "balance", 1100.0)
            or {"success": True}
        )
        manager.stop = lambda: {"status": "error", "success": False}
        seen = {}
        original = manager._observe_money_management_runtime_metrics

        def _observe_later(*args, **kwargs):
            seen["reason"] = _metrics(manager).mm_invalidation_reason
            return original(*args, **kwargs)

        manager._observe_money_management_runtime_metrics = _observe_later
        manager._run_emergency_orchestrator_locked({"operation_id": "emergency-gap"})
        assert seen["reason"] == "PAPER_EMERGENCY_FLATTEN"
        assert manager.engine.calls == []
    finally:
        governance_state.clear()
        governance_state.update(saved)


def test_t18_paper_capital_reset_reason_before_the_new_note():
    manager = _paper_manager()
    _observe(manager)
    temp = TemporaryDirectory()
    try:
        store = PaperAccountStore(f"{temp.name}/paper.json")
        manager.paper_account_store = store
        manager.paper_account_state = store.load()
        manager.pending_order = False
        manager.engine.portfolio = None
        seen = {}
        original = manager._publish_context_snapshot

        def _publish_later(**kwargs):
            seen["reason"] = _fragment(manager).get("mmInvalidationReason")
            return original(**kwargs)

        manager._publish_context_snapshot = _publish_later
        result = manager.reset_paper_capital(500, "DASHBOARD_MANUAL")
        assert result["success"] is True
        assert seen["reason"] == "PAPER_CAPITAL_RESET"
        assert _metrics(manager).mm_invalidation_reason is None
    finally:
        temp.cleanup()


def test_t19_paper_stop_reason_remains():
    from backend.routers import positions as positions_router
    from backend.runtime import runtime_registry

    manager = _paper_manager()
    _observe(manager)
    manager._preserve_stopped_paper_engine_safety_snapshot = lambda: {"ok": True}
    manager._stopped_paper_snapshot_authority_state = lambda snapshot: {
        "valid": True,
        "position_state": "flat",
        "pending_order_state": "flat",
        "open_order_state": "flat",
    }
    manager._notify_money_management_lifecycle = lambda state: True
    manager.engine.stop = lambda: {"status": "stopped"}
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
    fragment = _fragment(manager)
    assert fragment["mmInvalidationReason"] == "PAPER_RUNTIME_STOP"
    assert fragment["producerLifecycle"] == "STOPPED"
    assert fragment["producerLifecycle"] != "ACTIVE"
    assert "mmObservationCompletedAt" not in fragment
    assert _status(_publish(manager))["runtimeStatus"] == "UNKNOWN"


def test_t20_t24_live_cache_reasons_and_noop():
    manager = _live_manager(_live_snapshot(generation=3))
    noted = _observe(manager)
    assert noted.live_balance_source == SOURCE
    assert noted.live_authenticated is True
    assert noted.live_stale is False
    assert noted.live_snapshot_generation == 3
    assert noted.live_source_observed_at == PAST
    fragment = _fragment(manager)
    assert fragment["liveBalanceSource"] == SOURCE
    assert fragment["livePositionSource"] == SOURCE
    assert fragment["liveAuthenticated"] is True
    assert fragment["liveStale"] is False
    assert fragment["liveSnapshotGeneration"] == 3
    assert "liveSourceObservedAt" in fragment

    balance = dict(manager.real_account_snapshot)
    balance["balance"] = 11
    manager._assign_real_account_snapshot(balance)
    assert _metrics(manager).mm_invalidation_reason == "LIVE_ACCOUNT_CACHE_MUTATION"
    assert "liveBalanceSource" not in _fragment(manager)

    manager = _live_manager(_live_snapshot(generation=3))
    _observe(manager)
    source = dict(manager.real_account_snapshot)
    source["balanceSource"] = "OTHER"
    manager._assign_real_account_snapshot(source)
    assert _metrics(manager).mm_invalidation_reason == "LIVE_SOURCE_CHANGED"

    manager = _live_manager(_live_snapshot(generation=3))
    _observe(manager)
    auth = dict(manager.real_account_snapshot)
    auth["authenticated"] = False
    manager._assign_real_account_snapshot(auth)
    assert _metrics(manager).mm_invalidation_reason == "LIVE_AUTHENTICATION_CHANGED"

    manager = _live_manager(_live_snapshot(generation=3))
    _observe(manager)
    stale = dict(manager.real_account_snapshot)
    stale["stale"] = True
    manager._assign_real_account_snapshot(stale)
    assert _metrics(manager).mm_invalidation_reason == "LIVE_CACHE_STALE"

    manager = _live_manager(_live_snapshot(generation=3))
    noted = _observe(manager)
    manager.engine.actual_position = {"side": "LONG", "qty": 9}
    copied = dict(manager.real_account_snapshot)
    manager._assign_real_account_snapshot(copied)
    assert _metrics(manager).revision == noted.revision
    assert _metrics(manager).mm_invalidation_reason is None
    assert manager.refresh_calls == 0
    assert manager.engine.calls == []


def test_t25_running_lifecycle_is_not_current():
    manager = _paper_manager()
    _observe(manager)
    fragment = _fragment(manager)
    assert fragment["producerLifecycle"] == "RUNNING"
    assert fragment["producerLifecycle"] != "ACTIVE"
    assert "producerLifecycleChangedAt" in fragment
    assert fragment["producerLifecycleChangedAt"] != fragment["mmObservationCompletedAt"]
    assert "liveBalanceSource" not in fragment
    domain = _status(_publish(manager))
    assert domain["runtimeStatus"] == "UNKNOWN"
    assert domain["runtimeValues"]["producerLifecycle"] == "RUNNING"


def test_t27_new_session_drops_the_previous_reason():
    state, noted = _noted_state()
    state.begin_runtime_session(1, PAST + timedelta(days=1))
    observed = state.observe(
        as_of=PAST + timedelta(days=1, seconds=1),
        session_id=1,
        balance=noted.balance,
        equity=noted.current_equity,
        available_balance=noted.available_balance,
        realized_pnl=noted.realized_pnl,
        unrealized_pnl=noted.unrealized_pnl,
        position=[],
        mark_price=noted.current_equity,
        engine_peak_equity=noted.peak_equity,
        source_state="RUNNING",
    )
    state.note_mm_observation_completed(
        completed_at=PAST + timedelta(days=1, seconds=2),
        metrics_revision=observed.revision,
        input_scope="PAPER_ENGINE_ACCOUNT",
        input_completeness="COMPLETE",
    )
    state.invalidate_mm_observation_evidence("PAPER_INPUT_MUTATION")
    same = state.begin_runtime_session(1, PAST + timedelta(days=1, seconds=3))
    assert same.mm_invalidation_reason == "PAPER_INPUT_MUTATION"
    restarted = state.begin_runtime_session(2, PAST + timedelta(days=2))
    assert restarted.mm_invalidation_reason is None
    assert restarted.live_balance_source is None
    assert restarted.mm_observation_completed_at is not None
    assert restarted.revision != restarted.mm_observation_evidence_revision


def test_t28_t31_owner_and_runtime_projection():
    manager = _live_manager(_live_snapshot(generation=4))
    _observe(manager)
    domain = _status(_publish(manager))
    assert domain["runtimeStatus"] == "UNKNOWN"
    assert domain["runtimeValues"]["liveBalanceSource"] == SOURCE
    assert domain["runtimeValues"]["producerLifecycle"] == "RUNNING"
    assert "mmInvalidationReason" not in domain["runtimeValues"]
    manager._invalidate_mm_observation_evidence("LIVE_ACCOUNT_CACHE_MUTATION")
    hidden = _status(_publish(manager))
    assert hidden["runtimeStatus"] == "UNKNOWN"
    assert hidden["runtimeStatus"] != "STALE"
    assert hidden["runtimeValues"]["mmInvalidationReason"] == (
        "LIVE_ACCOUNT_CACHE_MUTATION"
    )
    assert "mmObservationCompletedAt" not in hidden["runtimeValues"]
    assert "liveBalanceSource" not in hidden["runtimeValues"]
    from backend.bot_manager.owner_snapshot import unavailable_owner_snapshot

    missing = _status(unavailable_owner_snapshot())
    assert missing["runtimeStatus"] == "UNAVAILABLE"


def test_t32_t33_advisor_and_supervisor_share_one_status():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence("PAPER_MANUAL_ENTRY")
    document = _publish(manager)
    advisor = load_shared_operator_context(
        _operator_app(document),
        question="現在のRuntime状態は？",
    )
    supervisor = load_shared_operator_context(
        _operator_app(document),
        question="Supervisorはどのような設計？",
    )
    advisor_domain = advisor["runtimeEvidence"]["domains"]["moneyManagement"]
    supervisor_domain = supervisor["runtimeEvidence"]["domains"]["moneyManagement"]
    assert advisor_domain["runtimeStatus"] == "UNKNOWN"
    assert supervisor_domain["runtimeStatus"] == "UNKNOWN"
    assert advisor_domain["runtimeValues"]["mmInvalidationReason"] == "PAPER_MANUAL_ENTRY"
    assert supervisor_domain["runtimeValues"]["mmInvalidationReason"] == "PAPER_MANUAL_ENTRY"
    assert advisor["authority"] == supervisor["authority"] == "NONE"
    assert advisor["tradingControl"] == supervisor["tradingControl"] == "FORBIDDEN"


def test_t34_operator_route_is_401():
    assert PUBLIC_ENDPOINT_ENABLED is False
    assert require_operator_session in {
        getattr(item, "dependency", None) for item in context_router.dependencies
    }
    response = TestClient(create_isolated_context_app()).get("/api/ai-context/operator")
    assert response.status_code == 401


def test_t35_public_view_hides_the_new_evidence():
    manager = _paper_manager()
    _observe(manager)
    manager._invalidate_mm_observation_evidence("PAPER_MANUAL_ENTRY")
    public = collection_from_owner_document(
        _publish(manager),
        datetime(2026, 10, 31, tzinfo=timezone.utc),
    ).public_view
    rendered = json.dumps(public)
    assert "runtimeEvidence" not in public
    for name in (
        "mmInvalidationReason",
        "PAPER_MANUAL_ENTRY",
        "producerLifecycle",
        "liveBalanceSource",
        "liveAuthenticated",
        "mmObservationCompletedAt",
    ):
        assert name not in rendered


def test_t36_t39_no_sync_orders_or_calculation_change():
    manager = _live_manager(_live_snapshot(generation=1))
    noted = _observe(manager)
    equity = noted.current_equity
    updated = dict(manager.real_account_snapshot)
    updated["balance"] = 12
    manager._assign_real_account_snapshot(updated)
    assert manager.refresh_calls == 0
    assert manager.engine.calls == []
    current = _metrics(manager)
    assert current.current_equity == equity
    assert current.as_of == noted.as_of
    assert current.mm_observation_completed_at == noted.mm_observation_completed_at


def test_published_at_is_not_the_completion_clock():
    manager = _paper_manager()
    _observe(manager)
    assert _publish(manager)["publishedAt"] == PUBLISHED_AT
    assert _fragment(manager)["mmObservationCompletedAt"] != PUBLISHED_AT
