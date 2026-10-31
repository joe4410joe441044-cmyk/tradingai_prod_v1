"""Default publication wiring for already-held owner caches."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_advisor.advisor_service import AdvisorService
from backend.api.supervisor_conversation import create_supervisor_conversation_router
from backend.bot_manager.bot_manager import BotManager
from backend.bot_manager.owner_snapshot import unavailable_owner_snapshot
from backend.context.project_evidence import collect_project_evidence
from backend.context.shared_answer_context import (
    load_shared_operator_context,
    render_canonical_context_block,
)
from backend.supervisor.contracts import SupervisorAgentId
from backend.supervisor.conversation_contracts import SupervisorConversationRequest
from backend.supervisor.conversation_service import SupervisorConversationService
from tests.test_ai_advisor_provider_contract import capabilities, config, model_policy
from tests.test_ai_advisor_service import service_input
from tests.test_ai_context_advisor_supervisor_integration import (
    NOW,
    App,
    FakeOwner,
    RecordingAdvisorProvider,
    RecordingProvider,
    SnapshotAdapter,
)

ROOT = Path("/home/joe4410joe/tradingai_prod_v1.worktrees/ai-runtime-owner-wiring")
QUESTION = "現在のRuntime状態は？"


class _State:
    def __init__(self):
        self.emergency_stop = True
        self.pending_order = None
        self.evaluations = 0

    def reevaluate(self):
        self.evaluations += 1


class _Metrics:
    def __init__(self, valid=True, equity=None):
        self.calls = 0
        self.valid = valid
        self.equity = equity

    def snapshot(self):
        self.calls += 1
        return _Snap(self.valid, self.equity)

    def recalculate(self):
        raise AssertionError("recalculate")


class _Snap:
    def __init__(self, valid, equity):
        self.observation_valid = valid
        self.source_state = "RUNNING" if valid else "NOT_INITIALIZED"
        self.current_equity = equity
        self.available_balance = None
        self.open_exposure = None
        self.current_drawdown_pct = None
        self.position_count = 2
        self.revision = 4
        self.as_of = datetime(2026, 10, 25, tzinfo=timezone.utc)
        self.peak_equity = Decimal("999")


def _owner():
    owner = BotManager.__new__(BotManager)
    owner._context_publication_lock = threading.Lock()
    owner._context_publication = unavailable_owner_snapshot()
    owner.paper_capital_lock = threading.RLock()
    owner.paper_account_runtime_snapshot = None
    owner.emergency_marker = ["ARMED"]
    owner.config = {"realOrderAllowed": "true", "mode": "LIVE"}
    owner.syncs = 0
    owner.supervisor_builds = 0
    owner.market_fetches = 0
    return owner


def _arm(owner):
    owner.state = _State()
    owner.selection_mode = "MANUAL"
    owner._active_symbol = "XRPUSDTM"
    owner.money_management_runtime_metrics = _Metrics(equity=Decimal("10.50"))
    owner.real_account_snapshot = {
        "connected": True,
        "authenticated": False,
        "accountType": "UNKNOWN",
        "lastSync": datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp(),
        "permission": "NOT_VERIFIED",
        "stale": True,
        "apiKey": "supersecretvalue",
        "balance": 10,
    }
    owner.market_snapshot = {
        "exchangeSymbol": "XRPUSDTM",
        "dataQuality": "VALID",
        "timestamp": "2026-10-25T00:00:00Z",
        "orderBook": {"bids": [[1, 1]] * 50},
        "recentTrades": [{"price": 1}] * 50,
    }
    return owner


def test_t01_t07_default_publish_copies_held_caches():
    owner = _arm(_owner())
    marker = owner.emergency_marker
    owner._publish_context_snapshot()
    exported = owner.export_context_snapshot()
    payload = exported["payload"]
    assert payload["execution_control"]["emergencyStop"] is True
    assert payload["execution_control"]["pendingOrder"] is None
    assert payload["execution_control"]["orderEffect"] == "NONE"
    assert "realOrderAllowed" not in payload["execution_control"]
    assert payload["money_management"]["equity"] == "10.50"
    assert payload["money_management"]["availableCapital"] is None
    assert "peakEquity" not in payload["money_management"]
    assert payload["real_account"]["connectionState"] is True
    assert payload["real_account"]["freshness"] == "STALE"
    assert payload["market_selection"]["activeSymbol"] == "XRPUSDTM"
    assert payload["market_selection"]["selectionMode"] == "MANUAL"
    assert payload["market_intelligence"]["activeMarket"] == "XRPUSDTM"
    assert "orderBook" not in json.dumps(payload["market_intelligence"])
    assert "recentTrades" not in json.dumps(payload["market_intelligence"])
    assert "supervisor" in exported["unavailable"]
    assert owner.emergency_marker is marker
    assert owner.state.evaluations == 0
    assert owner.money_management_runtime_metrics.calls == 1
    assert owner.syncs == 0
    assert owner.supervisor_builds == 0
    assert owner.market_fetches == 0
    assert "supersecretvalue" not in json.dumps(exported)
    assert exported["publishedAt"] != payload["money_management"]["producerObservedAt"]


def test_t08_t10_missing_or_unverified_state_is_not_current():
    bare = _owner()
    bare._publish_context_snapshot()
    exported = bare.export_context_snapshot()
    for name in ("execution_control", "money_management", "real_account", "supervisor"):
        assert name in exported["unavailable"]
    unsynced = _owner()
    unsynced.real_account_snapshot = {"balance": 10, "connected": False}
    unsynced._publish_context_snapshot()
    assert "real_account" in unsynced.export_context_snapshot()["unavailable"]
    invalid = _owner()
    invalid.money_management_runtime_metrics = _Metrics(valid=False)
    invalid._publish_context_snapshot()
    assert "money_management" in invalid.export_context_snapshot()["unavailable"]
    owner = _arm(_owner())
    owner._publish_context_snapshot()
    evidence_owner = FakeOwner(owner.export_context_snapshot())
    attachment = load_shared_operator_context(
        App(evidence_owner), question=QUESTION, repository=ROOT
    )
    domains = attachment["runtimeEvidence"]["domains"]
    assert domains["executionAuthority"]["runtimeTimestamp"] == "UNKNOWN"
    assert domains["executionAuthority"]["runtimeStatus"] != "CURRENT"
    assert domains["moneyManagement"]["runtimeStatus"] != "CURRENT"
    assert domains["moneyManagement"]["runtimeValues"]["equity"] == "10.50"
    assert domains["liveAccount"]["runtimeStatus"] == "STALE"
    assert domains["liveAccount"]["runtimeStatus"] != "CURRENT"
    assert domains["marketSelection"]["runtimeStatus"] != "CURRENT"
    assert domains["marketIntelligence"]["runtimeStatus"] != "CURRENT"
    assert domains["supervisorRuntime"]["runtimeStatus"] == "UNAVAILABLE"


def test_t18_t34_shared_context_and_boundaries():
    owner = _arm(_owner())
    owner._publish_context_snapshot()
    document = owner.export_context_snapshot()
    attachment = load_shared_operator_context(
        App(FakeOwner(document)), question="TradingAIで注文を制御する関数は？", repository=ROOT
    )
    assert "place_order_safe" in {
        item["sourceSymbol"] for item in attachment["sourceEvidence"]["items"]
    }
    project = collect_project_evidence("Money Managementはどのような設計？", ROOT)
    assert project["reason"] == "HASH_MISMATCH"
    assert attachment["decisionEvidence"]["truthKind"] == "DECISION_TRUTH"
    assert attachment["operatorView"]["schemaVersion"] == "tradingai-context/v1"
    provider = RecordingAdvisorProvider()
    advisor = AdvisorService(
        provider=provider,
        providerConfig=config(),
        modelPolicy=model_policy(),
        capabilities=capabilities(),
    )
    result = advisor.generate_response(
        service_input(canonicalContextBlock=render_canonical_context_block(attachment))
    )
    assert result.status.value == "SUCCEEDED"
    assert "runtimeEvidence" not in result.model_dump()
    assert "executionAuthority" in provider.requests[0].renderedPrompt
    service = SupervisorConversationService(
        snapshot_adapter=SnapshotAdapter(),
        provider=RecordingProvider(),
        clock=lambda: NOW,
    )
    request = SupervisorConversationRequest(
        agentId=SupervisorAgentId.MASTER_SUPERVISOR,
        message=QUESTION,
        conversationId="conversation-1",
        requestedAt=NOW,
    )
    master = service.respond(object(), request, canonical_context=attachment)
    mm = service.respond(
        object(),
        SupervisorConversationRequest(
            agentId=SupervisorAgentId.MM_SUPERVISOR,
            message=QUESTION,
            conversationId="conversation-1",
            requestedAt=NOW,
        ),
        canonical_context=attachment,
    )
    assert master.mode.value == "SHADOW"
    assert mm.mode.value == "SHADOW"
    conversation = next(
        payload
        for name, payload in service._provider.inputs
        if name == "SupervisorConversationProviderOutput"
    )
    assert conversation["operationalEffect"] == "NONE"
    calls = []

    def spy(document):
        calls.append(True)
        return {"truthKind": "RUNTIME_TRUTH"}

    import backend.context.runtime_evidence as runtime_evidence

    original = runtime_evidence.collect_runtime_evidence
    runtime_evidence.collect_runtime_evidence = spy
    try:
        app = FastAPI()
        app.include_router(create_supervisor_conversation_router(service))
        denied = TestClient(app).post(
            "/conversation/master",
            json={
                "agentId": "MASTER_SUPERVISOR",
                "message": QUESTION,
                "conversationId": "conversation-1",
                "requestedAt": "2026-08-13T00:00:00Z",
            },
        )
        assert denied.status_code == 200
        assert calls == []
        assert "supersecretvalue" not in denied.text
    finally:
        runtime_evidence.collect_runtime_evidence = original
    source = (ROOT / "backend/bot_manager/owner_snapshot.py").read_text(encoding="utf-8")
    for name in ("get_result", "Kucoin", "preview_new_entry", "place_order", "requests"):
        assert name not in source
