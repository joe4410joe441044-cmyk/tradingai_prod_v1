"""Sanitized HTTP boundary for Supervisor SHADOW conversations."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from backend.supervisor.contracts import SupervisorAgentId
from backend.supervisor.conversation_contracts import SupervisorConversationRequest
from backend.supervisor.conversation_service import SupervisorConversationService


def _json_response(body: dict | str, status_code: int = 200) -> Response:
    content = body if isinstance(body, str) else json.dumps(body, sort_keys=True, separators=(",", ":"))
    return Response(content=content, media_type="application/json", status_code=status_code)


def _invalid_response() -> Response:
    return _json_response({
        "code": "SUPERVISOR_INPUT_INVALID",
        "message": "Supervisor conversation request is invalid.",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }, 400)


def create_supervisor_conversation_router(
    service: SupervisorConversationService | None = None,
) -> APIRouter:
    conversation_service = service or SupervisorConversationService()
    router = APIRouter()

    async def handle(request: Request, expected_agent: SupervisorAgentId) -> Response:
        try:
            raw = await request.json()
            if not isinstance(raw, dict):
                return _invalid_response()
            parsed = SupervisorConversationRequest.model_validate(raw)
            if parsed.agentId is not expected_agent:
                return _invalid_response()
            response = conversation_service.respond(request.app, parsed)
            return _json_response(response.stable_json())
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
            return _invalid_response()
        except Exception:
            return _json_response({
                "code": "SUPERVISOR_FAIL_CLOSED",
                "message": "Supervisor conversation is unavailable.",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }, 503)

    @router.post("/conversation/master", response_class=Response)
    async def master_conversation(request: Request) -> Response:
        return await handle(request, SupervisorAgentId.MASTER_SUPERVISOR)

    @router.post("/conversation/mm", response_class=Response)
    async def mm_conversation(request: Request) -> Response:
        return await handle(request, SupervisorAgentId.MM_SUPERVISOR)

    return router
