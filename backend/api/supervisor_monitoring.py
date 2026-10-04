"""Read-only HTTP boundary for Supervisor monitoring health/state.

Only bounded GET routes are exposed.  No run, trigger, acknowledgement,
resolution or other mutating route exists here, and serving a GET never executes
a monitoring run or writes anything.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Response

from backend.supervisor.monitoring_read_service import (
    CROSS_PROCESS_SAFETY,
    MonitoringReadService,
)

MONITORING_UNAVAILABLE = "SUPERVISOR_MONITORING_UNAVAILABLE"


def _error_response() -> Response:
    body = {
        "code": MONITORING_UNAVAILABLE,
        "message": "Supervisor monitoring read model is unavailable.",
        "retryable": True,
        "crossProcessSafety": CROSS_PROCESS_SAFETY,
        "productionActivationAllowed": False,
    }
    return Response(
        content=json.dumps(body, sort_keys=True, separators=(",", ":")),
        media_type="application/json",
        status_code=503,
    )


def _read_response(service: MonitoringReadService) -> Response:
    try:
        model = service.read()
        return Response(content=model.stable_json(), media_type="application/json")
    except Exception:
        return _error_response()


def create_supervisor_monitoring_router(
    service: MonitoringReadService | None = None,
) -> APIRouter:
    """Create a GET-only router for the bounded monitoring read model."""

    read_service = service if service is not None else MonitoringReadService()
    router = APIRouter()

    @router.get("/monitoring/health", response_class=Response)
    def monitoring_health() -> Response:
        return _read_response(read_service)

    @router.get("/monitoring/state", response_class=Response)
    def monitoring_state() -> Response:
        return _read_response(read_service)

    return router
