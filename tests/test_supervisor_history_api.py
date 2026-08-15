from datetime import datetime,timezone
from types import SimpleNamespace
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

def _turn(store,agent,conversation,message,answer,minute,status="COMPLETED",attention="REVIEW"):
 request=SimpleNamespace(conversationId=conversation,agentId=SimpleNamespace(value=agent),requestedAt=NOW.replace(minute=minute),message=message)
 response=SimpleNamespace(messageId=f"{agent}-{conversation}-{minute}",respondedAt=NOW.replace(minute=minute,second=1),answer=answer,status=SimpleNamespace(value=status),humanAttention=SimpleNamespace(value=attention),operationalEffect="NONE")
 store.append_conversation_turn(request,response)

def test_conversation_sessions_group_separate_order_persist_and_redact(tmp_path):
 path=tmp_path/"sessions.db"; store=SupervisorAuditStore(path)
 _turn(store,"MASTER_SUPERVISOR","master-a","first master","answer 1",1)
 _turn(store,"MASTER_SUPERVISOR","master-a","second master","answer 2",2)
 _turn(store,"MASTER_SUPERVISOR","master-b","PASSWORD=hidden","answer 3",3,"FAILED_CLOSED")
 _turn(store,"MM_SUPERVISOR","mm-a","risk?","normal",4)
 reloaded=SupervisorAuditStore(path)
 master=reloaded.list_conversation_sessions("MASTER_SUPERVISOR")
 assert [s["conversationId"] for s in master["sessions"]]==["master-b","master-a"]
 assert len(master["sessions"][1]["messages"])==4
 assert master["sessions"][0]["title"]=="[REDACTED]"
 assert "hidden" not in str(master)
 assert all(s["agentId"]=="MASTER_SUPERVISOR" for s in master["sessions"])
 assert reloaded.get_conversation_session("MASTER_SUPERVISOR","master-a")["readOnly"] is True

def test_conversation_history_api_is_get_only_empty_and_agent_scoped(tmp_path):
 store=SupervisorAuditStore(tmp_path/"sessions.db"); app=FastAPI(); app.include_router(create_supervisor_history_router(store),prefix="/api/supervisor"); client=TestClient(app)
 assert client.get("/api/supervisor/conversation/history?agentId=MASTER_SUPERVISOR").json()["sessions"]==[]
 _turn(store,"MM_SUPERVISOR","same-id","risk?","normal",1)
 assert client.get("/api/supervisor/conversation/history?agentId=MASTER_SUPERVISOR").json()["sessions"]==[]
 assert client.get("/api/supervisor/conversation/history/same-id?agentId=MASTER_SUPERVISOR").status_code==404
 assert client.get("/api/supervisor/conversation/history/same-id?agentId=MM_SUPERVISOR").status_code==200
 for method in (client.post,client.put,client.patch,client.delete): assert method("/api/supervisor/conversation/history?agentId=MM_SUPERVISOR").status_code==405
