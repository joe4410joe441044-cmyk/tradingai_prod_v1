"""Build compact health telemetry from the authoritative runtime result.

This module only observes existing runtime state.  It deliberately does not
participate in strategy, governance, or execution decisions.
"""

from copy import deepcopy
from datetime import datetime, timezone


STAGE_NAMES = {
    "trading-runtime": "TradingRuntime",
    "runtime-adapter": "RuntimeAdapter",
    "runtime-state": "RuntimeState",
    "strategy-plugin": "Strategy Plugin",
    "ai-plugin": "AI Plugin",
    "governance-runtime": "Governance Runtime",
    "execution-runtime": "Execution Runtime",
    "execution-governance": "Execution Governance",
    "execution-signal-adapter": "Execution Signal Adapter",
    "execution-engine": "Execution Engine",
}


def _trace_reached(value):
    if value is True:
        return True
    return isinstance(value, dict) and value.get("ok") is not False


def _strategy_state(runtime_result):
    strategy_output = runtime_result.get("strategyOutput")
    if not isinstance(strategy_output, dict):
        return {}
    strategy = strategy_output.get("strategy")
    return deepcopy(strategy) if isinstance(strategy, dict) else {}


def _ai_state(runtime_result):
    if not runtime_result.get("aiRuntimeReached"):
        return {}
    return {
        "runtimeReached": True,
        "decision": runtime_result.get("aiDecision"),
        "direction": runtime_result.get("aiDirection"),
        "confidence": runtime_result.get("aiConfidence"),
        "score": runtime_result.get("aiScore"),
        "holdReason": runtime_result.get("aiHoldReason"),
        "output": deepcopy(runtime_result.get("aiOutput")),
    }


def _governance_state(runtime_result, governance_state):
    state = deepcopy(governance_state or {})
    state.update({
        "runtimeReached": bool(
            runtime_result.get("governanceRuntimeReached")
        ),
        "decision": runtime_result.get("governanceDecision"),
        "allowed": runtime_result.get("governanceAllowed"),
        "blockedReason": runtime_result.get("governanceBlockedReason"),
        "output": deepcopy(runtime_result.get("governanceOutput")),
    })
    return state


def _execution_state(runtime_result):
    runtime = runtime_result.get("runtime")
    state = deepcopy(runtime) if isinstance(runtime, dict) else {}
    state.update({
        "runtimeReached": bool(
            runtime_result.get("executionRuntimeReached")
        ),
        "governanceReached": bool(
            runtime_result.get("executionGovernanceReached")
        ),
        "signalAdapterReached": bool(
            runtime_result.get("signalAdapterReached")
        ),
        "normalizedDirection": runtime_result.get("normalizedDirection"),
        "adapterOutput": deepcopy(runtime_result.get("adapterOutput")),
        "handoffAttempted": bool(runtime_result.get("handoffAttempted")),
        "handoffExecuted": bool(runtime_result.get("handoffExecuted")),
        "handoffBlockedReason": runtime_result.get("handoffBlockedReason"),
    })
    return state


def _stage(status, reached=False, reason=None):
    return {
        "status": status,
        "reached": bool(reached),
        "reason": reason,
    }


def _timeline(runtime_result, running):
    if not running:
        return []

    trace = runtime_result.get("runtimeStageTrace")
    if not isinstance(trace, dict):
        return []

    events = []
    for stage_id, event in trace.items():
        if not isinstance(event, dict) or not event.get("reached"):
            continue
        timestamp = event.get("timestamp")
        if isinstance(timestamp, (int, float)):
            time_value = datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            ).isoformat()
        else:
            time_value = timestamp
        events.append({
            "timestamp": time_value,
            "timestampEpoch": timestamp,
            "stageId": stage_id,
            "source": STAGE_NAMES.get(stage_id, stage_id),
            "state": event.get("status", "OK"),
            "reason": event.get("reason"),
        })

    return sorted(
        events,
        key=lambda event: event.get("timestampEpoch") or 0,
    )


def build_runtime_health_snapshot(
    *,
    running,
    market_stale,
    ws_connected,
    engine_available,
    runtime_healthy,
    runtime_result,
    runtime_trace,
    runtime_metrics,
    governance_state,
    snapshot_timestamp,
):
    """Return UI-ready facts sourced only from backend runtime state."""

    result = runtime_result if isinstance(runtime_result, dict) else {}
    trace = runtime_trace if isinstance(runtime_trace, dict) else {}
    metrics = runtime_metrics if isinstance(runtime_metrics, dict) else {}
    active = bool(running)

    market_reached = active and not market_stale and (
        _trace_reached(trace.get("ws_receive"))
        or metrics.get("last_ws_message") is not None
    )
    orderbook_reached = active and bool(ws_connected) and (
        _trace_reached(trace.get("callback_fire"))
        or metrics.get("last_callback") is not None
    )
    bot_update_reached = active and _trace_reached(trace.get("bot_update"))
    adapter_reached = active and bool(result.get("runtimeAdapterReached"))
    runtime_state_reached = active and bool(result.get("runtimeStateReached"))
    strategy_reached = active and bool(result.get("strategyRuntimeReached"))
    ai_reached = active and bool(result.get("aiRuntimeReached"))
    governance_reached = active and bool(
        result.get("governanceRuntimeReached")
    )
    execution_reached = active and bool(
        result.get("executionRuntimeReached")
    )
    execution_governance_reached = active and bool(
        result.get("executionGovernanceReached")
    )
    signal_adapter_reached = active and bool(
        result.get("signalAdapterReached")
    )
    handoff_attempted = active and bool(result.get("handoffAttempted"))
    handoff_executed = active and bool(result.get("handoffExecuted"))

    execution_runtime = result.get("runtime")
    execution_runtime = (
        execution_runtime if isinstance(execution_runtime, dict) else {}
    )
    decision_reason = (
        execution_runtime.get("reason")
        or result.get("governanceBlockedReason")
        or result.get("handoffBlockedReason")
    )
    execution_enabled = bool(
        (governance_state or {}).get("execution_enabled")
    )
    execution_allowed = bool(execution_runtime.get("executionAllowed"))

    stages = {
        "start-request": _stage("OK" if active else "WAIT", active),
        "trading-runtime": _stage(
            "ACTIVE" if active and result else "WAIT",
            active and bool(result),
        ),
        "market-data": _stage("OK" if market_reached else "WAIT", market_reached),
        "order-book": _stage(
            "OK" if orderbook_reached else "WAIT",
            orderbook_reached,
        ),
        "runtime-adapter": _stage(
            "OK" if adapter_reached else "WAIT",
            adapter_reached,
        ),
        "runtime-state": _stage(
            "OK" if runtime_state_reached else "WAIT",
            runtime_state_reached,
        ),
        "strategy-plugin": _stage(
            "OK" if strategy_reached else "WAIT",
            strategy_reached,
        ),
        "ai-plugin": _stage("OK" if ai_reached else "WAIT", ai_reached),
        "governance-runtime": _stage(
            "OK" if governance_reached else "WAIT",
            governance_reached,
            result.get("governanceBlockedReason"),
        ),
        "execution-runtime": _stage(
            "OK" if execution_reached else "WAIT",
            execution_reached,
            decision_reason,
        ),
        "execution-governance": _stage(
            "OK" if execution_governance_reached else (
                "IDLE" if execution_reached else "WAIT"
            ),
            execution_governance_reached,
            decision_reason,
        ),
        "execution-signal-adapter": _stage(
            "OK" if signal_adapter_reached else (
                "IDLE" if execution_reached else "WAIT"
            ),
            signal_adapter_reached,
            decision_reason,
        ),
        "execution-engine": _stage(
            "OK" if handoff_executed else (
                "BLOCKED" if handoff_attempted else (
                    "IDLE" if engine_available and execution_reached else "WAIT"
                )
            ),
            handoff_attempted,
            result.get("handoffBlockedReason") or decision_reason,
        ),
        "exchange-client": _stage(
            "OK" if active and engine_available else "WAIT",
            active and engine_available,
        ),
        "exchange-api": _stage(
            "OK" if active and _trace_reached(trace.get("status_api")) else "WAIT",
            active and _trace_reached(trace.get("status_api")),
        ),
        "complete": _stage(
            "OK" if execution_reached else "WAIT",
            execution_reached,
            decision_reason,
        ),
    }

    loops = {
        "runtime-loop": "RUNNING" if active else "WAIT",
        "market-feed": "RUNNING" if market_reached else "WAIT",
        "orderbook-ws": "RUNNING" if orderbook_reached else "WAIT",
        "strategy-loop": "RUNNING" if strategy_reached else "WAIT",
        "ai-loop": "RUNNING" if ai_reached else "WAIT",
        "governance-loop": "RUNNING" if governance_reached else "WAIT",
        "execution-queue": "RUNNING" if execution_reached else "WAIT",
        "exchange-sync": "OK" if active and engine_available else "WAIT",
        "portfolio-sync": "OK" if active and engine_available else "WAIT",
    }

    pipeline_status = (
        "WAIT" if not active else ("OK" if execution_reached else "ACTIVE")
    )
    health = (
        "CRITICAL" if not runtime_healthy else (
            "DEGRADED" if active and market_stale else "HEALTHY"
        )
    )

    return {
        "snapshotTimestamp": snapshot_timestamp,
        "cycleTimestamp": metrics.get("last_bot_update"),
        "runtimeHealthy": bool(runtime_healthy),
        "health": health,
        "pipelineStatus": pipeline_status,
        "engineAvailable": bool(engine_available),
        "executionEnabled": execution_enabled,
        "executionAllowed": execution_allowed,
        "executionReason": decision_reason,
        "stages": stages,
        "loops": loops,
        "timeline": _timeline(result, active),
        "states": {
            "strategy": _strategy_state(result),
            "ai": _ai_state(result),
            "governance": _governance_state(result, governance_state),
            "execution": _execution_state(result),
        },
    }
