"""HTTP control boundary for the Supervisor monitoring control plane.

Mutating/active capabilities are default OFF and every route is fail-closed:

- ``POST /monitoring/run-once`` requires an authenticated operator session
  (reusing ``require_operator_session``), the API feature flag, the server-side
  capability mapping, the CSRF middleware allowlist, the rate limiter, bounded
  request validation and the fenced Trigger Coordinator.  It is disabled in the
  default composition.
- ``GET /monitoring/alerts`` and ``GET /monitoring/alerts/{alert_id}`` are
  bounded read-only projections over the alert outbox.
- ``GET /monitoring/control`` is a bounded read-only control-plane status.

No route acknowledges, resolves, delivers or executes anything through a GET.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import JSONResponse

from backend.auth.dependencies import require_operator_session
from backend.supervisor.monitoring_alert_models import MAX_ALERT_PAGE
from backend.supervisor.supervisor_control_plane import SupervisorControlPlane

MONITORING_DISABLED = "SUPERVISOR_MONITORING_TRIGGER_DISABLED"
MONITORING_CONTROL_UNAVAILABLE = "SUPERVISOR_MONITORING_CONTROL_UNAVAILABLE"
ALERTS_UNAVAILABLE = "SUPERVISOR_MONITORING_ALERTS_UNAVAILABLE"
ALERT_NOT_FOUND = "SUPERVISOR_MONITORING_ALERT_NOT_FOUND"


def _json_response(payload: dict, status_code: int = 200) -> Response:
    return Response(
        content=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        media_type="application/json",
        status_code=status_code,
    )


def _unavailable(code: str, message: str) -> Response:
    return _json_response(
        {
            "code": code,
            "message": message,
            "retryable": True,
            "productionActivationAllowed": False,
        },
        status_code=503,
    )


def create_supervisor_monitoring_control_router(
    *,
    control_plane: SupervisorControlPlane | None = None,
    trigger_service=None,
    alert_service=None,
) -> APIRouter:
    """Create the (default-OFF) control router.  Construction performs no I/O."""

    router = APIRouter()

    def _trigger():
        if trigger_service is not None:
            return trigger_service
        if control_plane is not None:
            return control_plane.trigger_service
        return None

    def _alerts():
        if alert_service is not None:
            return alert_service
        if control_plane is not None:
            return control_plane.alert_service
        return None

    @router.get("/monitoring/control", response_class=Response)
    def monitoring_control() -> Response:
        if control_plane is None:
            return _unavailable(MONITORING_CONTROL_UNAVAILABLE, "Control plane is unavailable.")
        try:
            status = control_plane.status()
            return Response(content=status.stable_json(), media_type="application/json")
        except Exception:  # noqa: BLE001 - bounded, sanitized failure
            return _unavailable(MONITORING_CONTROL_UNAVAILABLE, "Control plane is unavailable.")

    @router.get("/monitoring/alerts", response_class=Response)
    def monitoring_alerts(
        limit: int = 20, cursor: str | None = None, status: str | None = None
    ) -> Response:
        service = _alerts()
        if service is None or not service.available:
            return _unavailable(ALERTS_UNAVAILABLE, "Alert outbox is unavailable.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_ALERT_PAGE:
            return _json_response({"code": "SUPERVISOR_MONITORING_ALERT_REQUEST_INVALID"}, 400)
        if status is not None and status not in ("OPEN", "ACKNOWLEDGED", "RESOLVED"):
            return _json_response({"code": "SUPERVISOR_MONITORING_ALERT_REQUEST_INVALID"}, 400)
        try:
            page = service.list(limit=limit, cursor=cursor, status=status)
            return Response(content=page.stable_json(), media_type="application/json")
        except Exception:  # noqa: BLE001
            return _unavailable(ALERTS_UNAVAILABLE, "Alert outbox is unavailable.")

    @router.get("/monitoring/alerts/{alert_id}", response_class=Response)
    def monitoring_alert(alert_id: str) -> Response:
        service = _alerts()
        if service is None or not service.available:
            return _unavailable(ALERTS_UNAVAILABLE, "Alert outbox is unavailable.")
        record = service.get(alert_id)
        if record is None:
            return _json_response({"code": ALERT_NOT_FOUND}, 404)
        return Response(content=record.stable_json(), media_type="application/json")

    @router.post("/monitoring/run-once", response_class=Response)
    def monitoring_run_once(
        request: Request,
        body: dict = Body(default_factory=dict),
        _operator: str = Depends(require_operator_session),
    ) -> Response:
        del request
        service = _trigger()
        if service is None:
            return _json_response(
                {
                    "code": MONITORING_DISABLED,
                    "message": "Supervisor monitoring trigger is disabled.",
                    "retryable": False,
                    "productionActivationAllowed": False,
                },
                status_code=503,
            )
        try:
            result = service.handle(principal_id=_operator, body=body)
        except Exception:  # noqa: BLE001 - never expose raw exception text
            return _json_response(
                {"code": "SUPERVISOR_MONITORING_INTERNAL_FAILURE"}, status_code=500
            )
        payload = result.model_dump(mode="json")
        return JSONResponse(status_code=result.http_status, content=payload)

    return router


__all__ = [
    "ALERT_NOT_FOUND",
    "ALERTS_UNAVAILABLE",
    "MONITORING_CONTROL_UNAVAILABLE",
    "MONITORING_DISABLED",
    "create_supervisor_monitoring_control_router",
]
