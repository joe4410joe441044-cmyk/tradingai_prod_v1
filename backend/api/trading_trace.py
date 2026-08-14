from fastapi import APIRouter, HTTPException, Query

from backend.runtime.trading_trace import trace_store


router = APIRouter(prefix="/api/trading-trace", tags=["trading-trace"])


@router.get("/recent")
def recent_traces(limit: int = Query(50, ge=1, le=200)):
    traces = trace_store.recent(limit)
    return {"traces": traces, "count": len(traces)}


@router.get("/session")
def session_audit(mode: str | None = None, runtimeId: str | None = None):
    return trace_store.session(mode=mode, runtime_id=runtimeId)


@router.get("/{trace_id}")
def get_trace(trace_id: str):
    trace = trace_store.trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace
