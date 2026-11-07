"""Isolated owner-snapshot to operator-context tests.

No Production import, no BotManager constructor, and no exchange client.
"""

from __future__ import annotations

import ast
import inspect
import socket
import sys
import time
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.bot_manager.owner_snapshot import unavailable_owner_snapshot
from backend.context.api_contract import (
    OPERATOR_JSON_PATH,
    OPERATOR_MARKDOWN_PATH,
    PRODUCTION_API_AVAILABLE,
    PRODUCTION_RUNTIME_CONNECTED,
)
from backend.context.api_router import (
    ContextReadInputs,
    build_operator_http_body,
    create_isolated_context_app,
)
from backend.context.owner_context_bridge import (
    collection_from_owner_document,
    copied_owner_export,
    existing_owner_from_process,
    unavailable_owner_document,
)
from backend.context.runtime_projection import parse_producer_time
from backend.context.runtime_reader_contract import VERIFIED_CONNECTED_FIELDS
from tests.test_ai_context_support import FIXED_NOW

REPO = Path(__file__).resolve().parents[1]
BRIDGE = (REPO / "backend/context/owner_context_bridge.py").read_text(encoding="utf-8")
ROUTER = (REPO / "backend/context/api_router.py").read_text(encoding="utf-8")
SECRET = "SECRET_BB4J_TOKEN"
SESSION_SECRET = "c" * 32
PACK_AT = FIXED_NOW
PUBLISHED_AT = "2026-10-24T00:00:00+00:00"
FORBIDDEN_CALLS = (
    "get_bot_manager(",
    "get_status(",
    "get_result(",
    "_observe_runtime_decision(",
    "_capture_account_snapshot(",
    "_refresh_real_account_snapshot(",
    "_build_paper_account_runtime(",
    "MoneyManagementHttpBoundary",
    "RuntimeSnapshotAdapter.build(",
    "get_control_plane(",
    "get_account_overview(",
    "KucoinTradeClient(",
    "BotManager(",
    "load_dotenv(",
)


class FakeOwner:
    def __init__(self, document):
        self.document = document
        self.exports = 0

    def export_context_snapshot(self):
        self.exports += 1
        return self.document

    def get_result(self):
        raise AssertionError("get_result")

    def get_status(self):
        raise AssertionError("get_status")

    def get_bot_manager(self):
        raise AssertionError("get_bot_manager")


def _config() -> OperatorAuthConfig:
    return OperatorAuthConfig(session_secret=SESSION_SECRET, session_ttl_seconds=3600)


def _app(owner=None):
    manager = OperatorSessionManager(SESSION_SECRET, session_ttl_seconds=3600)
    app = create_isolated_context_app(session_manager=manager, config=_config())
    if owner is not None:
        app.state.context_owner_lookup = lambda: owner
    return app, manager


def _cookie(manager: OperatorSessionManager) -> dict[str, str]:
    session = manager.create_session("operator")
    return {COOKIE_NAME: manager.sign(session.session_id)}


def _client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _paper(*, last_update=None, state="OPEN"):
    account = {
        "available": True,
        "positionState": state,
        "positions": [
            {
                "symbol": "XRPUSDTM",
                "side": "LONG",
                "qty": 2,
                "entry_price": 0.5,
                "entry_time": FIXED_NOW.timestamp() - 30,
                "coin_qty": 20,
            }
        ],
    }
    if last_update is not None:
        account["lastUpdate"] = last_update
    return account


def _document(*, paper=None, runtime=None, mode="PAPER", published_at=PUBLISHED_AT):
    payload = {}
    if paper is not None:
        payload["position_account"] = paper
        payload["position_mode"] = mode
    if runtime is not None:
        payload["trading_cycle_runtime_result"] = runtime
    ready = bool(payload)
    return {
        "schemaVersion": "tradingai-owner-snapshot/v1",
        "source": "bot_manager_publication",
        "owner": "BotManager",
        "availability": "READY" if ready else "UNAVAILABLE",
        "publishedAt": published_at,
        "observedAt": None,
        "producerObservedAt": None,
        "revision": 3 if ready else 0,
        "errorState": None if ready else "NOT_PUBLISHED",
        "unavailable": [
            "real_account",
            "execution_control",
            "money_management",
            "supervisor",
        ],
        "payload": payload,
    }


def _runtime(cycle_id="cycle-stored", evaluated_at=None):
    readiness = {"cycleId": cycle_id}
    if evaluated_at is not None:
        readiness["evaluatedAt"] = evaluated_at
    return {"strategyOutput": {"strategy": {"entryReadiness": readiness}}}


def _fields(body, section):
    return {
        item["name"]: item
        for item in body["context"]["sections"][section]["fields"]
    }


def _fresh_stamp():
    return time.time() - 5


def _same_clock(left, right) -> bool:
    return parse_producer_time(left) == parse_producer_time(right)


def _body(owner, path=OPERATOR_JSON_PATH, authenticated=True):
    app, manager = _app(owner)
    cookies = _cookie(manager) if authenticated else {}
    response = _client(app).get(path, cookies=cookies)
    return response


def test_01_worktree_branch_file_is_isolated():
    assert (REPO / "backend/context/owner_context_bridge.py").is_file()
    assert "backend.main" not in BRIDGE


def test_02_reconciliation_does_not_import_main_changes():
    assert "loss_execution_integration" not in BRIDGE
    assert "execution authority preview" not in ROUTER


def test_03_existing_owner_reference_does_not_import_the_manager_module():
    saved = sys.modules.pop("backend.bot_manager.bot_manager", None)
    try:
        assert existing_owner_from_process() is None
        assert "backend.bot_manager.bot_manager" not in sys.modules
    finally:
        if saved is not None:
            sys.modules["backend.bot_manager.bot_manager"] = saved


def test_04_bridge_does_not_construct_a_manager():
    assert "BotManager(" not in BRIDGE
    tree = ast.parse(BRIDGE)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "backend.bot_manager.bot_manager" not in imported
    assert "backend.main" not in imported


def test_05_forbidden_runtime_calls_are_absent():
    for token in FORBIDDEN_CALLS:
        assert token not in BRIDGE
        assert token not in ROUTER


def test_06_router_does_not_call_status_readers():
    assert "get_status(" not in ROUTER
    assert "get_result(" not in ROUTER


def test_07_router_does_not_call_the_constructor_helper():
    assert "get_bot_manager(" not in ROUTER
    assert "get_bot_manager(" not in BRIDGE


def test_08_strategy_evaluation_is_not_referenced():
    assert "_observe_runtime_decision(" not in BRIDGE
    assert "process_runtime(" not in BRIDGE


def test_09_account_refresh_is_not_referenced():
    assert "_refresh_real_account_snapshot(" not in BRIDGE
    assert "_capture_account_snapshot(" not in BRIDGE
    assert "_build_paper_account_runtime(" not in BRIDGE


def test_10_money_management_boundary_is_not_referenced():
    assert "MoneyManagementHttpBoundary" not in BRIDGE


def test_11_exchange_client_is_not_referenced():
    assert "KucoinTradeClient" not in BRIDGE
    assert "get_account_overview(" not in BRIDGE


def test_12_supervisor_start_is_not_referenced():
    assert "get_control_plane(" not in BRIDGE
    assert "RuntimeSnapshotAdapter" not in BRIDGE


def test_13_export_copies_the_owner_document():
    document = _document(paper=_paper(last_update=PACK_AT.timestamp()))
    owner = FakeOwner(document)
    exported = copied_owner_export(owner)
    assert owner.exports == 1
    assert exported["availability"] == "READY"
    assert exported is not document


def test_14_export_mutation_does_not_change_the_stored_document():
    document = _document(paper=_paper(last_update=PACK_AT.timestamp()))
    owner = FakeOwner(document)
    exported = copied_owner_export(owner)
    exported["payload"]["position_account"]["positions"][0]["qty"] = 99
    assert document["payload"]["position_account"]["positions"][0]["qty"] == 2


def test_15_unavailable_document_matches_the_owner_publisher():
    assert unavailable_owner_document() == unavailable_owner_snapshot()


def test_16_paper_account_reaches_the_operator_position():
    owner = FakeOwner(_document(paper=_paper(last_update=_fresh_stamp())))
    response = _body(owner)
    assert response.status_code == 200
    fields = _fields(response.json(), "position")
    assert fields["status"]["value"] == "OPEN"
    assert fields["mode"]["value"] == "PAPER"
    assert fields["symbol"]["value"] == "XRPUSDTM"


def test_17_paper_is_not_reported_as_live():
    owner = FakeOwner(_document(paper=_paper(last_update=_fresh_stamp())))
    fields = _fields(_body(owner).json(), "position")
    assert fields["mode"]["value"] == "PAPER"
    assert fields["mode"]["value"] != "LIVE"


def test_18_position_uses_only_the_stored_mapping():
    owner = FakeOwner(_document(paper=_paper(last_update=_fresh_stamp())))
    fields = _fields(_body(owner).json(), "position")
    assert fields["quantity"]["value"] == 20 or fields["coinQuantity"]["value"] == 20
    assert fields["side"]["value"] == "LONG"


def test_19_stored_runtime_result_is_injected():
    owner = FakeOwner(_document(runtime=_runtime()))
    body = _body(owner).json()
    assert body["productionRuntimeConnected"] is False
    scope = _fields(body, "tradingCycle")["diagnosticScope"]["value"]
    assert scope != "CURRENT"


def test_20_missing_producer_timestamp_stays_unknown():
    paper = _paper()
    paper["positionState"] = "UNKNOWN"
    paper["positions"] = []
    owner = FakeOwner(_document(paper=paper))
    fields = _fields(_body(owner).json(), "position")
    assert fields["status"]["value"] == "UNKNOWN"
    assert fields["status"]["observedAt"] is None


def test_21_stale_last_update_is_not_marked_fresh():
    old = time.time() - 1000
    owner = FakeOwner(_document(paper=_paper(last_update=old)))
    status = _fields(_body(owner).json(), "position")["status"]
    assert status["freshness"] == "STALE"
    assert status["value"] != "OPEN"
    assert _same_clock(status["observedAt"], old)
    assert not _same_clock(status["observedAt"], PUBLISHED_AT)


def test_22_unknown_position_state_is_preserved():
    paper = _paper(last_update=_fresh_stamp(), state="UNKNOWN")
    paper["positions"] = []
    owner = FakeOwner(_document(paper=paper))
    assert _fields(_body(owner).json(), "position")["status"]["value"] == "UNKNOWN"


def test_23_missing_owner_stays_unavailable():
    response = _body(FakeOwner(unavailable_owner_snapshot()))
    body = response.json()
    assert response.status_code == 200
    assert body["context"]["sections"]["account"]["meta"]["availability"] == "UNAVAILABLE"
    failures = {item["source"]: item["category"] for item in body["context"]["readerFailures"]}
    assert failures["position"] == "READER_NOT_INJECTED"
    assert "money_management" in unavailable_owner_snapshot()["unavailable"]


def test_24_partial_paper_snapshot_keeps_position_and_skips_cycle_current():
    owner = FakeOwner(
        _document(paper=_paper(last_update=_fresh_stamp()), runtime=None)
    )
    body = _body(owner).json()
    assert _fields(body, "position")["status"]["value"] == "OPEN"
    assert body["context"]["sections"]["moneyManagement"]["meta"]["availability"] == "UNAVAILABLE"


def test_25_invalid_snapshot_does_not_become_a_position():
    owner = FakeOwner({"schemaVersion": "other", "payload": _paper()})
    body = _body(owner).json()
    failures = {item["source"]: item["category"] for item in body["context"]["readerFailures"]}
    assert failures["position"] == "READER_NOT_INJECTED"


def test_26_copy_rejects_a_lock_and_sanitizes_the_error():
    class Locked:
        token = SECRET

    owner = FakeOwner(_document(paper={"box": Locked(), "positionState": "OPEN"}))
    response = _body(owner)
    assert response.status_code == 200
    assert SECRET not in response.text
    assert "Locked" not in response.text


def test_27_injection_chain_is_the_existing_boundary():
    source = inspect.getsource(collection_from_owner_document)
    assert "copy_json_snapshot(" in source
    assert "copy_injection_inputs(" in source
    assert "inject_verified_runtime_snapshots(" in source


def test_28_builder_result_keeps_the_canonical_schema():
    document = _document(paper=_paper(last_update=PACK_AT.timestamp() - 10))
    collection = collection_from_owner_document(document, PACK_AT)
    assert collection.context.schemaVersion == "tradingai-context/v1"
    assert collection.production_runtime_connected is False


def test_29_operator_view_receives_the_paper_position():
    document = _document(paper=_paper(last_update=PACK_AT.timestamp() - 10))
    status, body = build_operator_http_body(
        ContextReadInputs(generated_at=PACK_AT, owner_snapshot=document)
    )
    assert status == 200
    assert body["view"] == "OPERATOR_CONTEXT"
    assert _fields(body, "position")["status"]["value"] == "OPEN"


def test_30_public_view_does_not_receive_the_owner_position():
    document = _document(
        paper={
            **_paper(last_update=PACK_AT.timestamp() - 10),
            "apiKey": SECRET,
        }
    )
    collection = collection_from_owner_document(document, PACK_AT)
    public = collection.public_view
    text = str(public)
    assert SECRET not in text
    assert "XRPUSDTM" not in text
    assert "position" not in public


def test_31_missing_session_is_401():
    owner = FakeOwner(_document(paper=_paper(last_update=PACK_AT.timestamp() - 10)))
    response = _body(owner, authenticated=False)
    assert response.status_code == 401
    assert SECRET not in response.text


def test_32_authenticated_request_is_200_without_production_flags():
    owner = FakeOwner(_document(paper=_paper(last_update=PACK_AT.timestamp() - 10)))
    body = _body(owner).json()
    assert body["status"] == "OK"
    assert body["productionRuntimeConnected"] is False
    assert body["productionApiAvailable"] is False
    assert PRODUCTION_RUNTIME_CONNECTED is False
    assert PRODUCTION_API_AVAILABLE is False


def test_33_markdown_endpoint_uses_the_same_owner_snapshot():
    owner = FakeOwner(_document(paper=_paper(last_update=_fresh_stamp())))
    response = _body(owner, path=OPERATOR_MARKDOWN_PATH)
    assert response.status_code == 200
    assert "markdown" in response.headers["content-type"]
    assert "OPEN" in response.text
    assert "XRPUSDTM" in response.text
    assert PUBLISHED_AT not in response.text
    assert SECRET not in response.text


def test_34_json_endpoint_path_is_the_existing_operator_route():
    response = _body(FakeOwner(_document(runtime=_runtime())))
    assert response.status_code == 200
    assert response.request.url.path == OPERATOR_JSON_PATH


def test_35_exception_text_is_not_returned():
    class Boom(FakeOwner):
        def export_context_snapshot(self):
            raise RuntimeError(SECRET)

    response = _body(Boom(None))
    assert response.status_code == 200
    assert SECRET not in response.text
    assert "RuntimeError" not in response.text


def test_36_secret_in_the_paper_mapping_is_not_in_the_operator_body():
    paper = _paper(last_update=_fresh_stamp())
    paper["apiKey"] = SECRET
    paper["session"] = SECRET
    response = _body(FakeOwner(_document(paper=paper)))
    assert SECRET not in response.text
    assert "apiKey" not in response.text


def test_37_export_does_not_call_mutating_methods():
    owner = FakeOwner(_document(paper=_paper(last_update=_fresh_stamp())))
    copied_owner_export(owner)
    assert owner.exports == 1


def test_38_request_does_not_open_a_socket(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("socket")

    monkeypatch.setattr(socket, "socket", boom)
    status, body = build_operator_http_body(
        ContextReadInputs(
            generated_at=PACK_AT,
            owner_snapshot=_document(paper=_paper(last_update=PACK_AT.timestamp() - 10)),
        )
    )
    assert status == 200
    assert _fields(body, "position")["status"]["value"] == "OPEN"


def test_39_context_package_import_does_not_load_the_manager_module():
    source = (REPO / "backend/context/__init__.py").read_text(encoding="utf-8")
    assert "bot_manager" not in source
    assert "load_dotenv(" not in BRIDGE


def test_40_production_connected_field_count_stays_unchanged():
    assert VERIFIED_CONNECTED_FIELDS == 24


def test_published_at_is_not_the_position_producer_time():
    old = time.time() - 1000
    owner = FakeOwner(_document(paper=_paper(last_update=old)))
    observed = _fields(_body(owner).json(), "position")["status"]["observedAt"]
    assert _same_clock(observed, old)
    assert not _same_clock(observed, PUBLISHED_AT)


def test_cycle_producer_time_is_not_replaced_by_the_pack_stamp():
    producer = (PACK_AT - timedelta(minutes=5)).isoformat()
    owner = FakeOwner(_document(runtime=_runtime(evaluated_at=producer)))
    fields = _fields(_body(owner).json(), "tradingCycle")
    assert fields["diagnosticScope"]["value"] != "CURRENT"
    assert _same_clock(fields["diagnosticsGeneratedAt"]["observedAt"], producer)
    assert not _same_clock(fields["diagnosticsGeneratedAt"]["observedAt"], PUBLISHED_AT)


def test_live_mode_document_is_not_injected_as_paper():
    owner = FakeOwner(
        _document(paper=_paper(last_update=_fresh_stamp()), mode="LIVE")
    )
    body = _body(owner).json()
    failures = {item["source"]: item["category"] for item in body["context"]["readerFailures"]}
    assert failures["position"] == "READER_NOT_INJECTED"


def test_flags_remain_false_on_the_contract():
    assert PRODUCTION_RUNTIME_CONNECTED is False
    assert PRODUCTION_API_AVAILABLE is False
