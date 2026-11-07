"""Isolated checks for mmObservationCompletedAt.

These tests do not refresh a live account, evaluate risk, or send an order.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.auth.dependencies import require_operator_session
from backend.bot_manager.bot_manager import BotManager
from backend.bot_manager.owner_snapshot import (
    held_runtime_domains,
    merge_owner_snapshot,
    unavailable_owner_snapshot,
)
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
from backend.runtime.governance_runtime import governance_state
from backend.runtime.paper_account_store import PaperAccountStore
from tests.test_mm_stopped_paper_recovery_metrics import persisted as stopped_persisted

D = Decimal
SOURCE = "KUCOIN_FUTURES_READ_ONLY"
PAST = datetime(2020, 1, 1, tzinfo=timezone.utc)
PUBLISHED_AT = "1999-01-01T00:00:00Z"


class _CallingEngine:
    def __init__(self, mode):
        self.mode = mode
        self.balance = 1000.0
        self.pnl = 0.0
        self.unrealized_pnl = 0.0
        self.actual_position = None
        self.peak_equity = D("1000")
        self.latest_price = D("100")
        self.calls = []

    def place_order(self, *args, **kwargs):
        self.calls.append("place_order")

    def create_order(self, *args, **kwargs):
        self.calls.append("create_order")

    def submit_order(self, *args, **kwargs):
        self.calls.append("submit_order")


def _paper_manager():
    manager = BotManager()
    manager.lifecycle_state = "RUNNING"
    manager.session_id = 1
    manager.engine = _CallingEngine("paper")
    manager.refresh_calls = 0

    def _refresh(*_args, **_kwargs):
        manager.refresh_calls += 1
        raise AssertionError("account sync is not part of observation")

    manager._refresh_real_account_snapshot = _refresh
    return manager


def _observe(manager, event_type=None, event_key="observation"):
    return manager._observe_money_management_runtime_metrics(
        {"realizedPnl": D("0")},
        event_type,
        event_key,
    )


def _publish(manager):
    return merge_owner_snapshot(
        unavailable_owner_snapshot(),
        runtime_domains=held_runtime_domains(manager),
        published_at=PUBLISHED_AT,
    )


def _live_snapshot(**overrides):
    payload = {
        "authenticated": True,
        "stale": False,
        "accountSource": SOURCE,
        "balanceSource": SOURCE,
        "positionSource": SOURCE,
        "lastSync": PAST.timestamp(),
        "balance": D("10"),
        "equity": D("10"),
        "availableBalance": D("8"),
        "realizedPnlToday": D("0"),
        "unrealizedPnl": D("0"),
        "positions": [],
    }
    payload.update(overrides)
    return payload


def _live_manager(snapshot):
    manager = _paper_manager()
    manager.engine = _CallingEngine("live")
    manager.real_account_snapshot = snapshot
    return manager


def test_t01_paper_success_notes_completion_after_a_new_snapshot():
    manager = _paper_manager()
    previous = manager.account_snapshot
    observed = _observe(manager)
    assert manager.account_snapshot is not previous
    assert observed.observation_valid is True
    assert observed.mm_observation_completed_at is not None
    assert observed.mm_observation_completed_at >= observed.as_of
    assert observed.mm_observation_input_completeness == "COMPLETE"
    assert observed.mm_observation_input_scope == "PAPER_ENGINE_ACCOUNT"
    assert observed.mm_observation_evidence_revision == observed.revision
    assert observed.as_of != PUBLISHED_AT


def test_t02_paper_invalid_observation_does_not_note():
    manager = _paper_manager()
    manager.engine.peak_equity = "not-a-number"
    observed = _observe(manager)
    assert observed.observation_valid is False
    assert observed.mm_observation_completed_at is None
    assert "mmObservationCompletedAt" not in (_publish(manager)["payload"])


def test_t03_paper_reused_snapshot_does_not_note():
    manager = _paper_manager()
    previous = manager.account_snapshot
    manager.engine.balance = object()
    observed = _observe(manager)
    assert manager.account_snapshot is previous
    assert observed.mm_observation_completed_at is None


def test_t04_live_full_observation_notes_complete():
    manager = _live_manager(_live_snapshot())
    observed = _observe(manager)
    assert observed.observation_valid is True
    assert observed.position_count == 0
    assert observed.mm_observation_input_completeness == "COMPLETE"
    assert observed.mm_observation_input_scope == "LIVE_ACCOUNT_CACHE"
    assert observed.mm_observation_evidence_revision == observed.revision
    fragment = _publish(manager)["payload"]["money_management"]
    assert fragment["mmObservationCompletedAt"] != fragment["producerObservedAt"]
    assert fragment["mmObservationCompletedAt"] != PUBLISHED_AT
    assert manager.refresh_calls == 0


def test_t04_cached_values_without_sources_are_not_complete():
    snapshot = _live_snapshot()
    del snapshot["balanceSource"]
    del snapshot["positionSource"]
    manager = _live_manager(snapshot)
    observed = _observe(manager)
    assert observed.observation_valid is True
    assert observed.balance == D("10")
    assert observed.position_count == 0
    assert observed.mm_observation_completed_at is None


def test_t05_live_balance_only_does_not_note():
    manager = _live_manager(
        _live_snapshot(positionSource=None, stale=True, positions=[{"qty": 1}])
    )
    observed = _observe(manager)
    assert observed.mm_observation_completed_at is None
    assert manager._live_account_input_completeness(
        manager.real_account_snapshot
    ) == "BALANCE_ONLY"


def test_t06_live_position_only_does_not_note():
    manager = _live_manager(
        _live_snapshot(balanceSource=None, stale=True, balance=D("10"), equity=D("10"))
    )
    observed = _observe(manager)
    assert observed.mm_observation_completed_at is None
    assert manager._live_account_input_completeness(
        manager.real_account_snapshot
    ) == "POSITION_ONLY"


def test_t07_live_both_failed_does_not_note():
    manager = _live_manager(
        _live_snapshot(
            balanceSource=None,
            positionSource=None,
            authenticated=False,
            stale=True,
            balance=D("10"),
            positions=[],
        )
    )
    observed = _observe(manager)
    assert observed.mm_observation_completed_at is None
    assert manager._live_account_input_completeness(
        manager.real_account_snapshot
    ) == "NONE"


def test_t08_live_stale_does_not_note():
    manager = _live_manager(_live_snapshot(stale=True))
    observed = _observe(manager)
    assert observed.mm_observation_completed_at is None


def test_t09_live_unauthenticated_does_not_note():
    manager = _live_manager(_live_snapshot(authenticated=False))
    observed = _observe(manager)
    assert observed.mm_observation_completed_at is None


def test_t10_matching_revision_publishes_the_clock():
    manager = _paper_manager()
    observed = _observe(manager)
    fragment = _publish(manager)["payload"]["money_management"]
    assert fragment["evidenceRevision"] == observed.revision
    assert fragment["mmObservationCompletedAt"].endswith("Z")
    assert fragment["inputCompleteness"] == "COMPLETE"
    assert fragment["inputScope"] == "PAPER_ENGINE_ACCOUNT"
    json.dumps(fragment)


def test_t11_revision_mismatch_hides_the_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    manager.money_management_runtime_metrics.begin_runtime_session(
        2,
        PAST + timedelta(days=1),
    )
    current = manager.money_management_runtime_metrics.snapshot()
    assert current.revision != noted.revision
    assert current.mm_observation_completed_at == original
    fragment = _publish(manager)["payload"]["money_management"]
    assert "mmObservationCompletedAt" not in fragment
    assert "evidenceRevision" not in fragment
    assert fragment["producerObservedAt"] != original.isoformat().replace("+00:00", "Z")


def test_t12_session_start_does_not_create_a_clock():
    state = AuthoritativeLossRuntimeMetricsState("runtime-session")
    snapshot = state.begin_runtime_session(1, PAST)
    assert snapshot.revision == 1
    assert snapshot.mm_observation_completed_at is None


def test_t13_restore_does_not_create_a_clock():
    state = AuthoritativeLossRuntimeMetricsState("runtime-restore")
    snapshot = state.restore(stopped_persisted(PAST), "PERSISTED_STATE", PAST)
    assert snapshot.observation_valid is False
    assert snapshot.mm_observation_completed_at is None


def test_t14_peak_recovery_does_not_create_a_clock():
    manager = _paper_manager()
    noted = _observe(manager)
    original = noted.mm_observation_completed_at
    recovered = manager.money_management_runtime_metrics.apply_validated_peak_recovery(
        authority_source=AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY,
        high_water_mark=D("900"),
        current_equity=D("800"),
        as_of=PAST + timedelta(days=2),
    )
    assert recovered.revision != noted.revision
    assert recovered.mm_observation_completed_at == original
    assert recovered.current_equity == noted.current_equity
    assert "mmObservationCompletedAt" not in _publish(manager)["payload"]["money_management"]


def test_t15_owner_snapshot_keeps_numeric_fields_and_separates_clocks():
    manager = _paper_manager()
    manager.engine.balance = 0.0
    manager.engine.unrealized_pnl = 0.0
    observed = _observe(manager)
    document = _publish(manager)
    fragment = document["payload"]["money_management"]
    assert document["publishedAt"] == PUBLISHED_AT
    assert fragment["equity"] == "0.0"
    assert fragment["positionSize"] == 0
    assert fragment["revision"] == observed.revision
    assert fragment["producerObservedAt"] == observed.as_of.isoformat().replace("+00:00", "Z")
    assert fragment["mmObservationCompletedAt"] != document["publishedAt"]
    assert "freshnessPolicy" not in fragment
    assert fragment["freshness"] == "UNKNOWN"


def test_t16_runtime_evidence_stays_unknown():
    manager = _paper_manager()
    _observe(manager)
    evidence = collect_runtime_evidence(_publish(manager))
    domain = evidence["domains"]["moneyManagement"]
    assert domain["runtimeStatus"] == "UNKNOWN"
    assert domain["runtimeFreshness"] == "UNKNOWN"
    assert domain["runtimeStatus"] != "CURRENT"
    assert "mmObservationCompletedAt" in domain["runtimeValues"]
    assert "freshnessPolicy" not in domain["runtimeValues"]
    assert evidence["authority"] == "NONE"
    assert evidence["tradingControl"] == "FORBIDDEN"
    assert evidence["productionRuntimeConnected"] is False


def test_t17_missing_fragment_stays_unavailable():
    evidence = collect_runtime_evidence(unavailable_owner_snapshot())
    domain = evidence["domains"]["moneyManagement"]
    assert domain["runtimeStatus"] == "UNAVAILABLE"
    assert domain["runtimeValues"] is None
    assert domain["runtimeStatus"] != "CURRENT"


def _operator_app(document):
    owner = SimpleNamespace(export_context_snapshot=lambda: document)

    class App:
        state = SimpleNamespace(context_owner_lookup=lambda: owner)

    return App()


def test_t18_advisor_context_does_not_promote_the_clock():
    manager = _paper_manager()
    _observe(manager)
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
    assert "mmObservationCompletedAt" in block
    assert "CURRENT" not in evidence["domains"]["moneyManagement"]["runtimeStatus"]
    assert evidence["tradingControl"] == "FORBIDDEN"


def test_t19_supervisor_context_does_not_promote_the_clock():
    manager = _paper_manager()
    _observe(manager)
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


def test_t20_operator_route_requires_authentication():
    assert PUBLIC_ENDPOINT_ENABLED is False
    assert require_operator_session in {
        getattr(item, "dependency", None) for item in context_router.dependencies
    }
    client = TestClient(create_isolated_context_app())
    response = client.get("/api/ai-context/operator")
    assert response.status_code == 401


def test_t21_public_view_does_not_receive_operator_runtime_evidence():
    manager = _paper_manager()
    _observe(manager)
    document = _publish(manager)
    public = collection_from_owner_document(
        document,
        datetime(2026, 10, 31, tzinfo=timezone.utc),
    ).public_view
    rendered = json.dumps(public)
    assert "mmObservationCompletedAt" not in rendered
    assert "runtimeEvidence" not in public
    assert "evidenceRevision" not in rendered


def test_t22_null_zero_and_false_stay_unchanged():
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
    assert observed.current_equity is None
    assert observed.position_count == 0
    assert observed.observation_valid is True
    noted = state.note_mm_observation_completed(
        completed_at=PAST + timedelta(seconds=1),
        metrics_revision=observed.revision,
        input_scope="PAPER_ENGINE_ACCOUNT",
        input_completeness="COMPLETE",
    )
    assert noted.current_equity is None
    assert noted.position_count == 0
    assert noted.observation_valid is True
    invalid = state.observe(
        as_of=PAST + timedelta(seconds=2),
        session_id=1,
        balance=D("1"),
        equity=D("1"),
        available_balance=D("1"),
        realized_pnl=D("0"),
        unrealized_pnl=D("0"),
        position=[],
        mark_price=D("100"),
        engine_peak_equity="bad",
        source_state="RUNNING",
    )
    assert invalid.observation_valid is False
    refused = state.note_mm_observation_completed(
        completed_at=PAST + timedelta(seconds=3),
        metrics_revision=invalid.revision,
        input_scope="PAPER_ENGINE_ACCOUNT",
        input_completeness="COMPLETE",
    )
    assert refused.mm_observation_completed_at == noted.mm_observation_completed_at
    assert refused.observation_valid is False


def test_t23_note_does_not_change_mm_calculation():
    left = AuthoritativeLossRuntimeMetricsState("runtime-left")
    right = AuthoritativeLossRuntimeMetricsState("runtime-right")
    kwargs = dict(
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
    before = left.observe(**kwargs)
    after_observe = right.observe(**kwargs)
    after = right.note_mm_observation_completed(
        completed_at=PAST + timedelta(seconds=5),
        metrics_revision=after_observe.revision,
        input_scope="PAPER_ENGINE_ACCOUNT",
        input_completeness="COMPLETE",
    )
    assert after.current_equity == before.current_equity
    assert after.current_drawdown_amount == before.current_drawdown_amount
    assert after.current_drawdown_pct == before.current_drawdown_pct
    assert after.peak_equity == before.peak_equity
    assert after.position_count == before.position_count
    assert after.revision == before.revision
    assert after.as_of == before.as_of


def test_t24_observation_does_not_sync_an_account():
    manager = _live_manager(_live_snapshot())
    _observe(manager)
    assert manager.refresh_calls == 0
    assert manager.engine.calls == []


def test_t25_observation_does_not_send_orders():
    manager = _paper_manager()
    _observe(manager)
    assert manager.engine.calls == []
    assert manager.refresh_calls == 0


def _stopped_manager(temp, now, *, age_seconds=0, open_position=False):
    manager = BotManager()
    manager.config = {"mode": "paper"}
    store = PaperAccountStore(f"{temp.name}/paper.json", account_scope="primary")
    manager.paper_account_store = store
    state = store.build_state(
        D("1000"),
        "PAPER_SIMULATION",
        (now - timedelta(seconds=age_seconds)).timestamp(),
    )
    if open_position:
        position = {
            "side": "LONG",
            "coin_qty": 1,
            "mark_price": 100,
            "entry_price": 100,
            "sl": 90,
        }
        state["positionState"] = "OPEN"
        state["position"] = position
        state["positions"] = [position]
    manager.paper_account_state = state
    return manager


def test_stopped_fresh_paper_notes_and_stale_or_invalid_does_not():
    saved = dict(governance_state)
    governance_state.update({"mode": "PAPER", "execution_enabled": False})
    temp = TemporaryDirectory()
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fresh = _stopped_manager(temp, now, open_position=True)
        noted = fresh.initialize_money_management_runtime_metrics(
            stopped_persisted(now), "PERSISTED_STATE", now
        )
        assert noted.observation_valid is True
        assert noted.mm_observation_completed_at is not None
        assert noted.mm_observation_input_scope == "PAPER_ENGINE_ACCOUNT"
        assert noted.mm_observation_evidence_revision == noted.revision

        stale = _stopped_manager(temp, now, age_seconds=91, open_position=True)
        stale_metrics = stale.initialize_money_management_runtime_metrics(
            stopped_persisted(now), "PERSISTED_STATE", now
        )
        assert stale_metrics.mm_observation_completed_at is None

        flat = _stopped_manager(temp, now, open_position=False)
        flat_metrics = flat.initialize_money_management_runtime_metrics(
            stopped_persisted(now), "PERSISTED_STATE", now
        )
        assert flat_metrics.observation_valid is False
        assert flat_metrics.mm_observation_completed_at is None
    finally:
        governance_state.clear()
        governance_state.update(saved)
        temp.cleanup()
