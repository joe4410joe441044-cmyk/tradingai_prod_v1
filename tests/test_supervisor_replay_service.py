from datetime import datetime,timezone
from backend.supervisor.audit_store import SupervisorAuditStore
from backend.supervisor.history_contracts import SupervisorHistoryEvent
from backend.supervisor.replay_service import SupervisorReplayService
NOW=datetime(2026,8,13,tzinfo=timezone.utc)
def test_replay_is_projection_only_and_does_not_change_store(tmp_path):
 store=SupervisorAuditStore(tmp_path/"a.db"); store.append(SupervisorHistoryEvent(eventId="e1",eventType="MASTER_CONVERSATION_FAILURE",agentId="MASTER_SUPERVISOR",occurredAt=NOW,snapshotCapturedAt=NOW,status="FAILED_CLOSED",failureCode="SUPERVISOR_PROVIDER_TIMEOUT",summary="failed safely",providerIdentity="p",providerVersion="1")); before=store.list().stable_json()
 replay=SupervisorReplayService(store).replay("e1")
 assert replay.replayMode=="READ_ONLY" and replay.providerCalled is replay.runtimeCalled is replay.configurationChanged is False
 assert replay.operationalEffect=="NONE" and replay.orderAction=="NONE" and store.list().stable_json()==before
 assert replay.freshness is None and replay.decisionIdentity is None
