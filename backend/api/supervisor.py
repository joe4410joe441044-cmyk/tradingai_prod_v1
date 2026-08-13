"""Read-only HTTP boundary for the Supervisor snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Request, Response

from backend.supervisor.failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from backend.supervisor.runtime_snapshot_adapter import RuntimeSnapshotAdapter
from backend.api.supervisor_conversation import create_supervisor_conversation_router
from backend.api.supervisor_history import create_supervisor_history_router
from backend.supervisor.audit_store import SupervisorAuditStore
from backend.supervisor.conversation_service import SupervisorConversationService
from backend.supervisor.ollama_provider import OllamaLocalProvider
from backend.supervisor.provider_configuration import load_supervisor_provider_configuration
from backend.supervisor.provider_status import build_provider_status


def _failure_response(code: SupervisorFailureCode) -> Response:
    body = {
        "code": code.value,
        "message": "Supervisor snapshot is unavailable.",
        "retryable": True,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return Response(
        content=json.dumps(body, sort_keys=True, separators=(",", ":")),
        media_type="application/json",
        status_code=503,
    )


def create_supervisor_router(
    adapter: RuntimeSnapshotAdapter | None = None,
) -> APIRouter:
    """Create a router holding observation capability only, never commands."""
    snapshot_adapter = adapter or RuntimeSnapshotAdapter()
    router = APIRouter(prefix="/api/supervisor", tags=["supervisor"])

    @router.get("/snapshot", response_class=Response)
    def get_supervisor_snapshot(request: Request) -> Response:
        try:
            snapshot = snapshot_adapter.build(request.app)
            return Response(content=snapshot.stable_json(), media_type="application/json")
        except SupervisorBoundaryError as exc:
            return _failure_response(exc.code)
        except Exception:
            return _failure_response(SupervisorFailureCode.FAIL_CLOSED)

    audit_store = SupervisorAuditStore()
    provider_configuration = load_supervisor_provider_configuration()
    local_provider = (
        OllamaLocalProvider(provider_configuration)
        if provider_configuration.mode.value == "OLLAMA_LOCAL"
        else None
    )
    router.include_router(create_supervisor_conversation_router(SupervisorConversationService(
        snapshot_adapter=snapshot_adapter, audit_store=audit_store, provider=local_provider,
    )))
    router.include_router(create_supervisor_history_router(audit_store))

    @router.get("/provider/status", response_class=Response)
    def get_provider_status() -> Response:
        try:
            provider_detail = local_provider.status() if local_provider is not None else {
                "provider": "DISABLED", "model": provider_configuration.model,
                "availability": "UNAVAILABLE", "localhostOnly": True,
                "mode": "SHADOW", "lastCheckedAt": None, "lastSuccessAt": None,
                "lastFailureCode": "SUPERVISOR_PROVIDER_UNAVAILABLE",
                "operationalEffect": "NONE",
            }
            status = build_provider_status(
                provider_configuration, local_provider, provider_detail=provider_detail
            )
            return Response(
                content=json.dumps(status, sort_keys=True, separators=(",", ":")),
                media_type="application/json",
            )
        except Exception:
            return Response(
                content=json.dumps({
                    "provider": "OLLAMA_LOCAL", "model": "qwen3:4b-instruct",
                    "availability": "UNAVAILABLE", "localhostOnly": True,
                    "mode": "SHADOW", "lastCheckedAt": None, "lastSuccessAt": None,
                    "lastFailureCode": "SUPERVISOR_OLLAMA_UNAVAILABLE",
                    "operationalEffect": "NONE",
                }, sort_keys=True, separators=(",", ":")),
                media_type="application/json", status_code=503,
            )

    return router


router = create_supervisor_router()
