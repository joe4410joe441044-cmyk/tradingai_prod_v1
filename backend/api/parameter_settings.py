"""FastAPI router for the operator-facing PARAMETER SETTINGS API (E-PARAM-4).

The router stays thin: all canonical validation, revision-conflict checking and
persistence happen in
:class:`backend.strategy.parameters.settings_service.ParameterSettingsService`,
which reuses the existing canonical parameter authority.

Read endpoints follow the existing Money Management configuration/status API
convention (unauthenticated GET).  The single write endpoint requires the
existing authenticated operator session.  The router never touches order,
leverage, quantity, symbol, mode or bot lifecycle authority.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.auth.dependencies import require_operator_session
from backend.runtime.parameter_performance_read import (
    ParameterPerformanceReadService,
)
from backend.strategy.parameters.settings_service import (
    ParameterSettingsService,
    UpdateOutcome,
)

router = APIRouter(
    prefix="/api/parameter-settings",
    tags=["parameter-settings"],
)

_APPLICATION_STATE_ATTRIBUTE = "parameter_settings_service"
_PERFORMANCE_STATE_ATTRIBUTE = "parameter_performance_read_service"

_OUTCOME_STATUS = {
    UpdateOutcome.ACCEPTED: 200,
    UpdateOutcome.INVALID_SCOPE: 422,
    UpdateOutcome.INVALID_BODY: 422,
    UpdateOutcome.VALIDATION_ERROR: 422,
    UpdateOutcome.REVISION_CONFLICT: 409,
    UpdateOutcome.LIVE_CONFIRMATION_REQUIRED: 422,
    UpdateOutcome.LIVE_PARAMETER_NOT_WRITABLE: 422,
    UpdateOutcome.STORE_FAILURE: 503,
}


def _attempt_stopped_promotion(scope) -> dict:
    """Trigger the canonical safe promotion when the bot is STOPPED.

    Promotion logic stays in the canonical parameter authority; this helper
    only supplies the runtime lifecycle signal.  When no bot manager exists
    (e.g. an isolated settings API test) no promotion is attempted, so a bare
    configuration write keeps its PENDING semantics.
    """

    try:
        from backend.bot_manager.bot_manager import get_existing_bot_manager
    except Exception:
        return {}
    try:
        manager = get_existing_bot_manager()
    except Exception:
        return {}
    if manager is None:
        return {}
    try:
        running = bool(getattr(manager, "_running", False))
        lifecycle = str(getattr(manager, "lifecycle_state", "STOPPED"))
        if running and lifecycle != "STOPPED":
            return {}
        result = manager.promote_parameter_revision_if_safe(bot_stopped=True)
    except Exception:
        return {}
    return result if isinstance(result, dict) else {}


def _service(request: Request) -> ParameterSettingsService:
    state = getattr(getattr(request, "app", None), "state", None)
    service = getattr(state, _APPLICATION_STATE_ATTRIBUTE, None)
    if isinstance(service, ParameterSettingsService):
        return service
    service = ParameterSettingsService()
    if state is not None:
        try:
            setattr(state, _APPLICATION_STATE_ATTRIBUTE, service)
        except Exception:
            pass
    return service


def _performance_service(request: Request) -> ParameterPerformanceReadService:
    state = getattr(getattr(request, "app", None), "state", None)
    service = getattr(state, _PERFORMANCE_STATE_ATTRIBUTE, None)
    if isinstance(service, ParameterPerformanceReadService):
        return service
    service = ParameterPerformanceReadService()
    if state is not None:
        try:
            setattr(state, _PERFORMANCE_STATE_ATTRIBUTE, service)
        except Exception:
            pass
    return service


def _safe_error(status_code: int, code: str, message: str, **extra) -> JSONResponse:
    content = {
        "code": code,
        "message": message,
        "retryable": False,
        "timestamp": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    content.update(extra)
    return JSONResponse(status_code=status_code, content=content)


def _scope_required(scope) -> JSONResponse:
    return _safe_error(
        422,
        "INVALID_SCOPE",
        "scope must be PAPER or LIVE",
        scope=scope,
    )


def _scoped_read(request: Request, scope, reader) -> JSONResponse:
    service = _service(request)
    if not isinstance(scope, str) or scope.strip().upper() not in (
        "PAPER",
        "LIVE",
    ):
        return _scope_required(scope)
    try:
        return JSONResponse(
            status_code=200,
            content=reader(service, scope.strip().upper()),
        )
    except ValueError:
        return _scope_required(scope)
    except Exception:
        return _safe_error(
            503,
            "PARAMETER_SETTINGS_UNAVAILABLE",
            "Parameter settings authority is unavailable.",
        )


@router.get("/schema")
def get_parameter_settings_schema(request: Request):
    try:
        return JSONResponse(status_code=200, content=_service(request).schema())
    except Exception:
        return _safe_error(
            503,
            "PARAMETER_SETTINGS_UNAVAILABLE",
            "Parameter settings schema is unavailable.",
        )


@router.get("/configuration")
def get_parameter_settings_configuration(request: Request, scope: str):
    return _scoped_read(
        request,
        scope,
        lambda service, value: service.configuration(value),
    )


@router.get("/effective")
def get_parameter_settings_effective(request: Request, scope: str):
    return _scoped_read(
        request,
        scope,
        lambda service, value: service.effective(value),
    )


@router.get("/runtime")
def get_parameter_settings_runtime(request: Request, scope: str):
    return _scoped_read(
        request,
        scope,
        lambda service, value: service.runtime(value),
    )


@router.get("/status")
def get_parameter_settings_status(request: Request):
    try:
        return JSONResponse(status_code=200, content=_service(request).status())
    except Exception:
        return _safe_error(
            503,
            "PARAMETER_SETTINGS_UNAVAILABLE",
            "Parameter settings status is unavailable.",
        )


@router.get("/performance")
def get_parameter_settings_performance(
    request: Request,
    scope: str | None = None,
    revision: int | None = None,
    symbol: str | None = None,
    mode: str | None = None,
    limit: int = 200,
):
    """Read-only Parameter Performance history (observed trades per revision).

    This endpoint is observational.  It never writes parameter configuration and
    never changes trading authority.
    """

    if scope is not None and (
        not isinstance(scope, str)
        or scope.strip().upper() not in ("PAPER", "LIVE")
    ):
        return _scope_required(scope)
    service = _performance_service(request)
    try:
        return JSONResponse(
            status_code=200,
            content=service.performance(
                scope=scope,
                revision=revision,
                symbol=symbol,
                mode=mode,
                limit=limit,
            ),
        )
    except Exception:
        return _safe_error(
            503,
            "PARAMETER_PERFORMANCE_UNAVAILABLE",
            "Parameter performance history is unavailable.",
        )


@router.get("/performance/compare")
def get_parameter_settings_performance_compare(
    request: Request,
    scope: str,
    revisionA: int,
    revisionB: int,
):
    """Read-only comparison of two observed parameter revisions (same scope)."""

    if not isinstance(scope, str) or scope.strip().upper() not in (
        "PAPER",
        "LIVE",
    ):
        return _scope_required(scope)
    service = _performance_service(request)
    try:
        return JSONResponse(
            status_code=200,
            content=service.compare(
                scope=scope,
                revision_a=revisionA,
                revision_b=revisionB,
            ),
        )
    except Exception:
        return _safe_error(
            503,
            "PARAMETER_PERFORMANCE_UNAVAILABLE",
            "Parameter performance comparison is unavailable.",
        )


@router.put("/configuration")
async def update_parameter_settings_configuration(
    request: Request,
    _operator: str = Depends(require_operator_session),
):
    service = _service(request)
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("application/json"):
        return _safe_error(
            415,
            "CONFIGURATION_INVALID",
            "Content-Type must be application/json.",
        )
    try:
        payload = await request.json()
    except Exception:
        return _safe_error(
            400,
            "CONFIGURATION_INVALID",
            "Request body must contain valid JSON.",
        )
    if not isinstance(payload, dict):
        return _safe_error(
            400,
            "CONFIGURATION_INVALID",
            "Request body must be a JSON object.",
        )

    result = service.update_configuration(
        scope=payload.get("scope"),
        parameters=payload.get("parameters"),
        expected_revision=payload.get("expectedRevision"),
        confirm_live=payload.get("confirmLive") is True,
    )
    content = result.payload
    if result.outcome is UpdateOutcome.ACCEPTED:
        promotion = _attempt_stopped_promotion(payload.get("scope"))
        if promotion.get("promoted") is True:
            # The bot is STOPPED, so the safe promotion boundary was reached
            # without starting the bot.  Refresh the read models so the
            # response never claims a stale effective revision.
            scope = payload.get("scope")
            content = {
                **content,
                "status": "ACTIVE",
                "effectiveRevision": promotion.get("effectiveRevision"),
                "promotion": promotion,
                "configuration": service.configuration(scope),
                "effective": service.effective(scope),
            }
    status_code = _OUTCOME_STATUS.get(result.outcome, 500)
    return JSONResponse(status_code=status_code, content=content)
