from datetime import datetime,timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api.supervisor_history import create_supervisor_history_router
from backend.supervisor.audit_store import SupervisorAuditStore
from backend.supervisor.history_contracts import SupervisorHistoryEvent
NOW=datetime(2026,8,13,tzinfo=timezone.utc)
def test_history_routes_are_get_only_paginated_and_sanitized(tmp_path):
 store=SupervisorAuditStore(tmp_path/"a.db"); store.append(SupervisorHistoryEvent(eventId="e1",eventType="MM_CONVERSATION_SUCCESS",agentId="MM_SUPERVISOR",occurredAt=NOW,snapshotCapturedAt=NOW,status="COMPLETED",summary="safe",providerIdentity="p",providerVersion="1")); app=FastAPI(); app.include_router(create_supervisor_history_router(store),prefix="/api/supervisor"); client=TestClient(app)
 assert client.get("/api/supervisor/history?limit=1").json()["order"]=="NEWEST_FIRST"
 replay=client.get("/api/supervisor/history/e1/replay").json(); assert replay["providerCalled"] is False and replay["runtimeCalled"] is False
 for method in (client.post,client.put,client.patch,client.delete): assert method("/api/supervisor/history").status_code==405
 assert client.get("/api/supervisor/history?cursor=bad").status_code==400
 assert client.get("/api/supervisor/history?agentId=UNKNOWN").status_code==400
 assert client.get("/api/supervisor/history?eventType=UNKNOWN").status_code==400
 assert client.get("/api/supervisor/history/missing").status_code==404
