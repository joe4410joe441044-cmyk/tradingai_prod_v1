"""Offline tests for explicit snapshot injection.

These tests call the real position, cycle, and supervisor readers through the
injection boundary. They do not import the production application.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import socket

from backend.context import SCHEMA_VERSION, collect_runtime_context, view_to_json
from backend.context.api_contract import (
    PRODUCTION_API_AVAILABLE,
    PRODUCTION_RUNTIME_CONNECTED,
    PUBLIC_ENDPOINT_ENABLED,
)
from backend.context.collector_contract import READER_NOT_INJECTED
from backend.context.runtime_reader_contract import RUNTIME_INSTANCE_NOT_INJECTED
from backend.context.context_views import DEFAULT_VIEW_MAX_BYTES
from backend.context.injection_boundary import inject_verified_runtime_snapshots
from backend.context.injection_contract import MAX_STRING
from backend.context.schema import ValueState
from backend.context.serializer import to_canonical_json
import backend.context.runtime_reader_adapter as adapter_module
from backend.runtime.current_position_view import current_position
from backend.runtime.cycle_diagnostics import build_trading_cycle_diagnostics
from backend.supervisor.snapshot_builder import build_supervisor_snapshot
from tests.test_ai_context_support import (
    FIXED_NOW,
    FRESHNESS_POLICY,
    bot_payload,
    governance_payload,
    health_payload,
    money_management_payload,
)

REPO = Path(__file__).resolve().parents[1]
PACK_AT = FIXED_NOW + timedelta(hours=1)
SECRET = "SECRET_BB4F_TOKEN"
BOUNDARY = (REPO / "backend/context/injection_boundary.py").read_text(encoding="utf-8")
CONTRACT = (REPO / "backend/context/injection_contract.py").read_text(encoding="utf-8")
ROUTER = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
MAIN = (REPO / "backend/main.py").read_text(encoding="utf-8")


def _fields(section):
    return {item.name: item for item in section.fields}


def _paper(now: float):
    return {
        "available": True,
        "lastUpdate": now,
        "positionState": "OPEN",
        "unrealizedPnl": 1.25,
        "positions": [
            {
                "symbol": "XRPUSDTM",
                "side": "LONG",
                "qty": 1,
                "entry_price": 0.5,
                "entry_time": now - 30,
                "entry_authority": "MANUAL",
                "coin_qty": 10,
            }
        ],
    }


def _inject_position(**kwargs):
    observed = kwargs.pop("observed_at", FIXED_NOW)
    return inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        position_account=kwargs.pop("account", _paper(FIXED_NOW.timestamp())),
        position_mode=kwargs.pop("mode", "PAPER"),
        position_observed_at=observed,
        **kwargs,
    )


def _execution(**overrides):
    payload = {
        "selectedMode": "BOT",
        "tradeMode": "MANUAL",
        "controlAuthority": "BOT",
        "entryAuthority": "MANUAL",
        "botState": "STOPPED",
        "loopState": "IDLE",
        "emergencyState": "ARMED",
        "sourceEvaluatedAt": "2026-10-25T00:00:00Z",
        "freshness": "FRESH",
    }
    payload.update(overrides)
    return payload


def _cycle(current: str, evaluation: str):
    return {
        "trading_decision": {"cycleId": current},
        "trading_cycle_runtime_result": {
            "strategyOutput": {
                "strategy": {"entryReadiness": {"cycleId": evaluation}}
            }
        },
    }


def _supervisor():
    return dict(
        supervisor_bot_status=bot_payload(),
        supervisor_governance_status=governance_payload(),
        supervisor_money_management_status=money_management_payload(),
        supervisor_health_payload=health_payload(),
        supervisor_captured_at=FIXED_NOW,
        supervisor_freshness_policy=FRESHNESS_POLICY,
    )


def test_01_bb4d_router_and_flags_remain():
    assert MAIN.count("app.include_router(context_router)") == 1
    assert "inject_verified_runtime_snapshots" not in MAIN
    assert "inject_verified_runtime_snapshots" not in ROUTER
    assert PUBLIC_ENDPOINT_ENABLED is False
    assert PRODUCTION_API_AVAILABLE is False
    assert PRODUCTION_RUNTIME_CONNECTED is False


def test_02_injection_boundary_is_explicit():
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT)
    assert result.connected_readers == ()
    assert result.runtime_instance_injected is False
    assert result.adapter_failures[0].category == RUNTIME_INSTANCE_NOT_INJECTED


def test_03_explicit_supervisor_input_uses_real_builder(monkeypatch):
    calls = {"count": 0}
    real = build_supervisor_snapshot

    def wrapped(**kwargs):
        calls["count"] += 1
        return real(**kwargs)

    monkeypatch.setattr(adapter_module, "build_supervisor_snapshot", wrapped)
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **_supervisor())
    assert calls["count"] == 1
    assert result.connected_readers == ("build_supervisor_snapshot",)
    assert result.collection.production_runtime_connected is False


def test_04_explicit_position_input_uses_current_position(monkeypatch):
    calls = {"count": 0}
    real = current_position

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "current_position", wrapped)
    result = _inject_position()
    fields = _fields(result.collection.context.position)
    assert calls["count"] == 1
    assert fields["status"].value == "OPEN"
    assert fields["mode"].value == "PAPER"
    assert fields["side"].value == "LONG"
    assert result.collection.context.position.meta.observedAt == FIXED_NOW
    assert result.collection.context.generatedAt == PACK_AT


def test_05_explicit_cycle_input_uses_real_diagnostics(monkeypatch):
    calls = {"count": 0}
    real = build_trading_cycle_diagnostics

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "build_trading_cycle_diagnostics", wrapped)
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        cycle_evaluated_at=FIXED_NOW,
        **_cycle("cycle-1", "cycle-1"),
    )
    assert calls["count"] == 1
    assert "build_trading_cycle_diagnostics" in result.connected_readers
    assert _fields(result.collection.context.tradingCycle)["stepCount"].value == 15


def test_06_no_input_stays_not_injected():
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT)
    assert {item.category for item in result.collection.failures} == {READER_NOT_INJECTED}
    assert _fields(result.collection.context.position).get("status") is None or (
        _fields(result.collection.context.position)["status"].value != "OPEN"
    )


def test_07_partial_input_keeps_position_and_leaves_account_empty():
    result = _inject_position()
    assert _fields(result.collection.context.position)["status"].value == "OPEN"
    assert any(
        item.source == "account" and item.category == READER_NOT_INJECTED
        for item in result.collection.failures
    )


def test_08_invalid_input_schema_is_rejected():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        position_account=["not-a-snapshot"],
        position_mode="PAPER",
        position_observed_at=FIXED_NOW,
    )
    assert any(item.source == "position" and item.category == "READER_REJECTED" for item in result.adapter_failures)
    status = _fields(result.collection.context.position).get("status")
    assert status is None or status.value != "OPEN"


def test_09_naive_timestamp_is_rejected(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("called")

    monkeypatch.setattr(adapter_module, "current_position", boom)
    naive = datetime(2026, 10, 25, 0, 0, 0)
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        position_account=_paper(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_observed_at=naive,
    )
    assert any(item.source == "position" and item.category == "READER_REJECTED" for item in result.adapter_failures)


def test_10_invalid_cycle_id_is_rejected(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("called")

    monkeypatch.setattr(adapter_module, "build_trading_cycle_diagnostics", boom)
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        trading_decision={"cycleId": 15},
        cycle_evaluated_at=FIXED_NOW,
    )
    assert any(
        item.source == "trading_cycle" and item.category == "READER_REJECTED"
        for item in result.adapter_failures
    )
    assert "15" not in "".join(item.category for item in result.adapter_failures)


def test_11_caller_mapping_is_not_mutated():
    account = _paper(FIXED_NOW.timestamp())
    before = deepcopy(account)
    _inject_position(account=account)
    assert account == before


def test_12_nested_mapping_is_not_shared():
    account = _paper(FIXED_NOW.timestamp())
    result = _inject_position(account=account)
    account["positions"][0]["qty"] = 99
    account["positions"][0]["symbol"] = "CHANGED"
    fields = _fields(result.collection.context.position)
    assert fields["symbol"].value == "XRPUSDTM"
    assert fields["quantity"].value == 10


def test_13_oversized_input_is_rejected():
    account = _paper(FIXED_NOW.timestamp())
    account["note"] = "x" * (MAX_STRING + 1)
    result = _inject_position(account=account)
    assert any(item.source == "position" and item.category == "READER_REJECTED" for item in result.adapter_failures)
    assert "xxxx" not in to_canonical_json(result.collection.context)


def test_14_reader_exception_text_is_absent(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError(f"path=/tmp/hidden token={SECRET}")

    monkeypatch.setattr(adapter_module, "current_position", boom)
    result = _inject_position()
    rendered = to_canonical_json(result.collection.context) + view_to_json(result.collection.operator_view)
    assert SECRET not in rendered
    assert "hidden" not in rendered
    assert all(not hasattr(item, "message") for item in result.adapter_failures)


def test_15_cycle_failure_does_not_drop_position(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(adapter_module, "build_trading_cycle_diagnostics", boom)
    result = _inject_position(
        trading_decision={"timestamp": "2026-10-25T00:00:00Z"},
        cycle_evaluated_at=FIXED_NOW,
    )
    assert _fields(result.collection.context.position)["status"].value == "OPEN"
    assert any(item.source == "trading_cycle" and item.category == "READER_FAILED" for item in result.adapter_failures)
    assert SECRET not in to_canonical_json(result.collection.context)


def test_16_paper_and_live_stay_separate():
    paper = _inject_position()
    live = _inject_position(account=_paper(FIXED_NOW.timestamp()), mode="LIVE")
    assert _fields(paper.collection.context.position)["mode"].value == "PAPER"
    assert _fields(paper.collection.context.position)["status"].value == "OPEN"
    assert _fields(live.collection.context.position)["status"].value != "OPEN"


def test_17_bot_and_manual_stay_distinct():
    payload = _execution()
    before = deepcopy(payload)
    fields = _fields(
        inject_verified_runtime_snapshots(
            generated_at=PACK_AT,
            execution_projection=payload,
        ).collection.context.executionControl
    )
    assert payload == before
    assert fields["selectedMode"].value == "BOT"
    assert fields["tradeMode"].value == "MANUAL"
    assert fields["modeMismatch"].value == "TRUE"


def test_18_flat_is_not_unknown():
    now = FIXED_NOW.timestamp()
    flat = _inject_position(
        account={"available": True, "lastUpdate": now, "positionState": "FLAT", "positions": []}
    )
    unknown = _inject_position(
        account={"available": True, "lastUpdate": now, "positionState": "OPEN", "positions": []}
    )
    assert _fields(flat.collection.context.position)["status"].value == "FLAT"
    assert _fields(unknown.collection.context.position)["status"].value == "UNKNOWN"


def test_19_current_requires_a_producer_time():
    untimed = inject_verified_runtime_snapshots(generated_at=PACK_AT, **_cycle("cycle-live", "cycle-live"))
    untimed_scope = _fields(untimed.collection.context.tradingCycle).get("diagnosticScope")
    assert untimed_scope is None or untimed_scope.value != "CURRENT"
    assert any(item.source == "trading_cycle" and item.category == "READER_REJECTED" for item in untimed.adapter_failures)

    timed = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        cycle_evaluated_at=FIXED_NOW,
        **_cycle("cycle-live", "cycle-live"),
    )
    cycle = timed.collection.context.tradingCycle
    assert _fields(cycle)["diagnosticScope"].value == "CURRENT"
    assert cycle.meta.observedAt == FIXED_NOW
    assert cycle.meta.observedAt != PACK_AT


def test_20_historical_cycle_is_not_promoted():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        cycle_evaluated_at=FIXED_NOW - timedelta(days=5),
        **_cycle("cycle-now", "cycle-old"),
    )
    cycle = result.collection.context.tradingCycle
    assert _fields(cycle)["diagnosticScope"].value == "HISTORICAL"
    assert cycle.meta.freshness.name == "STALE"
    assert cycle.meta.observedAt != PACK_AT


def test_21_cycle_without_ids_stays_unknown():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        trading_decision={"timestamp": "2026-10-20T00:00:00Z"},
    )
    assert _fields(result.collection.context.tradingCycle)["diagnosticScope"].value == "UNKNOWN"


def test_22_step_10_and_13_stay_unknown():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        trading_decision={"timestamp": "2026-10-25T00:00:00Z"},
        cycle_evaluated_at=FIXED_NOW,
    )
    fields = _fields(result.collection.context.tradingCycle)
    assert fields["step.10.status"].value == "UNKNOWN"
    assert fields["step.13.status"].value == "UNKNOWN"


def test_23_account_passthrough_does_not_invent_currency_or_zero():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        account_projection={
            "selectedMode": "PAPER",
            "paperAccount": {
                "balance": 11.5,
                "available": True,
                "lastUpdate": "2026-10-25T00:00:00Z",
                "freshness": "FRESH",
            },
            "realAccount": {
                "balance": 77.25,
                "lastSync": "2026-10-25T00:00:00Z",
                "freshness": "FRESH",
            },
        },
    )
    fields = _fields(result.collection.context.account)
    assert fields["paperBalance"].value == 11.5
    assert fields["liveBalance"].value == 77.25
    assert fields["paperEquity"].value != 0
    assert fields["paperEquity"].state is ValueState.UNAVAILABLE
    assert fields["paperCurrency"].state is ValueState.UNAVAILABLE


def test_24_mm_passthrough_does_not_alias_trailing():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        mm_projection={
            "availableCapital": "25",
            "trailing_stop_distance_percent": "3",
            "sourceUpdatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(result.collection.context.smallAccount)
    assert fields["availableCapital"].value == "25"
    assert fields["trailingPercent"].state is ValueState.UNAVAILABLE
    assert fields["takeProfitPercent"].state is ValueState.UNAVAILABLE
    assert fields["timeExitSeconds"].state is ValueState.UNAVAILABLE


def test_25_execution_passthrough_fail_closes_non_bool():
    result = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        execution_projection=_execution(realOrderAllowed="true"),
    )
    fields = _fields(result.collection.context.executionControl)
    assert fields["realOrderAllowed"].value is False
    assert fields["realOrderAllowed"].state is ValueState.UNKNOWN
    assert fields["realOrderAllowedEvidence"].value == "FAIL_CLOSED"
    explicit = inject_verified_runtime_snapshots(
        generated_at=PACK_AT,
        execution_projection=_execution(realOrderAllowed=True),
    )
    allowed = _fields(explicit.collection.context.executionControl)["realOrderAllowed"]
    assert allowed.value is True
    assert allowed.state is ValueState.PRESENT


def test_26_get_bot_manager_is_not_referenced():
    assert "get_bot_manager(" not in BOUNDARY
    assert "get_bot_manager(" not in CONTRACT
    assert "BotManager(" not in BOUNDARY


def test_27_get_status_is_not_referenced():
    assert "get_status(" not in BOUNDARY
    assert "get_status(" not in CONTRACT


def test_28_get_result_is_not_referenced():
    assert "get_result(" not in BOUNDARY
    assert "get_result(" not in CONTRACT


def test_29_exchange_client_is_not_opened(monkeypatch):
    def fail_socket(*_args, **_kwargs):
        raise AssertionError("socket")

    monkeypatch.setattr(socket, "socket", fail_socket)
    assert "KucoinTradeClient" not in BOUNDARY
    result = _inject_position()
    assert _fields(result.collection.context.position)["status"].value == "OPEN"


def test_30_production_startup_is_not_referenced():
    assert "backend.main" not in BOUNDARY
    assert "startup_event" not in BOUNDARY
    assert "get_control_plane" not in BOUNDARY
    assert "inject_verified_runtime_snapshots" not in MAIN


def test_31_authority_mapping_is_not_mutated():
    payload = _execution()
    before = deepcopy(payload)
    inject_verified_runtime_snapshots(generated_at=PACK_AT, execution_projection=payload)
    assert payload == before
    assert "set_authority" not in BOUNDARY


def test_32_emergency_mapping_is_not_mutated():
    payload = _execution()
    before = deepcopy(payload)
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, execution_projection=payload)
    assert payload == before
    assert _fields(result.collection.context.executionControl)["emergencyState"].value == "ARMED"
    assert "trigger_emergency" not in BOUNDARY


def test_33_context_safety_forbids_live_orders():
    result = _inject_position()
    safety = result.collection.context.safety
    assert safety.liveOrder is False
    assert safety.orderWrite is False
    assert safety.runtimeWrite is False
    assert "place_order" not in BOUNDARY


def test_34_collector_compatibility():
    result = _inject_position()
    assert result.collection.production_runtime_connected is False
    assert result.collection.context.schemaVersion == SCHEMA_VERSION
    assert result.collection.operator_view["view"] == "OPERATOR_CONTEXT"


def test_35_composer_compatibility():
    result = _inject_position(**_cycle("cycle-a", "cycle-b"), cycle_evaluated_at=FIXED_NOW)
    assert result.collection.context.schemaVersion == "tradingai-context/v1"
    assert _fields(result.collection.context.position)["status"].value == "OPEN"
    assert _fields(result.collection.context.tradingCycle)["diagnosticScope"].value == "HISTORICAL"


def test_36_operator_view_hides_position_from_public():
    result = _inject_position()
    operator = view_to_json(result.collection.operator_view)
    public = view_to_json(result.collection.public_view)
    assert '"view":"OPERATOR_CONTEXT"' in operator
    assert "XRPUSDTM" in operator
    assert "XRPUSDTM" not in public


def test_37_secret_text_does_not_reach_the_views(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError(f"password={SECRET}")

    monkeypatch.setattr(adapter_module, "build_supervisor_snapshot", boom)
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **_supervisor())
    rendered = view_to_json(result.collection.operator_view) + view_to_json(result.collection.public_view)
    assert SECRET not in rendered
    assert result.collection.context.safety.secretsIncluded is False


def test_38_operator_view_stays_within_payload_limit():
    result = _inject_position()
    encoded = view_to_json(result.collection.operator_view).encode("utf-8")
    assert len(encoded) <= DEFAULT_VIEW_MAX_BYTES
    assert result.collection.operator_view.get("reason") != "PAYLOAD_LIMIT_EXCEEDED"


def test_39_output_is_deterministic():
    kwargs = dict(
        generated_at=PACK_AT,
        position_account=_paper(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_observed_at=FIXED_NOW,
        execution_projection=_execution(realOrderAllowed=False),
        cycle_evaluated_at=FIXED_NOW,
        **_cycle("cycle-a", "cycle-b"),
    )
    first = to_canonical_json(inject_verified_runtime_snapshots(**kwargs).collection.context)
    second = to_canonical_json(inject_verified_runtime_snapshots(**kwargs).collection.context)
    assert first == second


def test_40_uninjected_collector_contract_remains():
    collection = collect_runtime_context(generated_at=PACK_AT)
    assert collection.production_runtime_connected is False
    assert {item.category for item in collection.failures} == {READER_NOT_INJECTED}
    assert collection.context.safety.productionDeploy is False


def test_generated_at_must_be_aware():
    try:
        inject_verified_runtime_snapshots(generated_at=datetime(2026, 10, 25))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
        assert "2026" not in str(exc)
    else:
        raise AssertionError("naive generated_at was accepted")
