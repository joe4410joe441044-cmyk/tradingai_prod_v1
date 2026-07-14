"""Normalize backend runtime telemetry for the Runtime Health Monitor.

This module is observation-only.  It must never participate in strategy,
governance, or execution decisions.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json


STAGE_DEFINITIONS = {
    "start-request": {
        "name": "START REQUEST",
        "backendFile": "backend/api/bot_api.py",
        "functionName": "start_bot",
        "relatedFiles": ["backend/bot_manager/bot_manager.py"],
    },
    "trading-runtime": {
        "name": "TradingRuntime",
        "backendFile": "backend/main.py",
        "functionName": "TradingRuntime.process_runtime",
        "relatedFiles": ["backend/runtime/runtime_registry.py"],
    },
    "market-data": {
        "name": "MarketData",
        "backendFile": "backend/bot_manager/bot_manager.py",
        "functionName": "BotManager.on_update",
        "relatedFiles": ["backend/market/exchanges"],
    },
    "order-book": {
        "name": "OrderBook",
        "backendFile": "backend/core/orderbook_manager.py",
        "functionName": "OrderBookManager.update",
        "relatedFiles": ["backend/market/exchanges"],
    },
    "runtime-adapter": {
        "name": "RuntimeAdapter",
        "backendFile": "backend/ai/runtime_adapter.py",
        "functionName": "RuntimeAdapter.build",
        "relatedFiles": ["backend/ai/runtime_state.py"],
    },
    "runtime-state": {
        "name": "RuntimeState",
        "backendFile": "backend/ai/runtime_state.py",
        "functionName": "RuntimeState",
        "relatedFiles": ["backend/ai/runtime_adapter.py"],
    },
    "strategy-plugin": {
        "name": "Strategy Plugin",
        "backendFile": "backend/strategy/MicrostructureEdgeStrategy.py",
        "functionName": "process_microstructure_strategy",
        "relatedFiles": ["backend/bot_manager/runtime_state.py"],
    },
    "ai-plugin": {
        "name": "AI Plugin",
        "backendFile": "backend/ai/ai_pipeline.py",
        "functionName": "AIPipeline.decide",
        "relatedFiles": [
            "backend/ai/feature_engine.py",
            "backend/ai/trade_brain.py",
        ],
    },
    "governance-runtime": {
        "name": "Governance Runtime",
        "backendFile": "backend/runtime/governance_runtime.py",
        "functionName": "GovernanceRuntime.process_governance",
        "relatedFiles": ["backend/api/governance.py"],
    },
    "execution-runtime": {
        "name": "Execution Runtime",
        "backendFile": "backend/runtime/ExecutionRuntime.py",
        "functionName": "process_execution_runtime",
        "relatedFiles": ["backend/bot_manager/runtime_state.py"],
    },
    "execution-governance": {
        "name": "Execution Governance",
        "backendFile": "backend/execution/ExecutionGovernance.py",
        "functionName": "process_execution_governance",
        "relatedFiles": ["backend/runtime/ExecutionRuntime.py"],
    },
    "execution-signal-adapter": {
        "name": "Execution Signal Adapter",
        "backendFile": "backend/runtime/adapters/execution_signal_adapter.py",
        "functionName": "ExecutionSignalAdapter.adapt",
        "relatedFiles": ["backend/runtime/ExecutionRuntime.py"],
    },
    "execution-engine": {
        "name": "Execution Engine",
        "backendFile": "Bot/engine/execution_engine.py",
        "functionName": "ExecutionEngine.submit_signal",
        "relatedFiles": ["backend/runtime/ExecutionRuntime.py"],
    },
    "exchange-client": {
        "name": "Exchange Client",
        "backendFile": "backend/execution/kucoin_trade.py",
        "functionName": None,
        "relatedFiles": ["backend/bot_manager/bot_manager.py"],
    },
    "exchange-api": {
        "name": "Exchange API",
        "backendFile": "backend/api/bot_api.py",
        "functionName": "get_status",
        "relatedFiles": ["backend/api/websocket.py"],
    },
    "complete": {
        "name": "COMPLETE",
        "backendFile": "backend/main.py",
        "functionName": "TradingRuntime.process_runtime",
        "relatedFiles": ["backend/runtime/ExecutionRuntime.py"],
    },
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
        "runtimeReached": bool(runtime_result.get("governanceRuntimeReached")),
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
        "runtimeReached": bool(runtime_result.get("executionRuntimeReached")),
        "governanceReached": bool(runtime_result.get("executionGovernanceReached")),
        "signalAdapterReached": bool(runtime_result.get("signalAdapterReached")),
        "normalizedDirection": runtime_result.get("normalizedDirection"),
        "adapterOutput": deepcopy(runtime_result.get("adapterOutput")),
        "handoffAttempted": bool(runtime_result.get("handoffAttempted")),
        "handoffExecuted": bool(runtime_result.get("handoffExecuted")),
        "handoffBlockedReason": runtime_result.get("handoffBlockedReason"),
    })
    return state


def _is_hold(runtime_result):
    return str(runtime_result.get("aiDecision") or "").upper() == "HOLD"


def _stage(
    stage_id,
    status,
    reached=False,
    reason=None,
    input_value=None,
    output_value=None,
    duration_ms=None,
):
    return {
        **deepcopy(STAGE_DEFINITIONS[stage_id]),
        "id": stage_id,
        "status": status,
        "reached": bool(reached),
        "reason": reason,
        "durationMs": duration_ms,
        "input": deepcopy(input_value),
        "output": deepcopy(output_value),
        "exception": reason if status == "ERROR" else None,
    }


def _timeline(runtime_result, stages, running, emergency_events=None):
    """Return only events actually recorded by the backend runtime trace."""

    events = []

    if running:
        trace = runtime_result.get("runtimeStageTrace")
        if isinstance(trace, dict):
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
                stage = stages.get(stage_id, {})
                events.append({
                    "timestamp": time_value,
                    "timestampEpoch": timestamp,
                    "stageId": stage_id,
                    "source": stage.get("name", stage_id),
                    "state": stage.get("status", event.get("status", "OK")),
                    "reason": stage.get("reason") or event.get("reason"),
                })

    if isinstance(emergency_events, list):
        for event in emergency_events:
            if isinstance(event, dict):
                events.append(deepcopy(event))

    return sorted(
        events,
        key=lambda event: event.get("timestampEpoch") or 0,
    )[-120:]


def _fingerprint(payload):
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()[:16]


def build_runtime_health_snapshot(
    *,
    running,
    market_stale,
    exchange_ws_connected,
    browser_ws_connected,
    browser_ws_clients,
    engine_available,
    runtime_healthy,
    runtime_result,
    runtime_trace,
    runtime_metrics,
    governance_state,
    snapshot_timestamp,
    lifecycle_revision=0,
    lifecycle_state=None,
    cycle_id=None,
    generated_at=None,
):
    """Return UI-ready facts sourced only from backend runtime state."""

    completed_result = (
        runtime_result if isinstance(runtime_result, dict) else {}
    )
    trace = runtime_trace if isinstance(runtime_trace, dict) else {}
    metrics = runtime_metrics if isinstance(runtime_metrics, dict) else {}
    active = bool(running)
    execution_available = active and bool(engine_available)
    # A completed cycle remains useful as history, but it must not be exposed
    # as the current decision after the bot lifecycle has stopped.
    result = completed_result if active else {}

    market_reached = active and not market_stale and (
        _trace_reached(trace.get("ws_receive"))
        or metrics.get("last_ws_message") is not None
    )
    orderbook_reached = active and bool(exchange_ws_connected) and (
        _trace_reached(trace.get("callback_fire"))
        or metrics.get("last_callback") is not None
    )
    adapter_reached = active and bool(result.get("runtimeAdapterReached"))
    runtime_state_reached = active and bool(result.get("runtimeStateReached"))
    strategy_reached = active and bool(result.get("strategyRuntimeReached"))
    ai_reached = active and bool(result.get("aiRuntimeReached"))
    governance_reached = active and bool(result.get("governanceRuntimeReached"))
    execution_reached = active and bool(result.get("executionRuntimeReached"))
    execution_governance_reached = active and bool(
        result.get("executionGovernanceReached")
    )
    signal_adapter_reached = active and bool(result.get("signalAdapterReached"))
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
    hold_cycle = _is_hold(result) or str(decision_reason or "").upper() == "AI_HOLD"
    trading_reason = "AI_HOLD" if hold_cycle else decision_reason
    ai_reason = result.get("aiHoldReason") if hold_cycle else None
    strategy = _strategy_state(result)
    strategy_reason = (
        strategy.get("suppressionReason")
        if strategy_reached and strategy.get("executionAllowed") is False
        else None
    )
    execution_enabled = bool((governance_state or {}).get("execution_enabled"))
    execution_allowed = bool(execution_runtime.get("executionAllowed"))

    strategy_status = "OK" if strategy_reached else "WAIT"
    if strategy_reached and strategy_reason:
        strategy_status = "IDLE"
    ai_status = "IDLE" if ai_reached and hold_cycle else (
        "OK" if ai_reached else "WAIT"
    )
    governance_status = (
        "IDLE" if governance_reached and not result.get("governanceAllowed")
        else ("OK" if governance_reached else "WAIT")
    )
    execution_status = (
        "IDLE" if execution_reached and not execution_allowed
        else ("OK" if execution_reached else "WAIT")
    )

    stage_inputs = {
        "ai-plugin": result.get("aiInput"),
        "governance-runtime": result.get("governanceInput"),
        "execution-runtime": {
            "strategyState": result.get("governanceInput", {}).get("strategy_state")
            if isinstance(result.get("governanceInput"), dict) else None,
            "governanceDecision": result.get("governanceOutput"),
        },
    }
    stage_outputs = {
        "start-request": {"status": "RUNNING" if active else "STOPPED"},
        "trading-runtime": {"runtimeHealthy": bool(runtime_healthy)},
        "market-data": {
            "marketReady": market_reached,
            "marketStale": bool(market_stale),
        },
        "order-book": {
            "exchangeWebSocketConnected": bool(exchange_ws_connected),
            "messageCount": metrics.get("message_count"),
        },
        "runtime-adapter": result.get("aiInput"),
        "runtime-state": (
            result.get("aiInput", {}).get("runtime_state")
            if isinstance(result.get("aiInput"), dict) else None
        ),
        "strategy-plugin": result.get("strategyOutput"),
        "ai-plugin": result.get("aiOutput"),
        "governance-runtime": result.get("governanceOutput"),
        "execution-runtime": execution_runtime,
        "execution-governance": _execution_state(result),
        "execution-signal-adapter": result.get("adapterOutput"),
        "execution-engine": {
            "available": execution_available,
            "handoffAttempted": handoff_attempted,
            "handoffExecuted": handoff_executed,
        },
        "exchange-client": {"available": execution_available},
        "exchange-api": {"status": "AVAILABLE" if active else "IDLE"},
        "complete": {
            "executionAllowed": execution_allowed,
            "tradingAction": "IDLE_BY_AI_HOLD" if hold_cycle else (
                "ORDER_SUBMITTED" if handoff_executed else "IDLE"
            ),
        },
    }

    stages = {
        "start-request": _stage(
            "start-request", "OK" if active else "STOPPED", active,
            output_value=stage_outputs["start-request"],
        ),
        "trading-runtime": _stage(
            "trading-runtime", "ACTIVE" if active and result else "WAIT",
            active and bool(result), output_value=stage_outputs["trading-runtime"],
        ),
        "market-data": _stage(
            "market-data", "OK" if market_reached else "ERROR",
            market_reached, "MARKET_DATA_MISSING_OR_STALE" if active and not market_reached else None,
            output_value=stage_outputs["market-data"],
        ),
        "order-book": _stage(
            "order-book", "OK" if orderbook_reached else "ERROR",
            orderbook_reached, "ORDERBOOK_MISSING_OR_STALE" if active and not orderbook_reached else None,
            output_value=stage_outputs["order-book"],
        ),
        "runtime-adapter": _stage(
            "runtime-adapter", "OK" if adapter_reached else "WAIT",
            adapter_reached, output_value=stage_outputs["runtime-adapter"],
        ),
        "runtime-state": _stage(
            "runtime-state", "OK" if runtime_state_reached else "WAIT",
            runtime_state_reached, output_value=stage_outputs["runtime-state"],
        ),
        "strategy-plugin": _stage(
            "strategy-plugin", strategy_status, strategy_reached,
            strategy_reason, output_value=stage_outputs["strategy-plugin"],
        ),
        "ai-plugin": _stage(
            "ai-plugin", ai_status, ai_reached,
            (f"AI_HOLD: {ai_reason}" if ai_reason else "AI_HOLD")
            if hold_cycle else None,
            input_value=stage_inputs["ai-plugin"],
            output_value=stage_outputs["ai-plugin"],
        ),
        "governance-runtime": _stage(
            "governance-runtime", governance_status, governance_reached,
            trading_reason, input_value=stage_inputs["governance-runtime"],
            output_value=stage_outputs["governance-runtime"],
        ),
        "execution-runtime": _stage(
            "execution-runtime", execution_status, execution_reached,
            trading_reason, input_value=stage_inputs["execution-runtime"],
            output_value=stage_outputs["execution-runtime"],
        ),
        "execution-governance": _stage(
            "execution-governance",
            "OK" if execution_governance_reached else (
                "IDLE" if execution_reached else "WAIT"
            ), execution_governance_reached, trading_reason,
            output_value=stage_outputs["execution-governance"],
        ),
        "execution-signal-adapter": _stage(
            "execution-signal-adapter",
            "OK" if signal_adapter_reached else (
                "IDLE" if execution_reached else "WAIT"
            ), signal_adapter_reached, trading_reason,
            output_value=stage_outputs["execution-signal-adapter"],
        ),
        "execution-engine": _stage(
            "execution-engine",
            "OK" if handoff_executed else (
                "ERROR" if not engine_available and active else (
                    "BLOCKED" if handoff_attempted else (
                        "IDLE" if engine_available and execution_reached else "WAIT"
                    )
                )
            ), handoff_attempted,
            result.get("handoffBlockedReason") or trading_reason,
            output_value=stage_outputs["execution-engine"],
        ),
        "exchange-client": _stage(
            "exchange-client", "OK" if active and engine_available else "ERROR",
            active and engine_available,
            "ENGINE_UNAVAILABLE" if active and not engine_available else None,
            output_value=stage_outputs["exchange-client"],
        ),
        "exchange-api": _stage(
            "exchange-api", "OK" if active else "STOPPED", active,
            output_value=stage_outputs["exchange-api"],
        ),
        "complete": _stage(
            "complete", "OK" if execution_reached else "WAIT",
            execution_reached, trading_reason,
            output_value=stage_outputs["complete"],
        ),
    }

    loops = {
        "runtime-loop": "REACHED" if active and result else "IDLE",
        "market-feed": "REACHED" if market_reached else "IDLE",
        "orderbook-ws": "REACHED" if orderbook_reached else "IDLE",
        "strategy-loop": "REACHED" if strategy_reached else "IDLE",
        "ai-loop": "EVALUATED" if ai_reached else "IDLE",
        "governance-loop": "EVALUATED" if governance_reached else "IDLE",
        "execution-queue": "REACHED" if execution_reached else "IDLE",
        "exchange-sync": "REACHED" if active and engine_available else "IDLE",
        "portfolio-sync": "REACHED" if active and engine_available else "IDLE",
    }

    if not active:
        for stage_id, stage in stages.items():
            if stage_id in {"start-request", "trading-runtime"}:
                stage["status"] = "STOPPED"
            else:
                stage["status"] = "SUSPENDED_BY_BOT_STOP"
            stage["reached"] = False
            stage["reason"] = "BOT_STOPPED"
            stage["exception"] = None
        loops = {
            key: "SUSPENDED_BY_BOT_STOP"
            for key in loops
        }

    issues = []
    if active and not browser_ws_connected:
        issues.append("BROWSER_WS_DISCONNECTED")
    if active and not exchange_ws_connected:
        issues.append("EXCHANGE_WS_DISCONNECTED")
    if active and not market_reached:
        issues.append("MARKET_DATA_MISSING_OR_STALE")
    if active and not orderbook_reached:
        issues.append("ORDERBOOK_MISSING_OR_STALE")
    if active and not result:
        issues.append("RUNTIME_SNAPSHOT_MISSING")
    if active and not runtime_healthy:
        issues.append("RUNTIME_EXCEPTION")
    if active and not engine_available:
        issues.append("ENGINE_UNAVAILABLE")

    if not active:
        severity = "HEALTHY"
        blocking_reason = None
    elif issues:
        severity = "CRITICAL"
        blocking_reason = issues[0]
    else:
        severity = "HEALTHY"
        blocking_reason = None

    pipeline_status = "SUSPENDED_BY_BOT_STOP" if not active else (
        "OK" if execution_reached else "ACTIVE"
    )
    if not active:
        execution_engine_status = "UNAVAILABLE_BY_BOT_STOP"
    elif not execution_available:
        execution_engine_status = "UNAVAILABLE"
    elif not execution_enabled:
        execution_engine_status = "DISABLED_BY_OPERATOR"
    elif execution_allowed:
        execution_engine_status = "READY"
    elif hold_cycle:
        execution_engine_status = "ENABLED_IDLE_BY_AI_HOLD"
    else:
        execution_engine_status = "ENABLED_IDLE_BLOCKED"

    if not active:
        trading_action_status = "NONE_BY_BOT_STOP"
    elif hold_cycle:
        trading_action_status = "IDLE_BY_AI_HOLD"
    elif handoff_executed:
        trading_action_status = "ORDER_SUBMITTED"
    elif execution_allowed:
        trading_action_status = "READY"
    else:
        trading_action_status = "IDLE"

    current_reason = "BOT_STOPPED" if not active else trading_reason
    current_decision = "N/A" if not active else result.get("aiDecision")
    resolved_lifecycle_state = lifecycle_state or (
        "RUNNING" if active else "STOPPED"
    )

    normalized = {
        "bot": {"status": "RUNNING" if active else "STOPPED", "running": active},
        "executionAuthority": {
            "status": (
                "ENABLED" if execution_enabled else "DISABLED_BY_OPERATOR"
            ),
            "enabled": execution_enabled,
        },
        "browserWebSocket": {
            "status": "LIVE" if browser_ws_connected else "DISCONNECTED",
            "connected": bool(browser_ws_connected),
            "clientCount": int(browser_ws_clients or 0),
        },
        "exchangeWebSocket": {
            "status": "LIVE" if exchange_ws_connected else (
                "DISCONNECTED_BY_BOT_STOP" if not active else "DISCONNECTED"
            ),
            "connected": bool(exchange_ws_connected),
        },
        "runtimeEngine": {
            "status": "ACTIVE" if active and runtime_healthy else (
                "ERROR" if active else "STOPPED"
            ),
            "healthy": bool(runtime_healthy),
        },
        "runtimeLoop": {
            "status": "RUNNING" if active else "STOPPED",
            "running": active,
        },
        "marketFeed": {
            "status": "LIVE" if market_reached else (
                "SUSPENDED_BY_BOT_STOP" if not active else "MISSING_OR_STALE"
            ),
            "healthy": market_reached,
            "stale": bool(market_stale),
        },
        "orderBook": {
            "status": "LIVE" if orderbook_reached else (
                "SUSPENDED_BY_BOT_STOP" if not active else "MISSING_OR_STALE"
            ),
            "healthy": orderbook_reached,
        },
        "strategy": {
            "reached": strategy_reached,
            "status": strategy_status if active else "SUSPENDED_BY_BOT_STOP",
            "reason": strategy_reason if active else "BOT_STOPPED",
        },
        "ai": {
            "reached": ai_reached,
            "status": ai_status if active else "SUSPENDED_BY_BOT_STOP",
            "reason": "AI_HOLD" if hold_cycle else current_reason,
            "detail": ai_reason if active else None,
            "decision": current_decision,
        },
        "governance": {
            "reached": governance_reached,
            "status": governance_status if active else "SUSPENDED_BY_BOT_STOP",
            "reason": result.get("governanceBlockedReason") if active else "BOT_STOPPED",
            "allowed": result.get("governanceAllowed") if active else False,
        },
        "executionQueue": {
            "reached": execution_reached,
            "status": "REACHED" if execution_reached else (
                "SUSPENDED_BY_BOT_STOP" if not active else "IDLE"
            ),
            "reason": current_reason,
        },
        "signalAdapter": {
            "reached": signal_adapter_reached,
            "status": "SUSPENDED_BY_BOT_STOP" if not active else (
                "READY" if signal_adapter_reached else (
                    "IDLE" if execution_reached else "WAIT"
                )
            ),
            "reason": current_reason,
        },
        "executionEngine": {
            "available": execution_available,
            "enabled": execution_enabled,
            "allowed": execution_allowed,
            "status": execution_engine_status,
            "reason": current_reason,
        },
        "tradingAction": {
            "status": trading_action_status,
            "reason": current_reason,
            "decision": current_decision,
        },
        "pipeline": {"status": pipeline_status},
        "severity": severity,
        "blockingReason": blocking_reason,
        "issues": issues,
        "lifecycle": {
            "state": resolved_lifecycle_state,
            "revision": int(lifecycle_revision or 0),
        },
    }
    status_fingerprint = _fingerprint({
        key: normalized[key]
        for key in (
            "bot",
            "lifecycle",
            "executionAuthority",
            "browserWebSocket",
            "exchangeWebSocket",
            "runtimeEngine",
            "runtimeLoop",
            "marketFeed",
            "orderBook",
            "strategy",
            "ai",
            "governance",
            "executionEngine",
            "tradingAction",
            "pipeline",
            "severity",
            "blockingReason",
            "issues",
        )
    })

    return {
        "schemaVersion": 2,
        "source": "BotManager.get_result",
        "snapshotId": str(metrics.get("last_bot_update") or snapshot_timestamp),
        "snapshotTimestamp": snapshot_timestamp,
        "generatedAt": generated_at or datetime.now(timezone.utc).isoformat(),
        "cycleId": cycle_id,
        "lifecycleRevision": int(lifecycle_revision or 0),
        "cycleTimestamp": metrics.get("last_bot_update"),
        "statusFingerprint": status_fingerprint,
        **normalized,
        # Compatibility aliases for consumers migrating to schemaVersion 2.
        "runtimeHealthy": bool(runtime_healthy),
        "health": severity,
        "pipelineStatus": pipeline_status,
        "engineAvailable": execution_available,
        "executionEnabled": execution_enabled,
        "executionAllowed": execution_allowed,
        "executionReason": current_reason,
        "stages": stages,
        "loops": loops,
        "timeline": _timeline(
            result,
            stages,
            active,
            (governance_state or {}).get("emergency_timeline"),
        ),
        "states": {
            "strategy": strategy,
            "ai": _ai_state(result),
            "governance": _governance_state(result, governance_state),
            "execution": _execution_state(result),
        },
        "lastCompletedDecision": (
            {
                "decision": completed_result.get("aiDecision"),
                "reason": (
                    completed_result.get("aiHoldReason")
                    or completed_result.get("governanceBlockedReason")
                    or completed_result.get("handoffBlockedReason")
                ),
            }
            if not active and completed_result
            else None
        ),
        "activeStageId": "trading-runtime" if active else "start-request",
        "latencyMs": metrics.get("latency_ms"),
    }
