"""Offline tests for the verified runtime reader adapter.

Real readers are called when their inputs are injected. Unsafe producers are
not called. Nothing in this module starts Production or opens a socket on
purpose.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import socket

from backend.context import SCHEMA_VERSION, collect_runtime_context, view_to_json
from backend.context.api_contract import (
    PRODUCTION_API_AVAILABLE,
    PRODUCTION_RUNTIME_CONNECTED,
    PUBLIC_ENDPOINT_ENABLED,
)
from backend.context.collector_contract import READER_NOT_INJECTED
from backend.context.runtime_reader_adapter import collect_verified_runtime_context
from backend.context.runtime_reader_contract import (
    CONNECTED_READERS,
    RUNTIME_INSTANCE_NOT_INJECTED,
    SKIPPED_READERS,
    SOURCE_EXISTS_NOT_CONNECTED_FIELDS,
    SOURCE_NOT_FOUND_FIELDS,
    SOURCE_NOT_FOUND_NAMES,
    STALE_OR_UNPROVEN_FIELDS,
    UNAVAILABLE_BY_DESIGN_FIELDS,
    UNAVAILABLE_BY_DESIGN_NAMES,
    UNKNOWN,
    UNKNOWN_FIELDS,
    UNSAFE_READER_SKIPPED,
    VERIFIED_CONNECTED_FIELDS,
    VERIFIED_CYCLE_FIELDS,
    VERIFIED_POSITION_FIELDS,
    VERIFIED_READ_ONLY,
)
from backend.context.schema import Availability, ValueState
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
SECRET = "SECRET_BB4D_TOKEN"
ADAPTER_SOURCE = (REPO / "backend/context/runtime_reader_adapter.py").read_text(
    encoding="utf-8"
)


def _fields(section) -> dict[str, object]:
    return {item.name: item for item in section.fields}


def _paper_account(now: float, **position):
    row = {
        "symbol": "XRPUSDTM",
        "side": "LONG",
        "qty": 1,
        "entry_price": 0.5,
        "entry_time": now - 30,
        "entry_authority": "MANUAL",
        "coin_qty": 10,
    }
    row.update(position)
    return {
        "available": True,
        "lastUpdate": now,
        "positionState": "OPEN",
        "unrealizedPnl": 1.25,
        "positions": [row],
    }


def _position_result(**kwargs):
    observed = kwargs.pop("observed_at", FIXED_NOW)
    return collect_verified_runtime_context(
        generated_at=PACK_AT,
        position_account=kwargs.pop("account", _paper_account(FIXED_NOW.timestamp())),
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


def _cycle_inputs(current: str, evaluation: str):
    return {
        "trading_decision": {"cycleId": current},
        "trading_cycle_runtime_result": {
            "strategyOutput": {
                "strategy": {
                    "entryReadiness": {"cycleId": evaluation},
                    "timestamp": "2026-10-20T00:00:00Z",
                }
            }
        },
    }


def test_01_bb4c_router_remains_source_mounted():
    main = (REPO / "backend/main.py").read_text(encoding="utf-8")
    assert main.count("app.include_router(context_router)") == 1
    assert "/api/ai-context/public" not in main
    assert "collect_verified_runtime_context" not in main
    assert PUBLIC_ENDPOINT_ENABLED is False
    assert PRODUCTION_API_AVAILABLE is False
    assert PRODUCTION_RUNTIME_CONNECTED is False


def test_02_reader_safety_classification():
    assert CONNECTED_READERS == (
        "current_position",
        "build_trading_cycle_diagnostics",
        "build_supervisor_snapshot",
    )
    skipped = {name: safety for name, safety, _reason in SKIPPED_READERS}
    assert skipped["BotManager.get_status"] == UNKNOWN
    assert skipped["BotManager.get_result"] == UNKNOWN
    assert skipped["get_bot_manager"] != VERIFIED_READ_ONLY
    assert "get_status(" not in ADAPTER_SOURCE
    assert "get_result(" not in ADAPTER_SOURCE
    assert "get_bot_manager(" not in ADAPTER_SOURCE
    assert len(VERIFIED_POSITION_FIELDS) + len(VERIFIED_CYCLE_FIELDS) == 24
    assert (
        VERIFIED_CONNECTED_FIELDS
        + SOURCE_EXISTS_NOT_CONNECTED_FIELDS
        + SOURCE_NOT_FOUND_FIELDS
        + UNAVAILABLE_BY_DESIGN_FIELDS
        + STALE_OR_UNPROVEN_FIELDS
        + UNKNOWN_FIELDS
    ) == 63
    assert set(SOURCE_NOT_FOUND_NAMES) == {
        "account.currency",
        "smallAccount.takeProfitPercent",
        "smallAccount.timeExitSeconds",
    }
    assert "position.avgExit" in UNAVAILABLE_BY_DESIGN_NAMES
    assert "tradingCycle.CURRENT" not in VERIFIED_CYCLE_FIELDS


def test_03_safe_supervisor_reader_is_the_real_builder(monkeypatch):
    calls = {"count": 0}
    real = build_supervisor_snapshot

    def wrapped(**kwargs):
        calls["count"] += 1
        return real(**kwargs)

    monkeypatch.setattr(adapter_module, "build_supervisor_snapshot", wrapped)
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        supervisor_bot_status=bot_payload(),
        supervisor_governance_status=governance_payload(),
        supervisor_money_management_status=money_management_payload(),
        supervisor_health_payload=health_payload(),
        supervisor_captured_at=FIXED_NOW,
        supervisor_freshness_policy=FRESHNESS_POLICY,
    )
    assert calls["count"] == 1
    assert result.connected_readers == ("build_supervisor_snapshot",)
    assert result.collection.context.runtime.meta.availability is not Availability.UNAVAILABLE
    assert result.collection.context.generatedAt == PACK_AT
    assert result.collection.production_runtime_connected is False


def test_04_safe_position_reader_is_current_position(monkeypatch):
    calls = {"count": 0}
    real = current_position

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "current_position", wrapped)
    result = _position_result()
    fields = _fields(result.collection.context.position)
    assert calls["count"] == 1
    assert "current_position" in result.connected_readers
    assert fields["status"].value == "OPEN"
    assert fields["mode"].value == "PAPER"
    assert fields["side"].value == "LONG"
    assert fields["symbol"].value == "XRPUSDTM"
    assert fields["quantity"].value == 10
    assert fields["contractQuantity"].value == 1
    assert fields["coinQuantity"].value == 10
    assert fields["avgEntry"].value == 0.5
    assert fields["pnlUsdt"].value == 1.25
    assert fields["durationSeconds"].state is ValueState.PRESENT
    assert result.collection.context.position.meta.observedAt == FIXED_NOW
    assert result.collection.context.position.meta.observedAt != PACK_AT

    now = FIXED_NOW.timestamp()
    live = collect_verified_runtime_context(
        generated_at=PACK_AT,
        position_account={"authenticated": True, "lastSync": now},
        position_mode="LIVE",
        position_observed_at=FIXED_NOW,
        position_symbol="XRPUSDTM",
        position_observation={
            "sourceUpdatedAt": now,
            "positions": [
                {
                    "symbol": "XRPUSDTM",
                    "currentQty": 2,
                    "positionSide": "SHORT",
                    "avgEntryPrice": 0.4,
                    "realLeverage": 3,
                    "unrealisedPnl": 1.5,
                    "openingTimestamp": now - 10,
                }
            ],
        },
    )
    live_fields = _fields(live.collection.context.position)
    assert live_fields["mode"].value == "LIVE"
    assert live_fields["side"].value == "SHORT"
    assert live_fields["leverage"].value == 3
    assert calls["count"] == 2


def test_05_account_producer_is_not_called_and_passthrough_keeps_modes():
    assert "_build_account_runtime" not in ADAPTER_SOURCE
    assert "_get_real_account_snapshot" not in ADAPTER_SOURCE
    result = collect_verified_runtime_context(
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
    assert "current_position" not in result.connected_readers
    fields = _fields(result.collection.context.account)
    assert fields["paperBalance"].value == 11.5
    assert fields["liveBalance"].value == 77.25
    assert fields["paperAvailable"].state is ValueState.UNAVAILABLE
    assert fields["paperAvailable"].value is None
    assert fields["paperEquity"].state is ValueState.UNAVAILABLE
    assert fields["paperEquity"].value != 0
    assert fields["paperCurrency"].state is ValueState.UNAVAILABLE
    assert fields["liveCurrency"].state is ValueState.UNAVAILABLE


def test_06_mm_reader_does_not_alias_trailing_or_invent_exits():
    assert "trailing_stop_distance_percent" not in ADAPTER_SOURCE
    result = collect_verified_runtime_context(
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
    assert fields["riskBudget"].state is ValueState.UNAVAILABLE


def test_07_safe_cycle_reader_is_the_real_diagnostics_builder(monkeypatch):
    calls = {"count": 0}
    real = build_trading_cycle_diagnostics

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "build_trading_cycle_diagnostics", wrapped)
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        **_cycle_inputs("cycle-1", "cycle-1"),
    )
    fields = _fields(result.collection.context.tradingCycle)
    assert calls["count"] == 1
    assert result.connected_readers == ("build_trading_cycle_diagnostics",)
    assert fields["stepCount"].value == 15
    assert fields["diagnosticScope"].value == "CURRENT"
    assert fields["cycleState"].state is not ValueState.ABSENT
    assert result.collection.context.tradingCycle.meta.observedAt != PACK_AT


def test_08_execution_passthrough_keeps_bot_and_manual_distinct():
    payload = _execution()
    before = deepcopy(payload)
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        execution_projection=payload,
    )
    fields = _fields(result.collection.context.executionControl)
    assert payload == before
    assert fields["selectedMode"].value == "BOT"
    assert fields["tradeMode"].value == "MANUAL"
    assert fields["modeMismatch"].value == "TRUE"
    assert fields["controlAuthority"].value == "BOT"
    assert fields["entryAuthority"].value == "MANUAL"
    assert "BotManager.get_result" in {item.name for item in result.skipped_readers}


def test_09_runtime_instance_not_injected():
    result = collect_verified_runtime_context(generated_at=PACK_AT)
    assert result.runtime_instance_injected is False
    assert result.connected_readers == ()
    assert result.adapter_failures[0].category == RUNTIME_INSTANCE_NOT_INJECTED
    assert {item.category for item in result.collection.failures} == {READER_NOT_INJECTED}
    assert result.collection.production_runtime_connected is False


def test_10_reader_not_injected_when_position_clock_is_missing():
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        position_account=_paper_account(FIXED_NOW.timestamp()),
        position_mode="PAPER",
    )
    assert "current_position" not in result.connected_readers
    assert any(
        item.source == "position" and item.category == "READER_NOT_INJECTED"
        for item in result.adapter_failures
    )
    status = _fields(result.collection.context.position).get("status")
    assert status is None or status.value != "OPEN"


def test_11_partial_reader_failure_keeps_successful_position(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError(f"cycle failed token={SECRET} path=/tmp/hidden")

    monkeypatch.setattr(adapter_module, "build_trading_cycle_diagnostics", boom)
    result = _position_result(trading_decision={"cycleId": "cycle-1"})
    assert _fields(result.collection.context.position)["status"].value == "OPEN"
    assert any(
        item.source == "trading_cycle" and item.category == "READER_FAILED"
        for item in result.adapter_failures
    )
    rendered = to_canonical_json(result.collection.context)
    assert SECRET not in rendered
    assert "cycle failed" not in rendered
    assert _fields(result.collection.context.tradingCycle)["diagnosticScope"].value != "CURRENT"


def test_12_reader_exception_text_is_not_stored(monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError(f"File \"/home/joe4410joe/secret.py\", token={SECRET}")

    monkeypatch.setattr(adapter_module, "build_supervisor_snapshot", boom)
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        supervisor_bot_status=bot_payload(),
        supervisor_captured_at=FIXED_NOW,
        supervisor_freshness_policy=FRESHNESS_POLICY,
    )
    rendered = view_to_json(result.collection.operator_view) + to_canonical_json(
        result.collection.context
    )
    assert SECRET not in rendered
    assert "secret.py" not in rendered
    assert "Traceback" not in rendered
    assert all(not hasattr(item, "message") for item in result.adapter_failures)


def test_13_paper_and_live_position_modes_stay_separate():
    paper = _position_result()
    live_shaped = _paper_account(FIXED_NOW.timestamp())
    live = _position_result(account=live_shaped, mode="LIVE")
    assert _fields(paper.collection.context.position)["mode"].value == "PAPER"
    assert _fields(paper.collection.context.position)["status"].value == "OPEN"
    assert _fields(live.collection.context.position)["mode"].value == "LIVE"
    assert _fields(live.collection.context.position)["status"].value != "OPEN"


def test_14_bot_and_manual_are_not_collapsed():
    fields = _fields(
        collect_verified_runtime_context(
            generated_at=PACK_AT,
            execution_projection=_execution(),
        ).collection.context.executionControl
    )
    assert fields["selectedMode"].value != fields["tradeMode"].value
    assert fields["controlAuthority"].value == "BOT"
    assert fields["entryAuthority"].value == "MANUAL"


def test_15_flat_is_not_unknown_and_unknown_is_not_flat():
    now = FIXED_NOW.timestamp()
    flat = _position_result(
        account={
            "available": True,
            "lastUpdate": now,
            "positionState": "FLAT",
            "positions": [],
        }
    )
    unknown = _position_result(
        account={
            "available": True,
            "lastUpdate": now,
            "positionState": "OPEN",
            "positions": [],
        }
    )
    assert _fields(flat.collection.context.position)["status"].value == "FLAT"
    assert _fields(unknown.collection.context.position)["status"].value == "UNKNOWN"


def test_16_multiple_positions_are_not_presented_as_one_open():
    now = FIXED_NOW.timestamp()
    account = {
        "available": True,
        "lastUpdate": now,
        "positionState": "OPEN",
        "positions": [
            {"symbol": "XRPUSDTM", "side": "LONG", "qty": 1, "entry_price": 0.5, "coin_qty": 1},
            {"symbol": "BTCUSDTM", "side": "SHORT", "qty": 2, "entry_price": 1, "coin_qty": 2},
        ],
    }
    fields = _fields(_position_result(account=account).collection.context.position)
    assert fields["status"].value == "UNKNOWN"
    assert fields["ambiguity"].value == "MULTIPLE_POSITIONS"
    assert fields["positionCount"].state is ValueState.UNAVAILABLE
    assert fields["symbol"].state is not ValueState.PRESENT


def test_17_current_cycle_needs_matching_cycle_evidence():
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        **_cycle_inputs("cycle-live", "cycle-live"),
    )
    cycle = result.collection.context.tradingCycle
    assert _fields(cycle)["diagnosticScope"].value == "CURRENT"
    assert cycle.meta.observedAt is None
    assert result.collection.context.generatedAt == PACK_AT
    assert cycle.meta.freshness.name == "UNKNOWN"


def test_18_historical_cycle_is_not_promoted():
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        cycle_evaluated_at=FIXED_NOW - timedelta(days=5),
        **_cycle_inputs("cycle-now", "cycle-old"),
    )
    cycle = result.collection.context.tradingCycle
    fields = _fields(cycle)
    assert fields["diagnosticScope"].value == "HISTORICAL"
    assert cycle.meta.freshness.name == "STALE"
    assert cycle.meta.observedAt != PACK_AT


def test_19_cycle_without_ids_stays_unknown():
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        trading_decision={"timestamp": "2026-10-20T00:00:00Z"},
    )
    fields = _fields(result.collection.context.tradingCycle)
    assert fields["diagnosticScope"].value == "UNKNOWN"
    assert result.collection.context.tradingCycle.meta.freshness.name == "UNKNOWN"


def test_20_step_10_and_13_stay_unknown():
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        trading_decision={"timestamp": "2026-10-25T00:00:00Z"},
        cycle_evaluated_at=FIXED_NOW,
    )
    fields = _fields(result.collection.context.tradingCycle)
    assert fields["step.10.status"].value == "UNKNOWN"
    assert fields["step.13.status"].value == "UNKNOWN"
    assert fields["step.10.status"].value != "PASS"
    assert fields["step.13.userActionRequired"].value != "PASS"


def test_21_real_order_allowed_fails_closed_unless_explicit_true():
    omitted = _fields(
        collect_verified_runtime_context(
            generated_at=PACK_AT,
            execution_projection=_execution(),
        ).collection.context.executionControl
    )
    assert omitted["realOrderAllowed"].value is False
    assert omitted["realOrderAllowed"].state is ValueState.UNKNOWN
    assert omitted["realOrderAllowedEvidence"].value == "FAIL_CLOSED"

    coerced = _fields(
        collect_verified_runtime_context(
            generated_at=PACK_AT,
            execution_projection=_execution(realOrderAllowed=1),
        ).collection.context.executionControl
    )
    assert coerced["realOrderAllowedEvidence"].value == "FAIL_CLOSED"

    explicit = _fields(
        collect_verified_runtime_context(
            generated_at=PACK_AT,
            execution_projection=_execution(realOrderAllowed=True),
        ).collection.context.executionControl
    )
    assert explicit["realOrderAllowed"].value is True
    assert explicit["realOrderAllowed"].state is ValueState.PRESENT
    assert explicit["realOrderAllowedEvidence"].value == "EXPLICIT_TRUE"


def test_22_bot_manager_is_not_created_or_queried():
    class Manager:
        def __init__(self):
            raise AssertionError("constructed")

        def get_status(self):
            raise AssertionError("get_status")

        def get_result(self):
            raise AssertionError("get_result")

    manager = Manager.__new__(Manager)
    result = collect_verified_runtime_context(generated_at=PACK_AT, bot_manager=manager)
    assert any(item.category == UNSAFE_READER_SKIPPED for item in result.adapter_failures)
    assert "BotManager(" not in ADAPTER_SOURCE


def test_23_supervisor_class_is_not_constructed():
    assert "Supervisor(" not in ADAPTER_SOURCE
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        supervisor_bot_status=bot_payload(),
        supervisor_governance_status=governance_payload(),
        supervisor_money_management_status=money_management_payload(),
        supervisor_health_payload=health_payload(),
        supervisor_captured_at=FIXED_NOW,
        supervisor_freshness_policy=FRESHNESS_POLICY,
    )
    assert type(result.collection.context).__name__ == "CanonicalContext"


def test_24_adapter_call_does_not_open_a_socket(monkeypatch):
    def fail_socket(*_args, **_kwargs):
        raise AssertionError("socket opened")

    monkeypatch.setattr(socket, "socket", fail_socket)
    result = _position_result()
    assert _fields(result.collection.context.position)["status"].value == "OPEN"


def test_25_bot_start_and_stop_are_not_called():
    class Manager:
        def __init__(self):
            self.calls = []

        def start(self):
            self.calls.append("start")

        def stop(self):
            self.calls.append("stop")

        def connect_exchange(self):
            self.calls.append("connect")

    manager = Manager()
    collect_verified_runtime_context(generated_at=PACK_AT, bot_manager=manager)
    assert manager.calls == []
    assert ".start(" not in ADAPTER_SOURCE
    assert ".stop(" not in ADAPTER_SOURCE


def test_26_authority_mapping_is_not_mutated():
    payload = _execution()
    before = deepcopy(payload)
    collect_verified_runtime_context(generated_at=PACK_AT, execution_projection=payload)
    assert payload == before
    assert "set_authority" not in ADAPTER_SOURCE
    assert "executionEnabled" not in ADAPTER_SOURCE


def test_27_emergency_mapping_is_not_mutated():
    payload = _execution(emergencyState="ARMED")
    before = deepcopy(payload)
    result = collect_verified_runtime_context(
        generated_at=PACK_AT, execution_projection=payload
    )
    assert payload == before
    assert _fields(result.collection.context.executionControl)["emergencyState"].value == "ARMED"
    assert "trigger_emergency" not in ADAPTER_SOURCE
    assert "emergency_lock" not in ADAPTER_SOURCE


def test_28_production_startup_is_not_referenced():
    assert "backend.main" not in ADAPTER_SOURCE
    assert "startup_event" not in ADAPTER_SOURCE
    assert "TestClient" not in ADAPTER_SOURCE
    result = collect_verified_runtime_context(generated_at=PACK_AT)
    assert result.collection.production_runtime_connected is False
    safety = result.collection.context.safety
    assert safety.runtimeWrite is False
    assert safety.orderWrite is False
    assert safety.liveOrder is False
    assert safety.productionDeploy is False


def test_29_canonical_context_schema_is_unchanged():
    result = _position_result(**_cycle_inputs("cycle-1", "cycle-9"))
    assert result.collection.context.schemaVersion == SCHEMA_VERSION
    assert result.collection.context.schemaVersion == "tradingai-context/v1"
    rendered = to_canonical_json(result.collection.context)
    assert rendered.startswith("{")
    assert "tradingai-context/v1" in rendered


def test_30_operator_view_receives_the_wired_position():
    result = _position_result()
    operator = view_to_json(result.collection.operator_view)
    public = view_to_json(result.collection.public_view)
    assert '"view":"OPERATOR_CONTEXT"' in operator
    assert "XRPUSDTM" in operator
    assert "XRPUSDTM" not in public
    assert result.collection.operator_view["authentication"] == "NOT_ASSERTED"


def test_31_secrets_in_failures_do_not_reach_either_view(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError(f"password={SECRET} api_key={SECRET}")

    monkeypatch.setattr(adapter_module, "current_position", boom)
    result = _position_result()
    rendered = view_to_json(result.collection.operator_view) + view_to_json(
        result.collection.public_view
    )
    assert SECRET not in rendered
    assert "password=" not in rendered
    assert result.collection.context.safety.secretsIncluded is False


def test_32_raw_exception_text_is_absent_from_the_pack(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("Traceback (most recent call last): secret path")

    monkeypatch.setattr(adapter_module, "build_trading_cycle_diagnostics", boom)
    result = collect_verified_runtime_context(
        generated_at=PACK_AT,
        trading_decision={"cycleId": "cycle-1"},
    )
    rendered = to_canonical_json(result.collection.context)
    assert "Traceback" not in rendered
    assert "most recent call" not in rendered
    assert "RuntimeError" not in rendered


def test_33_output_is_deterministic():
    kwargs = dict(
        generated_at=PACK_AT,
        position_account=_paper_account(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_observed_at=FIXED_NOW,
        execution_projection=_execution(realOrderAllowed=False),
        **_cycle_inputs("cycle-a", "cycle-b"),
        cycle_evaluated_at=FIXED_NOW,
    )
    first = to_canonical_json(collect_verified_runtime_context(**kwargs).collection.context)
    second = to_canonical_json(collect_verified_runtime_context(**kwargs).collection.context)
    assert first == second


def test_34_uninjected_collector_contract_remains_fail_closed():
    collection = collect_runtime_context(generated_at=PACK_AT)
    assert collection.production_runtime_connected is False
    assert {item.category for item in collection.failures} == {READER_NOT_INJECTED}
    assert collection.context.schemaVersion == SCHEMA_VERSION
    assert collection.context.safety.liveOrder is False
