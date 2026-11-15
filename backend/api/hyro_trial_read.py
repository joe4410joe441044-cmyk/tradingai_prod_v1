"""Authenticated operator API for a bounded Hyro Trading-OFF refresh."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.auth.dependencies import require_operator_session
from backend.prop_trading.hyro_trial_read_service import (
    HyroTrialReadError,
    HyroTrialReadService,
)


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == host
        and parsed.scheme == request.url.scheme
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
    )


def create_hyro_trial_read_router(
    service: HyroTrialReadService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/prop-accounts/hyro-trial", tags=["hyro-trial-read"])
    reader = service or HyroTrialReadService()

    @router.post("/refresh")
    def refresh(
        request: Request,
        _identity: str = Depends(require_operator_session),
    ) -> JSONResponse:
        if not _same_origin(request):
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": {"code": "ORIGIN_REJECTED"}},
            )
        try:
            challenge = reader.refresh()
        except HyroTrialReadError as error:
            return JSONResponse(
                status_code=error.status_code,
                content={"ok": False, "error": {"code": error.safe_code}},
            )
        return JSONResponse(status_code=200, content={"ok": True, "challenge": challenge})

    return router
