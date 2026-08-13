from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.supervisor_conversation import create_supervisor_conversation_router
from backend.supervisor.contracts import HumanAttention, SupervisorAgentId
from backend.supervisor.conversation_contracts import (
    ConversationStatus,
    SupervisorConversationResponse,
)


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


class StubService:
    def __init__(self):
        self.requests = []

    def respond(self, app, request):
        self.requests.append(request)
        return SupervisorConversationResponse(
            agentId=request.agentId,
            conversationId=request.conversationId,
            messageId="message-1",
            status=ConversationStatus.UNAVAILABLE,
            answer="Supervisor AI provider is not connected.",
            humanAttention=HumanAttention.REVIEW,
            snapshotCapturedAt=NOW,
            failureCode="SUPERVISOR_PROVIDER_UNAVAILABLE",
            respondedAt=NOW,
        )


def client():
    service = StubService()
    app = FastAPI()
    app.include_router(create_supervisor_conversation_router(service), prefix="/api/supervisor")
    return TestClient(app), service


def payload(agent="MASTER_SUPERVISOR", message="現在の状態は？"):
    return {
        "schemaVersion": 1,
        "agentId": agent,
        "message": message,
        "conversationId": "conversation-1",
        "requestedAt": NOW.isoformat(),
    }


def test_master_and_mm_endpoints_route_only_the_explicit_agent():
    api, service = client()
    master = api.post("/api/supervisor/conversation/master", json=payload())
    mm = api.post("/api/supervisor/conversation/mm", json=payload("MM_SUPERVISOR", "Riskについて"))
    assert master.status_code == mm.status_code == 200
    assert [item.agentId for item in service.requests] == [
        SupervisorAgentId.MASTER_SUPERVISOR,
        SupervisorAgentId.MM_SUPERVISOR,
    ]
    for response in (master, mm):
        assert response.json()["mode"] == "SHADOW"
        assert response.json()["operationalEffect"] == "NONE"
        assert response.json()["configurationChanged"] is False


def test_unknown_or_cross_routed_agent_is_rejected():
    api, service = client()
    assert api.post("/api/supervisor/conversation/master", json=payload("UNKNOWN")).status_code == 400
    assert api.post("/api/supervisor/conversation/master", json=payload("MM_SUPERVISOR")).status_code == 400
    assert service.requests == []


def test_empty_oversized_extra_and_timezone_naive_requests_are_sanitized():
    api, service = client()
    cases = [payload(message=" "), payload(message="x" * 1001), payload() | {"apiKey": "SECRET_VALUE"}]
    naive = payload()
    naive["requestedAt"] = "2026-08-13T00:00:00"
    cases.append(naive)
    for value in cases:
        response = api.post("/api/supervisor/conversation/master", json=value)
        assert response.status_code == 400
        assert "SECRET_VALUE" not in response.text
        assert "traceback" not in response.text.lower()
    assert service.requests == []
