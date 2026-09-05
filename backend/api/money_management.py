"""FastAPI router for the MM-5A3 safe HTTP boundary."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.auth.dependencies import require_operator_session

from backend.money_management.loss_http_api import (
    APPLICATION_STATE_ATTRIBUTE,
    MoneyManagementApiBoundaryException,
    MoneyManagementHttpBoundary,
)


router = APIRouter(
    prefix="/api/money-management",
    tags=["money-management"],
)


@router.get("/history")
def get_money_management_history(
    request: Request,
    limit: int = 100,
    before: str = None,
    after: str = None,
    eventType: str = None,
    state: str = None,
):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management history is unavailable.",
            True,
        )
    try:
        return boundary.get_history(
            limit=limit,
            before=before,
            after=after,
            event_type=eventType,
            state=state,
        ).to_dict()
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management history is unavailable.",
            True,
        )


def _safe_error(status_code, code, message, retryable=False):
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "retryable": retryable,
            "timestamp": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )


def _boundary(request):
    value = getattr(
        getattr(request.app, "state", None),
        APPLICATION_STATE_ATTRIBUTE,
        None,
    )
    return value if isinstance(value, MoneyManagementHttpBoundary) else None


def _boundary_error(error):
    return JSONResponse(
        status_code=error.error.status_code,
        content=error.error.to_dict(),
    )


@router.get("/status")
def get_money_management_status(request: Request):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management status is unavailable.",
            True,
        )
    try:
        return boundary.get_status().to_dict()
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management status is unavailable.",
            True,
        )


@router.get("/configuration")
def get_money_management_configuration(request: Request):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management configuration is unavailable.",
            True,
        )
    try:
        return boundary.get_configuration().to_dict()
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management configuration is unavailable.",
            True,
        )


@router.put("/configuration")
async def update_money_management_configuration(
    request: Request,
    _operator: str = Depends(require_operator_session),
):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management configuration is unavailable.",
            True,
        )
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
    try:
        return boundary.update_configuration(payload).to_dict()
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management configuration update failed.",
            True,
        )


@router.post("/recovery")
def recover_money_management(request: Request):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management recovery is unavailable.",
            True,
        )
    try:
        return boundary.recover().to_dict()
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management recovery failed.",
            True,
        )


@router.post("/recovery/accounting-rebase")
async def rebase_money_management_accounting(request: Request):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(503, "MONEY_MANAGEMENT_UNAVAILABLE", "Money Management accounting recovery is unavailable.", True)
    try:
        payload = await request.json()
    except Exception:
        return _safe_error(400, "ACCOUNTING_REBASE_INVALID", "Request body must contain valid JSON.")
    try:
        return boundary.rebase_accounting(payload)
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(503, "INTERNAL_STATE_UNAVAILABLE", "Money Management accounting rebase failed.", True)
@router.post("/position-size/preview")
async def preview_money_management_position_size(request: Request):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management position size preview is unavailable.",
            True,
        )
    try:
        payload = await request.json()
    except Exception:
        return _safe_error(
            400,
            "POSITION_SIZE_INPUT_INVALID",
            "Request body must contain valid JSON.",
        )
    try:
        return boundary.preview_position_size(payload)
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management position size preview failed.",
            True,
        )


@router.post("/simulation")
async def simulate_money_management(request: Request):
    boundary = _boundary(request)
    if boundary is None:
        return _safe_error(
            503,
            "MONEY_MANAGEMENT_UNAVAILABLE",
            "Money Management simulation is unavailable.",
            True,
        )
    try:
        payload = await request.json()
    except Exception:
        return _safe_error(
            400,
            "SIMULATION_INPUT_INVALID",
            "Request body must contain valid JSON.",
        )
    try:
        return boundary.simulate(payload)
    except MoneyManagementApiBoundaryException as error:
        return _boundary_error(error)
    except Exception:
        return _safe_error(
            503,
            "INTERNAL_STATE_UNAVAILABLE",
            "Money Management simulation failed.",
            True,
        )
