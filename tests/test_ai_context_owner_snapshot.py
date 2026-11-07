"""Isolated tests for the BotManager owner-published snapshot.

The BotManager constructor is not called. Production startup is not imported.
"""

from __future__ import annotations

from datetime import timedelta
import inspect
import threading
from pathlib import Path

from backend.bot_manager.bot_manager import BotManager
from backend.bot_manager.owner_snapshot import (
    merge_owner_snapshot,
    unavailable_owner_snapshot,
)
from backend.context import collect_runtime_context, copy_injection_inputs, copy_json_snapshot
from backend.context.injection_boundary import inject_verified_runtime_snapshots
from backend.context.runtime_composer import compose_tradingai_context
from backend.context.schema import ValueState
from tests.test_ai_context_support import FIXED_NOW

REPO = Path(__file__).resolve().parents[1]
PACK_AT = FIXED_NOW + timedelta(hours=1)
SECRET = "SECRET_BB4I_TOKEN"
OWNER_SOURCE = (REPO / "backend/bot_manager/owner_snapshot.py").read_text(encoding="utf-8")
PUBLISH_SOURCE = "\n".join(
    inspect.getsource(method)
    for method in (
        BotManager._publish_context_snapshot,
        BotManager._paper_cache_for_publication,
        BotManager.export_context_snapshot,
    )
)
MAIN = (REPO / "backend/main.py").read_text(encoding="utf-8")
ROUTER = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")


def _owner():
    owner = BotManager.__new__(BotManager)
    owner._context_publication_lock = threading.Lock()
    owner._context_publication = unavailable_owner_snapshot()
    owner.paper_capital_lock = threading.RLock()
    owner.paper_account_runtime_snapshot = None
    owner.emergency_marker = ["ARMED"]
    owner.config = {"realOrderAllowed": "true", "mode": "LIVE"}
    return owner


def _paper():
    return {
        "available": True,
        "lastUpdate": FIXED_NOW.timestamp(),
        "positionState": "OPEN",
        "positions": [
            {
                "symbol": "XRPUSDTM",
                "side": "LONG",
                "qty": 1,
                "entry_price": 0.5,
                "entry_time": FIXED_NOW.timestamp() - 30,
                "coin_qty": 10,
            }
        ],
    }


def _runtime(cycle_id="cycle-live"):
    return {
        "strategyOutput": {
            "strategy": {"entryReadiness": {"cycleId": cycle_id}}
        }
    }


def _fields(section):
    return {item.name: item for item in section.fields}


def test_01_initial_snapshot_is_unavailable():
    exported = _owner().export_context_snapshot()
    assert exported["availability"] == "UNAVAILABLE"
    assert exported["errorState"] == "NOT_PUBLISHED"
    assert exported["payload"] == {}
    assert exported["schemaVersion"] == "tradingai-owner-snapshot/v1"
    blob = str(exported["payload"])
    for guessed in ("FLAT", "STOPPED", "PAPER", "LIVE"):
        assert guessed not in blob


def test_02_publish_stores_a_ready_snapshot():
    owner = _owner()
    owner._publish_context_snapshot(paper_account=_paper(), update_paper=True)
    exported = owner.export_context_snapshot()
    assert exported["availability"] == "READY"
    assert exported["revision"] == 1
    assert exported["payload"]["position_mode"] == "PAPER"


def test_03_export_returns_the_stored_snapshot():
    owner = _owner()
    owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True)
    exported = owner.export_context_snapshot()
    assert exported["payload"]["trading_cycle_runtime_result"]["strategyOutput"]["strategy"]["entryReadiness"]["cycleId"] == "cycle-live"


def test_04_publish_does_not_mutate_the_input():
    original = _paper()
    before = copy_json_snapshot(original)
    _owner()._publish_context_snapshot(paper_account=original, update_paper=True)
    assert original == before


def test_05_exported_mutation_does_not_change_the_stored_snapshot():
    owner = _owner()
    owner._publish_context_snapshot(paper_account=_paper(), update_paper=True)
    exported = owner.export_context_snapshot()
    exported["payload"]["position_account"]["positions"][0]["qty"] = 99
    again = owner.export_context_snapshot()
    assert again["payload"]["position_account"]["positions"][0]["qty"] == 1


def test_06_publication_replaces_the_document_as_a_whole():
    owner = _owner()
    owner._publish_context_snapshot(
        paper_account=_paper(),
        runtime_result=_runtime(),
        update_paper=True,
        update_runtime=True,
    )
    exported = owner.export_context_snapshot()
    assert exported["schemaVersion"] == "tradingai-owner-snapshot/v1"
    assert "position_account" in exported["payload"]
    assert "trading_cycle_runtime_result" in exported["payload"]


def test_07_export_waits_for_the_publication_lock_then_returns():
    owner = _owner()
    owner._context_publication_lock.acquire()
    seen = {}

    def _export():
        seen["value"] = owner.export_context_snapshot()

    worker = threading.Thread(target=_export)
    worker.start()
    worker.join(0.05)
    assert worker.is_alive()
    owner._context_publication_lock.release()
    worker.join(1)
    assert not worker.is_alive()
    assert seen["value"]["availability"] == "UNAVAILABLE"


def test_08_concurrent_publishes_keep_both_fragments():
    owner = _owner()
    barrier = threading.Barrier(2)

    def _paper_publish():
        barrier.wait()
        owner._publish_context_snapshot(paper_account=_paper(), update_paper=True)

    def _runtime_publish():
        barrier.wait()
        owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True)

    workers = [threading.Thread(target=_paper_publish), threading.Thread(target=_runtime_publish)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)
    exported = owner.export_context_snapshot()
    assert exported["payload"]["position_account"]["positionState"] == "OPEN"
    assert "trading_cycle_runtime_result" in exported["payload"]


def test_09_paper_lock_is_released_before_the_publication_lock():
    publish = inspect.getsource(BotManager._publish_context_snapshot)
    paper = inspect.getsource(BotManager._paper_cache_for_publication)
    assert publish.find("_paper_cache_for_publication") < publish.find("with self._context_publication_lock")
    assert paper.find("paper_capital_lock") < paper.find("lock.release()")
    assert "account_refresh_lock" not in publish
    assert "execution_authority_lock" not in publish


def test_10_publish_finishes_while_another_thread_holds_the_paper_lock():
    owner = _owner()
    owner.paper_capital_lock.acquire()
    finished = threading.Event()

    def _publish():
        owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True, update_paper=True)
        finished.set()

    worker = threading.Thread(target=_publish)
    worker.start()
    assert finished.wait(1)
    owner.paper_capital_lock.release()
    worker.join(1)
    assert owner.export_context_snapshot()["availability"] == "READY"


def test_11_publish_source_does_not_call_get_status():
    assert "get_status(" not in PUBLISH_SOURCE
    assert "get_status(" not in OWNER_SOURCE


def test_12_publish_source_does_not_call_get_result():
    assert "get_result(" not in PUBLISH_SOURCE
    assert "get_result(" not in OWNER_SOURCE


def test_13_publish_source_does_not_call_get_bot_manager():
    assert "get_bot_manager(" not in PUBLISH_SOURCE
    assert "get_bot_manager(" not in OWNER_SOURCE


def test_14_account_refresh_is_not_called():
    assert "_refresh_real_account_snapshot" not in PUBLISH_SOURCE
    assert "_capture_account_snapshot" not in PUBLISH_SOURCE
    assert "_build_paper_account_runtime" not in OWNER_SOURCE


def test_15_money_management_status_is_not_called():
    assert "MoneyManagementHttpBoundary" not in OWNER_SOURCE
    assert "get_status(" not in OWNER_SOURCE


def test_16_exchange_api_is_not_called():
    assert "get_account_overview(" not in PUBLISH_SOURCE
    assert "KucoinTradeClient" not in OWNER_SOURCE


def test_17_supervisor_start_is_not_called():
    assert "get_control_plane" not in PUBLISH_SOURCE
    assert "RuntimeSnapshotAdapter" not in OWNER_SOURCE
    assert ".start(" not in OWNER_SOURCE


def test_18_trading_loop_is_not_started():
    assert "start_loop(" not in PUBLISH_SOURCE
    assert "process_runtime(" not in PUBLISH_SOURCE


def test_19_explicit_paper_cache_is_copied():
    owner = _owner()
    paper = _paper()
    owner.paper_account_runtime_snapshot = paper
    owner._publish_context_snapshot(paper_account=paper, update_paper=True)
    exported = owner.export_context_snapshot()
    assert exported["payload"]["position_account"]["positions"][0]["symbol"] == "XRPUSDTM"
    assert paper["positions"][0]["qty"] == 1


def test_20_real_account_cache_is_not_published():
    owner = _owner()
    owner.real_account_snapshot = {"balance": 10, "loading": False}
    owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True)
    exported = owner.export_context_snapshot()
    assert "real_account" in exported["unavailable"]
    assert "balance" not in exported["payload"]


def test_21_missing_paper_cache_leaves_position_absent():
    owner = _owner()
    owner._publish_context_snapshot(update_paper=True)
    exported = owner.export_context_snapshot()
    assert "position_account" not in exported["payload"]
    assert exported["availability"] == "UNAVAILABLE"


def test_22_position_state_is_copied_without_rewriting_unknown():
    paper = _paper()
    paper["positionState"] = "UNKNOWN"
    paper["positions"] = []
    owner = _owner()
    owner._publish_context_snapshot(paper_account=paper, update_paper=True)
    exported = owner.export_context_snapshot()
    assert exported["payload"]["position_account"]["positionState"] == "UNKNOWN"
    assert exported["payload"]["position_mode"] == "PAPER"


def test_23_stored_runtime_result_is_exported():
    runtime = _runtime("cycle-stored")
    owner = _owner()
    owner._publish_context_snapshot(runtime_result=runtime, update_runtime=True)
    exported = owner.export_context_snapshot()
    stored = exported["payload"]["trading_cycle_runtime_result"]
    assert stored == runtime
    assert stored is not runtime


def test_24_missing_producer_time_stays_missing():
    owner = _owner()
    owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True)
    exported = owner.export_context_snapshot()
    assert exported["producerObservedAt"] is None
    assert exported["observedAt"] is None
    assert exported["publishedAt"] != exported["producerObservedAt"]


def test_25_cycle_id_text_is_preserved():
    owner = _owner()
    owner._publish_context_snapshot(runtime_result=_runtime("cycle-exact"), update_runtime=True)
    exported = owner.export_context_snapshot()
    readiness = exported["payload"]["trading_cycle_runtime_result"]["strategyOutput"]["strategy"]["entryReadiness"]
    assert readiness["cycleId"] == "cycle-exact"


def test_26_matching_cycle_ids_do_not_grant_current():
    owner = _owner()
    owner._publish_context_snapshot(runtime_result=_runtime("cycle-live"), update_runtime=True)
    exported = owner.export_context_snapshot()
    prepared = copy_injection_inputs(
        trading_decision={"cycleId": "cycle-live"},
        trading_cycle_runtime_result=exported["payload"]["trading_cycle_runtime_result"],
    )
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **prepared.values)
    scope = _fields(result.collection.context.tradingCycle).get("diagnosticScope")
    assert scope is None or scope.value != "CURRENT"


def test_27_non_bool_real_order_allowed_is_not_published():
    owner = _owner()
    owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True)
    exported = owner.export_context_snapshot()
    assert "execution_control" in exported["unavailable"]
    assert "realOrderAllowed" not in exported["payload"]
    assert owner.config["realOrderAllowed"] == "true"


def test_28_publish_does_not_mutate_emergency_state():
    owner = _owner()
    before = owner.emergency_marker
    owner._publish_context_snapshot(runtime_result=_runtime(), update_runtime=True)
    assert owner.emergency_marker is before
    assert owner.emergency_marker == ["ARMED"]


def test_29_money_management_stays_unavailable():
    exported = _owner().export_context_snapshot()
    assert "money_management" in exported["unavailable"]
    assert "mm_projection" not in exported["payload"]


def test_30_supervisor_stays_unavailable():
    exported = _owner().export_context_snapshot()
    assert "supervisor" in exported["unavailable"]
    assert "supervisor_bot_status" not in exported["payload"]


def test_31_rejected_runtime_keeps_a_good_paper_fragment():
    owner = _owner()
    owner._publish_context_snapshot(paper_account=_paper(), update_paper=True)

    class Locked:
        token = SECRET

    owner._publish_context_snapshot(runtime_result={"cycleId": "cycle-1", "lock": Locked()}, update_runtime=True)
    exported = owner.export_context_snapshot()
    assert exported["payload"]["position_account"]["positionState"] == "OPEN"
    assert "trading_cycle_runtime_result" not in exported["payload"]
    assert exported["errorState"] == "PARTIAL"
    assert SECRET not in str(exported)


def test_32_rejection_token_does_not_include_the_secret():
    class Box:
        def __init__(self):
            self.token = SECRET

    merged = merge_owner_snapshot(
        unavailable_owner_snapshot(),
        paper_account={"box": Box()},
        update_paper=True,
        published_at="2026-10-26T00:00:00+00:00",
    )
    assert merged["availability"] == "UNAVAILABLE"
    assert SECRET not in str(merged)


def test_33_export_is_json_compatible():
    owner = _owner()
    owner._publish_context_snapshot(paper_account=_paper(), update_paper=True)
    exported = owner.export_context_snapshot()
    assert copy_json_snapshot(exported) == exported


def test_34_owner_payload_passes_the_context_copy():
    owner = _owner()
    owner._publish_context_snapshot(
        paper_account=_paper(),
        runtime_result=_runtime(),
        update_paper=True,
        update_runtime=True,
    )
    exported = owner.export_context_snapshot()
    copied = copy_json_snapshot(exported["payload"])
    assert copied["position_account"]["lastUpdate"] == FIXED_NOW.timestamp()
    assert exported["publishedAt"] != copied["position_account"]["lastUpdate"]


def test_35_copied_payload_injects_into_the_verified_readers():
    owner = _owner()
    owner._publish_context_snapshot(paper_account=_paper(), update_paper=True)
    payload = owner.export_context_snapshot()["payload"]
    prepared = copy_injection_inputs(
        position_account=payload["position_account"],
        position_mode=payload["position_mode"],
        position_observed_at=FIXED_NOW,
    )
    result = inject_verified_runtime_snapshots(generated_at=PACK_AT, **prepared.values)
    assert _fields(result.collection.context.position)["status"].value == "OPEN"
    assert result.collection.context.position.meta.observedAt == FIXED_NOW
    assert result.collection.production_runtime_connected is False


def test_36_uninjected_collector_stays_disconnected():
    collection = collect_runtime_context(generated_at=PACK_AT)
    assert collection.production_runtime_connected is False
    assert "export_context_snapshot" not in ROUTER


def test_37_composer_keeps_the_pack_schema():
    context = compose_tradingai_context(generated_at=PACK_AT)
    assert context.schemaVersion == "tradingai-context/v1"


def test_38_operator_route_does_not_call_the_owner_export():
    assert "export_context_snapshot" not in ROUTER
    assert MAIN.count("app.include_router(context_router)") == 1


def test_39_startup_is_not_referenced():
    assert "startup_event" not in OWNER_SOURCE
    assert "backend.main" not in OWNER_SOURCE
    assert "BotManager(" not in OWNER_SOURCE


def test_40_field_contract_counts_stay_unchanged():
    from backend.context.runtime_reader_contract import (
        SOURCE_EXISTS_NOT_CONNECTED_FIELDS,
        SOURCE_NOT_FOUND_FIELDS,
        STALE_OR_UNPROVEN_FIELDS,
        UNAVAILABLE_BY_DESIGN_FIELDS,
        VERIFIED_CONNECTED_FIELDS,
    )

    assert VERIFIED_CONNECTED_FIELDS == 24
    assert SOURCE_EXISTS_NOT_CONNECTED_FIELDS == 27
    assert SOURCE_NOT_FOUND_FIELDS == 3
    assert UNAVAILABLE_BY_DESIGN_FIELDS == 8
    assert STALE_OR_UNPROVEN_FIELDS == 1


def test_unknown_position_state_is_not_rewritten_to_flat_by_merge():
    merged = merge_owner_snapshot(
        unavailable_owner_snapshot(),
        paper_account={"positionState": "UNKNOWN", "positions": [], "available": True},
        update_paper=True,
        published_at="2026-10-26T00:00:00+00:00",
    )
    assert merged["payload"]["position_account"]["positionState"] == "UNKNOWN"
    assert merged["observedAt"] is None
    assert merged["producerObservedAt"] is None
