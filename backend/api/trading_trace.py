"""Read-only HTTP surface over the restart-safe trading trace reader.

Every endpoint is GET-only and delegates to
:class:`~backend.runtime.trading_trace_reader.TradingTraceReader`, which reads
the durable JSONL trace from disk.  The trace writer, the fifteen-stage
recording, the bot/execution path and every runtime authority are untouched.

The pre-existing ``/recent``, ``/session`` and ``/{trace_id}`` endpoints keep
their response shapes for backward compatibility; they are now backed by the
disk reader, so records remain queryable after a process restart.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.runtime.trading_trace_reader import (
    TraceCursorError,
    TradingTraceReader,
    default_trading_trace_reader,
)


router = APIRouter(prefix="/api/trading-trace", tags=["trading-trace"])

trace_reader: TradingTraceReader = default_trading_trace_reader()


def _cursor_error(exc: TraceCursorError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"code": exc.code, "message": exc.message, "stale": True},
    )


@router.get("/recent")
def recent_traces(limit: int = Query(50, ge=1, le=200)):
    traces = trace_reader.recent(limit)
    return {"traces": traces, "count": len(traces)}


@router.get("/session")
def session_audit(mode: str | None = None, runtimeId: str | None = None):
    return trace_reader.session(mode=mode, runtime_id=runtimeId)


@router.get("/events")
def query_trace_events(
    fromTimestamp: str | None = Query(None, alias="from"),
    toTimestamp: str | None = Query(None, alias="to"),
    cycleId: str | None = None,
    tradeId: str | None = None,
    correlationId: str | None = None,
    mode: str | None = None,
    stage: str | None = None,
    reasonCode: str | None = None,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    direction: str = Query("forward"),
    maxScanBytes: int | None = Query(None, ge=1024),
    maxScanLines: int | None = Query(None, ge=1),
    timeoutSeconds: float | None = Query(None, ge=0.0, le=30.0),
):
    """Bounded, cursor-paginated, restart-safe trace event query."""

    try:
        return trace_reader.query_events(
            time_from=fromTimestamp,
            time_to=toTimestamp,
            cycle_id=cycleId,
            trade_id=tradeId,
            correlation_id=correlationId,
            mode=mode,
            stage=stage,
            reason_code=reasonCode,
            status=status,
            symbol=symbol,
            limit=limit,
            cursor=cursor,
            direction=direction,
            max_scan_bytes=maxScanBytes,
            max_scan_lines=maxScanLines,
            timeout_seconds=timeoutSeconds,
        )
    except TraceCursorError as exc:
        return _cursor_error(exc)


@router.get("/{trace_id}")
def get_trace(trace_id: str):
    trace = trace_reader.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace
