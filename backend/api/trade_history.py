"""FastAPI router for the operator-facing Trade History API.

The router is a thin, read-only projection over the canonical completed-trade
store (the same Stage 13 store that backs Parameter Performance).  It never
writes, never promotes and never changes any trading authority.  Both endpoints
are unauthenticated GET reads, following the existing Parameter Performance
convention.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.runtime.trade_history_read import TradeHistoryService

router = APIRouter(
    prefix="/api/trade-history",
    tags=["trade-history"],
)

_APPLICATION_STATE_ATTRIBUTE = "trade_history_service"


def _service(request: Request) -> TradeHistoryService:
    state = getattr(getattr(request, "app", None), "state", None)
    service = getattr(state, _APPLICATION_STATE_ATTRIBUTE, None)
    if isinstance(service, TradeHistoryService):
        return service
    service = TradeHistoryService()
    if state is not None:
        try:
            setattr(state, _APPLICATION_STATE_ATTRIBUTE, service)
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


@router.get("")
def get_trade_history(
    request: Request,
    period: str = "all",
    scope: str | None = None,
    mode: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
    result: str | None = None,
    revision: int | None = None,
    exitReason: str | None = None,
    controlSource: str | None = None,
    fromTimestamp: float | None = None,
    toTimestamp: float | None = None,
    sort: str | None = None,
    direction: str | None = None,
    page: int = 1,
    pageSize: int = 50,
):
    """Read-only completed-trade history with filters, sort and pagination."""

    service = _service(request)
    try:
        return JSONResponse(
            status_code=200,
            content=service.history(
                period=period,
                scope=scope,
                mode=mode,
                symbol=symbol,
                side=side,
                result=result,
                revision=revision,
                exit_reason=exitReason,
                control_source=controlSource,
                from_timestamp=fromTimestamp,
                to_timestamp=toTimestamp,
                sort=sort or "exitTimestamp",
                direction=direction or "desc",
                page=page,
                page_size=pageSize,
            ),
        )
    except ValueError as error:
        return _safe_error(
            422,
            "INVALID_TRADE_HISTORY_QUERY",
            str(error) or "Invalid trade history query.",
        )
    except Exception:
        return _safe_error(
            503,
            "TRADE_HISTORY_UNAVAILABLE",
            "Trade history is unavailable.",
        )


@router.get("/detail")
def get_trade_history_detail(request: Request, recordId: str | None = None):
    """Read-only detail for a single canonical completed trade."""

    if not isinstance(recordId, str) or not recordId.strip():
        return _safe_error(
            422,
            "INVALID_TRADE_HISTORY_QUERY",
            "recordId is required.",
        )
    service = _service(request)
    try:
        detail = service.detail(recordId)
    except Exception:
        return _safe_error(
            503,
            "TRADE_HISTORY_UNAVAILABLE",
            "Trade history is unavailable.",
        )
    if detail is None:
        return _safe_error(
            404,
            "TRADE_HISTORY_NOT_FOUND",
            "Completed trade was not found.",
            recordId=recordId,
        )
    return JSONResponse(status_code=200, content=detail)
