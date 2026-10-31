"""Authenticated read-only Context router.

The router is not included by the Production application. It accepts only
explicit read-only projections and the existing operator-session dependency.
It does not create a BotManager, call an exchange, or send context to an
external model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import Response

from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.dependencies import require_operator_session
from backend.auth.operator_session import OperatorSessionManager
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.supervisor.contracts import ReadOnlySupervisorSnapshot

from .api_contract import (
    CONTEXT_BUILD_FAILED,
    CONTEXT_FAILURE_HTTP_STATUS,
    PAYLOAD_HTTP_STATUS,
    PAYLOAD_LIMIT_EXCEEDED,
    PRODUCTION_API_AVAILABLE,
    PRODUCTION_RUNTIME_CONNECTED,
    PUBLIC_ENDPOINT_ENABLED,
)
from .context_views import (
    DEFAULT_VIEW_MAX_BYTES,
    scrub_context_tree,
    view_to_json,
    view_to_markdown,
)
from .owner_context_bridge import (
    collection_from_owner_document,
    copied_owner_export,
    existing_owner_from_process,
)
from .runtime_collector import collect_runtime_context
from .schema import ProjectTruth, SourceTruth


@dataclass(frozen=True)
class ContextReadInputs:
    """Caller-supplied projections. None means the reader was not injected."""

    generated_at: datetime
    supervisor_snapshot: ReadOnlySupervisorSnapshot | None = None
    position_view: Mapping[str, Any] | None = None
    position_account: Mapping[str, Any] | None = None
    position_mode: str | None = None
    position_now: datetime | float | int | str | None = None
    position_symbol: str | None = None
    account_projection: Mapping[str, Any] | None = None
    mm_projection: Mapping[str, Any] | None = None
    trading_cycle_projection: Mapping[str, Any] | None = None
    execution_projection: Mapping[str, Any] | None = None
    bot_status: Mapping[str, Any] | None = None
    source_truth: SourceTruth | None = None
    project_truth: ProjectTruth | None = None
    max_bytes: int = DEFAULT_VIEW_MAX_BYTES
    owner_snapshot: Mapping[str, Any] | None = None


def context_read_inputs(request: Request) -> ContextReadInputs:
    """Read the already loaded owner, or return an empty pack stamp.

    ``generated_at`` is only the pack stamp. A missing owner stays missing.
    This function does not construct a manager.
    """

    generated_at = datetime.now(timezone.utc)
    lookup = getattr(request.app.state, "context_owner_lookup", None)
    if lookup is None:
        lookup = existing_owner_from_process
    try:
        owner = lookup()
    except Exception:
        owner = None
    if owner is None:
        return ContextReadInputs(generated_at=generated_at)
    return ContextReadInputs(
        generated_at=generated_at,
        owner_snapshot=copied_owner_export(owner),
    )


def _envelope(view: Mapping[str, Any]) -> dict[str, Any]:
    limited = view.get("reason") == PAYLOAD_LIMIT_EXCEEDED
    return {
        "status": PAYLOAD_LIMIT_EXCEEDED if limited else "OK",
        "view": "OPERATOR_CONTEXT",
        "productionRuntimeConnected": PRODUCTION_RUNTIME_CONNECTED,
        "productionApiAvailable": PRODUCTION_API_AVAILABLE,
        "publicEndpointEnabled": PUBLIC_ENDPOINT_ENABLED,
        "context": dict(view),
    }


def _failure_body() -> dict[str, Any]:
    return {
        "status": CONTEXT_BUILD_FAILED,
        "productionRuntimeConnected": PRODUCTION_RUNTIME_CONNECTED,
        "productionApiAvailable": PRODUCTION_API_AVAILABLE,
        "publicEndpointEnabled": PUBLIC_ENDPOINT_ENABLED,
    }


def build_operator_http_body(inputs: ContextReadInputs) -> tuple[int, dict[str, Any]]:
    """Collect injected projections and return the operator envelope.

    Exceptions become a fixed failure body. The exception text is discarded.
    """

    try:
        if inputs.owner_snapshot is not None:
            collected = collection_from_owner_document(
                inputs.owner_snapshot,
                inputs.generated_at,
            )
        else:
            collected = collect_runtime_context(
                generated_at=inputs.generated_at,
                supervisor_snapshot=inputs.supervisor_snapshot,
                position_view=inputs.position_view,
                position_account=inputs.position_account,
                position_mode=inputs.position_mode,
                position_now=inputs.position_now,
                position_symbol=inputs.position_symbol,
                account_projection=inputs.account_projection,
                mm_projection=inputs.mm_projection,
                trading_cycle_projection=inputs.trading_cycle_projection,
                execution_projection=inputs.execution_projection,
                bot_status=inputs.bot_status,
                source_truth=inputs.source_truth,
                project_truth=inputs.project_truth,
                max_bytes=inputs.max_bytes,
            )
    except Exception:
        return CONTEXT_FAILURE_HTTP_STATUS, _failure_body()
    body = scrub_context_tree(_envelope(collected.operator_view))
    if not isinstance(body, dict):
        return CONTEXT_FAILURE_HTTP_STATUS, _failure_body()
    status = PAYLOAD_HTTP_STATUS if body.get("status") == PAYLOAD_LIMIT_EXCEEDED else 200
    return status, body


def _json_response(status_code: int, body: Mapping[str, Any]) -> Response:
    return Response(
        content=view_to_json(body),
        status_code=status_code,
        media_type="application/json",
    )


def _markdown_response(status_code: int, body: Mapping[str, Any]) -> Response:
    return Response(
        content=view_to_markdown(body),
        status_code=status_code,
        media_type="text/markdown",
    )


context_router = APIRouter(
    prefix="/api/ai-context",
    dependencies=[Depends(require_operator_session)],
)


@context_router.get("/operator")
def read_operator_context(
    _operator_identity: str = Depends(require_operator_session),
    inputs: ContextReadInputs = Depends(context_read_inputs),
) -> Response:
    """Return the operator view after the existing session dependency runs."""

    del _operator_identity
    status, body = build_operator_http_body(inputs)
    return _json_response(status, body)


@context_router.get("/operator.md")
def read_operator_context_markdown(
    _operator_identity: str = Depends(require_operator_session),
    inputs: ContextReadInputs = Depends(context_read_inputs),
) -> Response:
    """Render the same operator envelope as Markdown."""

    del _operator_identity
    status, body = build_operator_http_body(inputs)
    return _markdown_response(status, body)


def create_isolated_context_app(
    *,
    session_manager: OperatorSessionManager | None = None,
    config: OperatorAuthConfig | None = None,
) -> FastAPI:
    """Mount the context router on a new app for tests.

    This function is not called by the Production application. When a session
    manager is supplied, the existing operator middleware validates the cookie.
    """

    app = FastAPI()
    app.include_router(context_router)
    if session_manager is not None:
        if config is None:
            raise ValueError("operator auth config is required with a session manager")
        app.add_middleware(
            OperatorSessionMiddleware,
            session_manager=session_manager,
            config=config,
        )
    return app
