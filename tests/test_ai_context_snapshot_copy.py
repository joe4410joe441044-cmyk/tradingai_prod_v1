"""Offline tests for the non-refreshing snapshot copy.

Copies are plain mappings. These tests do not construct a BotManager,
Supervisor, exchange client, or the production application.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import io
import socket
import threading
from pathlib import Path

from backend.context import collect_runtime_context, copy_injection_inputs, copy_json_snapshot
from backend.context.injection_boundary import inject_verified_runtime_snapshots
from backend.context.injection_contract import MAX_BYTES, MAX_DEPTH, MAX_STRING, SnapshotRejected
from backend.context.schema import ValueState
from backend.context.snapshot_copy import LIVE_SOURCE_NOT_SAFE
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
SECRET = "SECRET_BB4G_TOKEN"
COPY_SOURCE = (REPO / "backend/context/snapshot_copy.py").read_text(encoding="utf-8")
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
                "coin_qty": 10,
            }
        ],
    }


def _cycle(current: str, evaluation: str):
    return {
        "trading_decision": {"cycleId": current},
        "trading_cycle_runtime_result": {
            "strategyOutput": {"strategy": {"entryReadiness": {"cycleId": evaluation}}}
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


def _inject_copied(**kwargs):
    prepared = copy_injection_inputs(**kwargs)
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **prepared.values)
    return prepared, result


def test_01_bb4f_injection_still_rejects_empty_input():
    assert MAIN.count("app.include_router(context_router)") == 1
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT)
    assert result.runtime_instance_injected is False
    assert result.collection.production_runtime_connected is False


def test_02_json_snapshot_copy_preserves_values():
    copied = copy_json_snapshot({"mode": "PAPER", "qty": 2, "ok": True, "note": None})
    assert copied == {"mode": "PAPER", "qty": 2, "ok": True, "note": None}


def test_03_nested_mapping_is_copied():
    copied = copy_json_snapshot({"positions": [{"symbol": "XRPUSDTM"}]})
    assert copied["positions"][0]["symbol"] == "XRPUSDTM"
    assert copied["positions"] is not None


def test_04_input_mapping_is_not_mutated():
    original = _paper(FIXED_NOW.timestamp())
    before = deepcopy(original)
    copy_json_snapshot(original)
    assert original == before


def test_05_output_mutation_does_not_change_input():
    original = _paper(FIXED_NOW.timestamp())
    copied = copy_json_snapshot(original)
    copied["positions"][0]["qty"] = 99
    assert original["positions"][0]["qty"] == 1


def test_06_circular_reference_is_rejected():
    node = {"name": "loop"}
    node["self"] = node
    try:
        copy_json_snapshot(node)
    except SnapshotRejected as exc:
        assert SECRET not in str(exc)
    else:
        raise AssertionError("cycle accepted")


def test_07_oversized_string_is_rejected():
    try:
        copy_json_snapshot({"note": "x" * (MAX_STRING + 1)})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("oversize accepted")


def test_08_excessive_nesting_is_rejected():
    node: dict = {"v": 1}
    for _ in range(MAX_DEPTH + 3):
        node = {"n": node}
    try:
        copy_json_snapshot(node)
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("deep nest accepted")


def test_09_nan_is_rejected():
    try:
        copy_json_snapshot({"pnl": float("nan")})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("nan accepted")


def test_10_infinity_is_rejected():
    try:
        copy_json_snapshot({"pnl": float("inf")})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("infinity accepted")


def test_11_lock_is_rejected():
    try:
        copy_json_snapshot({"lock": threading.Lock()})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("lock accepted")


def test_12_socket_is_rejected():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        copy_json_snapshot({"sock": sock})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("socket accepted")
    finally:
        sock.close()


def test_13_client_object_is_rejected():
    class Client:
        def get_account_overview(self):
            raise AssertionError("called")

    client = Client()
    try:
        copy_json_snapshot({"client": client})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("client accepted")


def test_14_manager_object_is_rejected():
    class Manager:
        def get_status(self):
            raise AssertionError("called")

    try:
        copy_json_snapshot({"manager": Manager()})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("manager accepted")


def test_15_callable_is_rejected():
    try:
        copy_json_snapshot({"fn": lambda: SECRET})
    except SnapshotRejected as exc:
        assert SECRET not in str(exc)
    else:
        raise AssertionError("callable accepted")


def test_16_generator_is_rejected():
    try:
        copy_json_snapshot({"gen": (item for item in (1,))})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("generator accepted")


def test_17_file_handle_is_rejected():
    handle = io.StringIO("not-a-snapshot")
    try:
        copy_json_snapshot({"handle": handle})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("file handle accepted")
    finally:
        handle.close()


def test_18_copy_source_does_not_construct_runtime():
    assert "BotManager(" not in COPY_SOURCE
    assert "Supervisor(" not in COPY_SOURCE
    assert "KucoinTradeClient(" not in COPY_SOURCE


def test_19_get_bot_manager_is_absent():
    assert "get_bot_manager(" not in COPY_SOURCE


def test_20_get_status_is_absent():
    assert "get_status(" not in COPY_SOURCE


def test_21_get_result_is_absent():
    assert "get_result(" not in COPY_SOURCE


def test_22_exchange_api_is_absent():
    assert "get_account_overview(" not in COPY_SOURCE
    assert "KucoinTradeClient" not in COPY_SOURCE


def test_23_account_refresh_is_absent():
    assert "_refresh_real_account_snapshot" not in COPY_SOURCE
    assert "_capture_account_snapshot" not in COPY_SOURCE


def test_24_mm_recalculation_is_absent():
    assert "MoneyManagementHttpBoundary" not in COPY_SOURCE
    assert "riskBudget" not in COPY_SOURCE


def test_25_authority_is_not_mutated():
    payload = _execution()
    before = deepcopy(payload)
    prepared = copy_injection_inputs(execution_projection=payload)
    assert payload == before
    assert "set_authority" not in COPY_SOURCE
    assert prepared.values["execution_projection"]["controlAuthority"] == "BOT"


def test_26_emergency_is_not_mutated():
    payload = _execution()
    before = deepcopy(payload)
    prepared = copy_injection_inputs(execution_projection=payload)
    assert payload == before
    assert prepared.values["execution_projection"]["emergencyState"] == "ARMED"
    assert "trigger_emergency" not in COPY_SOURCE


def test_27_copied_supervisor_payload_injects():
    prepared, result = _inject_copied(**_supervisor())
    assert prepared.consistency == LIVE_SOURCE_NOT_SAFE
    assert result.connected_readers == ("build_supervisor_snapshot",)
    assert result.collection.production_runtime_connected is False


def test_28_copied_position_payload_injects():
    prepared, result = _inject_copied(
        position_account=_paper(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_observed_at=FIXED_NOW,
    )
    assert prepared.values["position_account"]["positions"][0]["symbol"] == "XRPUSDTM"
    assert _fields(result.collection.context.position)["status"].value == "OPEN"
    assert result.collection.context.position.meta.observedAt == FIXED_NOW


def test_29_copied_cycle_payload_injects():
    _, result = _inject_copied(cycle_evaluated_at=FIXED_NOW, **_cycle("cycle-1", "cycle-1"))
    assert "build_trading_cycle_diagnostics" in result.connected_readers
    assert _fields(result.collection.context.tradingCycle)["stepCount"].value == 15


def test_30_copied_account_passthrough():
    _, result = _inject_copied(
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
        }
    )
    fields = _fields(result.collection.context.account)
    assert fields["paperBalance"].value == 11.5
    assert fields["liveBalance"].value == 77.25
    assert fields["paperCurrency"].state is ValueState.UNAVAILABLE


def test_31_copied_mm_passthrough_does_not_alias_trailing():
    _, result = _inject_copied(
        mm_projection={
            "availableCapital": "25",
            "trailing_stop_distance_percent": "3",
            "sourceUpdatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        }
    )
    fields = _fields(result.collection.context.smallAccount)
    assert fields["availableCapital"].value == "25"
    assert fields["trailingPercent"].state is ValueState.UNAVAILABLE


def test_32_copied_execution_passthrough():
    _, result = _inject_copied(execution_projection=_execution())
    fields = _fields(result.collection.context.executionControl)
    assert fields["selectedMode"].value == "BOT"
    assert fields["tradeMode"].value == "MANUAL"


def test_33_non_bool_real_order_allowed_is_removed_from_the_copy():
    original = _execution(realOrderAllowed="true")
    prepared = copy_injection_inputs(execution_projection=original)
    assert original["realOrderAllowed"] == "true"
    assert "realOrderAllowed" not in prepared.values["execution_projection"]
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **prepared.values)
    allowed = _fields(result.collection.context.executionControl)["realOrderAllowed"]
    assert allowed.value is False
    assert allowed.state is ValueState.UNKNOWN


def test_34_producer_timestamp_is_preserved():
    stamp = FIXED_NOW.timestamp()
    copied = copy_json_snapshot(_paper(stamp))
    assert copied["lastUpdate"] == stamp
    assert "copiedAt" not in copied


def test_35_missing_timestamp_stays_missing():
    copied = copy_json_snapshot({"mode": "PAPER"})
    assert "observedAt" not in copied
    assert "evaluatedAt" not in copied
    assert "diagnosticsGeneratedAt" not in copied


def test_36_cycle_id_text_is_preserved():
    original = _cycle("cycle-live", "cycle-old")
    prepared = copy_injection_inputs(**original)
    assert prepared.values["trading_decision"]["cycleId"] == "cycle-live"
    readiness = prepared.values["trading_cycle_runtime_result"]["strategyOutput"]["strategy"]["entryReadiness"]
    assert readiness["cycleId"] == "cycle-old"


def test_37_matching_cycle_ids_without_time_are_not_current():
    prepared, result = _inject_copied(**_cycle("cycle-live", "cycle-live"))
    assert prepared.values["trading_decision"]["cycleId"] == "cycle-live"
    scope = _fields(result.collection.context.tradingCycle).get("diagnosticScope")
    assert scope is None or scope.value != "CURRENT"


def test_38_historical_cycle_stays_historical():
    _, result = _inject_copied(
        cycle_evaluated_at=FIXED_NOW - timedelta(days=5),
        **_cycle("cycle-now", "cycle-old"),
    )
    cycle = result.collection.context.tradingCycle
    assert _fields(cycle)["diagnosticScope"].value == "HISTORICAL"
    assert cycle.meta.observedAt != PACK_AT


def test_39_unknown_cycle_stays_unknown():
    _, result = _inject_copied(trading_decision={"timestamp": "2026-10-20T00:00:00Z"})
    assert _fields(result.collection.context.tradingCycle)["diagnosticScope"].value == "UNKNOWN"


def test_40_bad_cycle_slot_does_not_drop_position():
    class Locked:
        token = SECRET

    prepared = copy_injection_inputs(
        position_account=_paper(FIXED_NOW.timestamp()),
        position_mode="PAPER",
        position_observed_at=FIXED_NOW,
        trading_decision={"cycleId": "cycle-1", "lock": Locked()},
    )
    assert any(item.source == "trading_cycle" and item.category == "READER_REJECTED" for item in prepared.failures)
    assert SECRET not in str(prepared.failures)
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **prepared.values)
    assert _fields(result.collection.context.position)["status"].value == "OPEN"


def test_41_rejection_does_not_include_secret_text():
    class Box:
        def __init__(self):
            self.token = SECRET

    try:
        copy_json_snapshot({"box": Box()})
    except SnapshotRejected as exc:
        assert str(exc) == "READER_REJECTED"
        assert SECRET not in str(exc)
    else:
        raise AssertionError("object accepted")


def test_42_encoded_payload_over_the_copy_limit_is_rejected():
    payload = {f"k{index}": "y" * 3000 for index in range(30)}
    assert len(str(payload)) > MAX_BYTES
    try:
        copy_json_snapshot(payload)
    except SnapshotRejected as exc:
        assert "yyyy" not in str(exc)
    else:
        raise AssertionError("large payload accepted")


def test_43_copy_is_deterministic():
    original = _paper(FIXED_NOW.timestamp())
    assert copy_json_snapshot(original) == copy_json_snapshot(original)


def test_44_startup_is_not_referenced():
    assert "startup_event" not in COPY_SOURCE
    assert "backend.main" not in COPY_SOURCE
    assert "get_control_plane" not in COPY_SOURCE


def test_45_uninjected_collector_remains_fail_closed():
    collection = collect_runtime_context(generated_at=PACK_AT)
    assert collection.production_runtime_connected is False
    prepared = copy_injection_inputs()
    assert prepared.values == {}
    assert prepared.consistency == LIVE_SOURCE_NOT_SAFE
    assert prepared.lock_action == "CONTEXT_DOES_NOT_TAKE_RUNTIME_LOCKS"


def test_coroutine_is_rejected():
    import asyncio

    async def _unused():
        return None

    coro = _unused()
    try:
        copy_json_snapshot({"coro": coro})
    except SnapshotRejected:
        pass
    else:
        raise AssertionError("coroutine accepted")
    finally:
        coro.close()
