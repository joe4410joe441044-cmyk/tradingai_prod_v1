"""Read-only HTTP boundary for the Supervisor snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Request, Response

from backend.supervisor.failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from backend.supervisor.knowledge_history_consumer import (
    SupervisorKnowledgeHistoryConsumer,
)
from backend.supervisor.runtime_snapshot_adapter import RuntimeSnapshotAdapter
from backend.api.supervisor_conversation import create_supervisor_conversation_router
from backend.api.supervisor_history import create_supervisor_history_router
from backend.api.supervisor_monitoring import create_supervisor_monitoring_router
from backend.api.supervisor_monitoring_control import (
    create_supervisor_monitoring_control_router,
)
from backend.supervisor.monitoring_read_service import MonitoringReadService
from backend.supervisor.supervisor_control_plane import get_control_plane
from backend.supervisor.audit_store import SupervisorAuditStore
from backend.supervisor.conversation_service import SupervisorConversationService
from backend.supervisor.ollama_provider import OllamaLocalProvider
from backend.supervisor.openai_provider import OpenAIStructuredProvider
from backend.supervisor.provider_configuration import (
    SupervisorProviderMode,
    load_supervisor_provider_configuration,
)
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


def _snapshot_body(snapshot, knowledge_history_consumer) -> str:
    """Serialize a snapshot, adding optional metadata only when available."""

    body = snapshot.stable_json()
    if knowledge_history_consumer is None:
        return body
    try:
        metadata = knowledge_history_consumer.metadata_for_snapshot(snapshot)
    except Exception:
        return body
    if metadata is None:
        return body
    payload = json.loads(body)
    payload["knowledgeHistory"] = metadata
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def create_supervisor_router(
    adapter: RuntimeSnapshotAdapter | None = None,
    provider_configuration: object | None = None,
    knowledge_history_consumer: SupervisorKnowledgeHistoryConsumer | None = None,
    monitoring_read_service: MonitoringReadService | None = None,
    control_plane=None,
) -> APIRouter:
    """Create a router holding observation capability only, never commands."""
    snapshot_adapter = adapter or RuntimeSnapshotAdapter()
    if control_plane is None:
        control_plane = get_control_plane()
    router = APIRouter(prefix="/api/supervisor", tags=["supervisor"])

    @router.get("/snapshot", response_class=Response)
    def get_supervisor_snapshot(request: Request) -> Response:
        try:
            snapshot = snapshot_adapter.build(request.app)
            return Response(
                content=_snapshot_body(snapshot, knowledge_history_consumer),
                media_type="application/json",
            )
        except SupervisorBoundaryError as exc:
            return _failure_response(exc.code)
        except Exception:
            return _failure_response(SupervisorFailureCode.FAIL_CLOSED)

    # Read-only monitoring health/state routes (GET only; default unavailable).
    if monitoring_read_service is None:
        monitoring_read_service = MonitoringReadService(control_plane=control_plane)
    router.include_router(create_supervisor_monitoring_router(monitoring_read_service))
    # Default-OFF control plane: trigger POST + bounded alert/control reads.
    router.include_router(
        create_supervisor_monitoring_control_router(control_plane=control_plane)
    )

    audit_store = SupervisorAuditStore()
    if provider_configuration is None:
        provider_configuration = load_supervisor_provider_configuration()
    if provider_configuration.mode is SupervisorProviderMode.OPENAI:
        local_provider = OpenAIStructuredProvider(provider_configuration)
    elif provider_configuration.mode is SupervisorProviderMode.OLLAMA_LOCAL:
        local_provider = OllamaLocalProvider(provider_configuration)
    else:
        local_provider = None
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
                    "provider": provider_configuration.mode.value,
                    "model": provider_configuration.model,
                    "availability": "UNAVAILABLE",
                    "localhostOnly": provider_configuration.mode is SupervisorProviderMode.OLLAMA_LOCAL,
                    "mode": "SHADOW", "lastCheckedAt": None, "lastSuccessAt": None,
                    "lastFailureCode": "SUPERVISOR_PROVIDER_UNAVAILABLE",
                    "operationalEffect": "NONE",
                }, sort_keys=True, separators=(",", ":")),
                media_type="application/json", status_code=503,
            )

    return router


router = create_supervisor_router(
    knowledge_history_consumer=SupervisorKnowledgeHistoryConsumer()
)
