# -*- coding: utf-8 -*-
"""Read-only Market Recorder proxy routes.

Browser → TradingAI Backend → Recorder API.  Only GET, fixed paths, and
validated query parameters are supported.  Internal URLs and stack traces are
never exposed; every failure is normalized to a safe error code.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.models.recorder_proxy import RecorderProxyDTOError
from backend.services.http.recorder_http_client import RecorderUpstreamError
from backend.services.recorder_proxy.errors import (
    CONFIGURATION_ERROR,
    INTERNAL,
    PROXY_DISABLED,
    QUERY_INVALID,
    error_status_code,
    safe_error_payload,
)
from backend.services.recorder_proxy.service import (
    RecorderProxyConfigurationError,
    RecorderProxyDisabledError,
    RecorderProxyQueryError,
    RecorderProxyService,
)


def _control_dry_run(body):
    """Accept only an explicit boolean control mode.

    This prevents an empty or malformed browser request from silently
    becoming a live Recorder mutation.
    """
    if not isinstance(body, dict) or set(body) != {"dry_run"}:
        raise RecorderProxyQueryError()
    dry_run = body["dry_run"]
    if not isinstance(dry_run, bool):
        raise RecorderProxyQueryError()
    return dry_run


def _error_response(code):
    return JSONResponse(
        status_code=error_status_code(code),
        content=safe_error_payload(code),
    )


def create_recorder_proxy_router(service=None):
    """Create the read-only proxy router.

    ``service`` may be injected for tests; by default it is built from the
    process environment and fails closed when unconfigured.
    """
    if service is None:
        service = RecorderProxyService()

    router = APIRouter(
        prefix="/api/market-recorder",
        tags=["market-recorder"],
    )

    @router.get("/health")
    async def get_health(request: Request):
        try:
            result = await service.get_health(request.query_params)
        except RecorderProxyQueryError:
            return _error_response(QUERY_INVALID)
        except RecorderProxyDisabledError:
            return _error_response(PROXY_DISABLED)
        except RecorderProxyConfigurationError:
            return _error_response(CONFIGURATION_ERROR)
        except RecorderUpstreamError as error:
            return _error_response(error.code)
        except RecorderProxyDTOError:
            return _error_response("market_recorder_upstream_invalid_response")
        except Exception:
            return _error_response(INTERNAL)
        return JSONResponse(status_code=200, content=result)

    @router.get("/status")
    async def get_status(request: Request):
        try:
            result = await service.get_status(request.query_params)
        except RecorderProxyQueryError:
            return _error_response(QUERY_INVALID)
        except RecorderProxyDisabledError:
            return _error_response(PROXY_DISABLED)
        except RecorderProxyConfigurationError:
            return _error_response(CONFIGURATION_ERROR)
        except RecorderUpstreamError as error:
            return _error_response(error.code)
        except RecorderProxyDTOError:
            return _error_response("market_recorder_upstream_invalid_response")
        except Exception:
            return _error_response(INTERNAL)
        return JSONResponse(status_code=200, content=result)

    @router.get("/storage")
    async def get_storage(request: Request):
        try:
            result = await service.get_storage(request.query_params)
        except RecorderProxyQueryError:
            return _error_response(QUERY_INVALID)
        except RecorderProxyDisabledError:
            return _error_response(PROXY_DISABLED)
        except RecorderProxyConfigurationError:
            return _error_response(CONFIGURATION_ERROR)
        except RecorderUpstreamError as error:
            return _error_response(error.code)
        except RecorderProxyDTOError:
            return _error_response("market_recorder_upstream_invalid_response")
        except Exception:
            return _error_response(INTERNAL)
        return JSONResponse(status_code=200, content=result)

    @router.get("/archives")
    async def get_archives(request: Request):
        try:
            result = await service.get_archives(request.query_params)
        except RecorderProxyQueryError:
            return _error_response(QUERY_INVALID)
        except RecorderProxyDisabledError:
            return _error_response(PROXY_DISABLED)
        except RecorderProxyConfigurationError:
            return _error_response(CONFIGURATION_ERROR)
        except RecorderUpstreamError as error:
            return _error_response(error.code)
        except RecorderProxyDTOError:
            return _error_response("market_recorder_upstream_invalid_response")
        except Exception:
            return _error_response(INTERNAL)
        return JSONResponse(status_code=200, content=result)

    @router.post("/start")
    async def post_start(request: Request):
        try:
            body = await request.json()
            dry_run = _control_dry_run(body)
        except Exception:
            return _error_response(QUERY_INVALID)
        try:
            result = await service.start(dry_run=dry_run)
        except RecorderProxyQueryError:
            return _error_response(QUERY_INVALID)
        except RecorderProxyDisabledError:
            return _error_response(PROXY_DISABLED)
        except RecorderProxyConfigurationError:
            return _error_response(CONFIGURATION_ERROR)
        except RecorderUpstreamError as error:
            return _error_response(error.code)
        except RecorderProxyDTOError:
            return _error_response("market_recorder_upstream_invalid_response")
        except Exception:
            return _error_response(INTERNAL)
        return JSONResponse(status_code=200, content=result)

    @router.post("/stop")
    async def post_stop(request: Request):
        try:
            body = await request.json()
            dry_run = _control_dry_run(body)
        except Exception:
            return _error_response(QUERY_INVALID)
        try:
            result = await service.stop(dry_run=dry_run)
        except RecorderProxyQueryError:
            return _error_response(QUERY_INVALID)
        except RecorderProxyDisabledError:
            return _error_response(PROXY_DISABLED)
        except RecorderProxyConfigurationError:
            return _error_response(CONFIGURATION_ERROR)
        except RecorderUpstreamError as error:
            return _error_response(error.code)
        except RecorderProxyDTOError:
            return _error_response("market_recorder_upstream_invalid_response")
        except Exception:
            return _error_response(INTERNAL)
        return JSONResponse(status_code=200, content=result)

    return router
