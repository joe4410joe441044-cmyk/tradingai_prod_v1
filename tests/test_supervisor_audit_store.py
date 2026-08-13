from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import sqlite3
import pytest
from backend.supervisor.audit_store import SupervisorAuditStore
from backend.supervisor.failure_codes import SupervisorBoundaryError,SupervisorFailureCode
from backend.supervisor.history_contracts import SupervisorHistoryEvent
NOW=datetime(2026,8,13,tzinfo=timezone.utc)
def event(i,agent="MM_SUPERVISOR",status="COMPLETED"):
 return SupervisorHistoryEvent(eventId=f"event-{i}",eventType="MM_SHADOW_ASSESSMENT",agentId=agent,occurredAt=NOW,snapshotCapturedAt=NOW,status=status,summary="sanitized",providerIdentity="test",providerVersion="1")
def test_append_duplicate_pagination_filter_and_immutability(tmp_path):
 store=SupervisorAuditStore(tmp_path/"audit.db",max_events=10); store.append(event(1)); store.append(event(2,"MASTER_SUPERVISOR"));
 with pytest.raises(SupervisorBoundaryError) as e: store.append(event(1))
 assert e.value.code is SupervisorFailureCode.DUPLICATE_EVENT
 assert store.get("event-1").summary=="sanitized"; assert len(store.list(agent_id="MASTER_SUPERVISOR").events)==1
 page=store.list(limit=1); assert page.nextCursor; assert len(store.list(limit=1,cursor=page.nextCursor).events)==1
 with pytest.raises(SupervisorBoundaryError): store.list(cursor="../bad")
 with sqlite3.connect(tmp_path/"audit.db") as db:
  assert "UPDATE" not in " ".join(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
def test_concurrent_append_retention_and_not_found(tmp_path):
 store=SupervisorAuditStore(tmp_path/"audit.db",max_events=20)
 with ThreadPoolExecutor(max_workers=5) as pool: list(pool.map(lambda i:store.append(event(i)),range(10)))
 assert len(store.list(limit=20).events)==10
 with pytest.raises(SupervisorBoundaryError) as e: store.get("missing")
 assert e.value.code is SupervisorFailureCode.EVENT_NOT_FOUND
 full=SupervisorAuditStore(tmp_path/"full.db",max_events=1); full.append(event(1))
 with pytest.raises(SupervisorBoundaryError) as e: full.append(event(2))
 assert e.value.code is SupervisorFailureCode.STORE_FULL
def test_payload_contains_no_raw_message_secret_or_traceback(tmp_path):
 store=SupervisorAuditStore(tmp_path/"audit.db"); store.append(event(1)); data=(tmp_path/"audit.db").read_bytes()
 for forbidden in (b"raw user message",b"SECRET_VALUE",b"traceback"): assert forbidden not in data
