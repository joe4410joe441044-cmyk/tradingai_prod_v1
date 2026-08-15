"""Read-only Supervisor history and replay HTTP routes."""
from fastapi import APIRouter, Query, Response
import json
from backend.supervisor.audit_store import SupervisorAuditStore
from backend.supervisor.failure_codes import SupervisorBoundaryError
from backend.supervisor.replay_service import SupervisorReplayService
from backend.supervisor.contracts import SupervisorAgentId
from backend.supervisor.history_contracts import SupervisorEventType
from backend.supervisor.failure_codes import SupervisorFailureCode

def _response(value,status=200):
    body=value.stable_json() if hasattr(value,"stable_json") else json.dumps(value,separators=(",",":"))
    return Response(content=body,media_type="application/json",status_code=status)
def create_supervisor_history_router(store: SupervisorAuditStore):
    router=APIRouter(); replay=SupervisorReplayService(store)
    @router.get("/conversation/history",response_class=Response)
    def conversation_history(agentId:str,limit:int=Query(20,ge=1,le=100)):
        try: return _response(store.list_conversation_sessions(SupervisorAgentId(agentId).value,limit))
        except ValueError: return _response({"code":SupervisorFailureCode.INPUT_INVALID.value,"message":"Conversation history filter is invalid."},400)
        except SupervisorBoundaryError: return _response({"code":SupervisorFailureCode.READ_FAILED.value,"message":"Conversation history is unavailable."},503)
    @router.get("/conversation/history/{conversation_id}",response_class=Response)
    def conversation_session(conversation_id:str,agentId:str):
        try: return _response(store.get_conversation_session(SupervisorAgentId(agentId).value,conversation_id))
        except SupervisorBoundaryError as e: return _response({"code":e.code.value,"message":"Conversation session is unavailable."},404 if e.code is SupervisorFailureCode.EVENT_NOT_FOUND else 503)
        except ValueError: return _response({"code":SupervisorFailureCode.INPUT_INVALID.value,"message":"Conversation history filter is invalid."},400)
    @router.get("/history",response_class=Response)
    def history(agentId:str|None=None,eventType:str|None=None,status:str|None=None,limit:int=Query(20,ge=1,le=100),cursor:str|None=None):
        try:
            if agentId is not None: SupervisorAgentId(agentId)
            if eventType is not None: SupervisorEventType(eventType)
            if status is not None and status not in {"COMPLETED","FAILED_CLOSED","UNAVAILABLE"}:
                raise ValueError("unknown status")
            return _response(store.list(agent_id=agentId,event_type=eventType,status=status,limit=limit,cursor=cursor))
        except ValueError: return _response({"code":SupervisorFailureCode.INPUT_INVALID.value,"message":"Supervisor history filter is invalid."},400)
        except SupervisorBoundaryError as e: return _response({"code":e.code.value,"message":"Supervisor history is unavailable."},400 if "CURSOR" in e.code.value or "INPUT" in e.code.value else 503)
    @router.get("/history/{event_id}",response_class=Response)
    def event(event_id:str):
        try: return _response(store.get(event_id))
        except SupervisorBoundaryError as e: return _response({"code":e.code.value,"message":"Supervisor history event is unavailable."},404 if "NOT_FOUND" in e.code.value else 503)
    @router.get("/history/{event_id}/replay",response_class=Response)
    def replay_event(event_id:str):
        try: return _response(replay.replay(event_id))
        except SupervisorBoundaryError as e: return _response({"code":e.code.value,"message":"Supervisor replay is unavailable."},404 if "NOT_FOUND" in e.code.value else 503)
    return router
