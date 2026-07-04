const EMPTY_TEXT_VALUES = new Set([
    "",
    "--",
    "UNKNOWN",
    "NO DATA",
    "NONE",
    "NULL",
    "UNDEFINED",
]);

const STAGE_DEFINITIONS = [
    {
        id: "start-request",
        name: "START REQUEST",
        backendFile: "backend/api/bot_api.py",
        functionName: "start_bot",
        relatedFiles: ["backend/bot_manager/bot_manager.py"],
    },
    {
        id: "trading-runtime",
        name: "TradingRuntime",
        backendFile: "backend/main.py",
        functionName: "TradingRuntime.process_runtime",
        relatedFiles: ["backend/runtime/runtime_registry.py"],
    },
    {
        id: "market-data",
        name: "MarketData",
        backendFile: "backend/bot_manager/bot_manager.py",
        functionName: "BotManager.on_update",
        relatedFiles: ["frontend/src/runtime/websocketRuntime.js"],
    },
    {
        id: "order-book",
        name: "OrderBook",
        backendFile: "backend/bot_manager/bot_manager.py",
        functionName: "OrderBookManager.update",
        relatedFiles: ["backend/market/exchanges"],
    },
    {
        id: "runtime-adapter",
        name: "RuntimeAdapter",
        backendFile: "backend/ai/runtime_adapter.py",
        functionName: "RuntimeAdapter.build",
        relatedFiles: ["backend/ai/runtime_state.py"],
    },
    {
        id: "runtime-state",
        name: "RuntimeState",
        backendFile: "backend/ai/runtime_state.py",
        functionName: "RuntimeState",
        relatedFiles: ["backend/ai/runtime_adapter.py"],
    },
    {
        id: "strategy-plugin",
        name: "Strategy Plugin",
        backendFile: "backend/strategy/MicrostructureEdgeStrategy.py",
        functionName: "process_microstructure_strategy",
        relatedFiles: ["backend/bot_manager/runtime_state.py"],
    },
    {
        id: "ai-plugin",
        name: "AI Plugin",
        backendFile: "backend/ai/ai_pipeline.py",
        functionName: "AIPipeline.decide",
        relatedFiles: ["backend/ai/feature_engine.py", "backend/ai/trade_brain.py"],
    },
    {
        id: "governance-runtime",
        name: "Governance Runtime",
        backendFile: "backend/runtime/governance_runtime.py",
        functionName: "GovernanceRuntime.process_governance",
        relatedFiles: ["backend/api/governance.py"],
    },
    {
        id: "execution-runtime",
        name: "Execution Runtime",
        backendFile: "backend/runtime/ExecutionRuntime.py",
        functionName: "process_execution_runtime",
        relatedFiles: ["backend/bot_manager/runtime_state.py"],
    },
    {
        id: "execution-governance",
        name: "Execution Governance",
        backendFile: "backend/execution/ExecutionGovernance.py",
        functionName: "process_execution_governance",
        relatedFiles: ["backend/runtime/ExecutionRuntime.py"],
    },
    {
        id: "execution-signal-adapter",
        name: "Execution Signal Adapter",
        backendFile: "backend/runtime/adapters/execution_signal_adapter.py",
        functionName: "ExecutionSignalAdapter.adapt",
        relatedFiles: ["backend/websocket/ws_manager.py"],
    },
    {
        id: "execution-engine",
        name: "Execution Engine",
        backendFile: "Bot/engine/execution_engine.py",
        functionName: "ExecutionEngine.submit_signal",
        relatedFiles: ["backend/runtime/ExecutionRuntime.py"],
    },
    {
        id: "exchange-client",
        name: "Exchange Client",
        backendFile: "backend/execution/kucoin_trade.py",
        functionName: "--",
        relatedFiles: ["backend/bot_manager/bot_manager.py"],
    },
    {
        id: "exchange-api",
        name: "Exchange API",
        backendFile: "backend/api/bot_api.py",
        functionName: "get_status",
        relatedFiles: ["backend/api/websocket.py"],
    },
    {
        id: "complete",
        name: "COMPLETE",
        backendFile: "backend/main.py",
        functionName: "TradingRuntime.process_runtime",
        relatedFiles: ["backend/runtime/ExecutionRuntime.py"],
    },
];

const TRACE_KEYS = {
    "market-data": "ws_receive",
    "order-book": "callback_fire",
    "runtime-adapter": "bot_update",
    "exchange-api": "status_api",
};

const isFiniteNumber = (value) => (
    typeof value === "number" && Number.isFinite(value)
);

export const hasRuntimeValue = (value) => {
    if (value === null || value === undefined) {
        return false;
    }

    if (typeof value === "number") {
        return Number.isFinite(value);
    }

    if (typeof value === "string") {
        return !EMPTY_TEXT_VALUES.has(value.trim().toUpperCase());
    }

    if (Array.isArray(value)) {
        return value.length > 0;
    }

    if (typeof value === "object") {
        return Object.keys(value).length > 0;
    }

    return value === true;
};

const traceReached = (traceValue) => (
    traceValue === true
    || (
        traceValue
        && typeof traceValue === "object"
        && traceValue.ok !== false
    )
);

const receivedState = (state) => (
    hasRuntimeValue(state)
    && (
        !Object.prototype.hasOwnProperty.call(state, "lastUpdate")
        || hasRuntimeValue(state.lastUpdate)
    )
);

const displayValue = (value) => {
    if (value === null || value === undefined) {
        return "--";
    }

    if (typeof value === "number" && !Number.isFinite(value)) {
        return "--";
    }

    if (typeof value === "string") {
        return hasRuntimeValue(value) ? value : "--";
    }

    if (typeof value === "boolean" || typeof value === "number") {
        return String(value);
    }

    if (!hasRuntimeValue(value)) {
        return "--";
    }

    try {
        const serialized = JSON.stringify(value, (key, item) => {
            if (item === null || item === undefined) {
                return "--";
            }

            if (typeof item === "number" && !Number.isFinite(item)) {
                return "--";
            }

            if (
                typeof item === "string"
                && EMPTY_TEXT_VALUES.has(item.trim().toUpperCase())
            ) {
                return "--";
            }

            return item;
        }, 2);

        return serialized === "{}" || serialized === "[]"
            ? "--"
            : serialized;
    } catch {
        return "--";
    }
};

const durationValue = (value) => (
    isFiniteNumber(value)
        ? `${value.toFixed(2)} ms`
        : "--"
);

const deriveAuthoritativeRuntimeHealth = (snapshot) => {
    const health = snapshot.runtime_health;
    const metrics = snapshot.runtime_metrics || {};
    const states = health.states || {};
    const backendStages = health.stages || {};

    const outputByStage = {
        "start-request": {
            status: snapshot.status,
            symbol: snapshot.symbol,
        },
        "trading-runtime": {
            authoritativeRuntimeState: snapshot.authoritativeRuntimeState,
            runtimeSynchronizationState: snapshot.runtimeSynchronizationState,
        },
        "market-data": {
            price: snapshot.price,
            marketReady: snapshot.marketReady,
            marketStale: snapshot.marketStale,
        },
        "order-book": {
            wsConnected: snapshot.ws_connected,
            messageCount: metrics.message_count,
        },
        "runtime-adapter": snapshot.latestRuntimeResult?.aiInput,
        "runtime-state": snapshot.latestRuntimeResult?.aiInput?.runtime_state,
        "strategy-plugin": states.strategy,
        "ai-plugin": states.ai,
        "governance-runtime": states.governance,
        "execution-runtime": states.execution,
        "execution-governance": states.execution,
        "execution-signal-adapter": states.execution?.adapterOutput,
        "execution-engine": {
            engineAvailable: health.engineAvailable,
            handoffAttempted: states.execution?.handoffAttempted,
            handoffExecuted: states.execution?.handoffExecuted,
            blockedReason: states.execution?.handoffBlockedReason,
        },
        "exchange-client": {
            exchange: snapshot.exchange,
            executionMode: snapshot.execution_mode,
        },
        "exchange-api": {
            status: snapshot.status,
            timestamp: snapshot.timestamp,
        },
        complete: {
            executionAllowed: health.executionAllowed,
            reason: health.executionReason,
        },
    };

    const stages = STAGE_DEFINITIONS.map((definition) => {
        const backendStage = backendStages[definition.id] || {};
        const status = backendStage.status || "WAIT";

        return {
            ...definition,
            status,
            duration: backendStage.reached
                ? durationValue(metrics.latency_ms)
                : "--",
            input: displayValue(
                definition.id === "strategy-plugin"
                    ? snapshot.latestRuntimeResult?.governanceInput?.strategy_state
                    : undefined,
            ),
            output: displayValue(outputByStage[definition.id]),
            exception: status === "ERROR"
                ? displayValue(backendStage.reason)
                : "None",
            reason: displayValue(backendStage.reason),
            relatedFiles: definition.relatedFiles.join("\n") || "--",
        };
    });

    const loopNames = {
        "runtime-loop": "Runtime Loop",
        "market-feed": "Market Feed",
        "orderbook-ws": "OrderBook WS",
        "strategy-loop": "Strategy Loop",
        "ai-loop": "AI Loop",
        "governance-loop": "Governance Loop",
        "execution-queue": "Execution Queue",
        "exchange-sync": "Exchange Sync",
        "portfolio-sync": "Portfolio Sync",
    };
    const loops = Object.entries(health.loops || {}).map(([id, status]) => ({
        id,
        name: loopNames[id] || id,
        status,
    }));

    return {
        running: String(snapshot.status || "").toUpperCase() === "RUNNING",
        stages,
        loops,
        timeline: Array.isArray(health.timeline) ? health.timeline : [],
        pipelineStatus: health.pipelineStatus || "WAIT",
        loopCount: loops.filter((loop) => loop.status !== "WAIT").length,
        runtimeHealthy: health.runtimeHealthy === true,
        health: health.health || "CRITICAL",
        engineAvailable: health.engineAvailable === true,
        executionEnabled: health.executionEnabled === true,
        executionAllowed: health.executionAllowed === true,
        executionReason: health.executionReason,
    };
};

export function deriveRuntimeHealth({
    botStatus,
    marketState,
    aiState,
    governanceState,
    executionState,
    statusReceivedAt,
} = {}) {
    const snapshot = botStatus || {};
    if (
        snapshot.runtime_health
        && typeof snapshot.runtime_health === "object"
        && snapshot.runtime_health.stages
    ) {
        return deriveAuthoritativeRuntimeHealth(snapshot);
    }
    const running = String(snapshot.status || "").toUpperCase() === "RUNNING";
    const trace = snapshot.runtime_trace || {};
    const metrics = snapshot.runtime_metrics || {};
    const strategyState = snapshot.strategy_state || {};
    const backendExecutionState = snapshot.execution_state || {};
    const liveExecutionState = receivedState(executionState)
        ? executionState
        : {};
    const combinedExecutionState = hasRuntimeValue(backendExecutionState)
        ? backendExecutionState
        : liveExecutionState;
    const liveAiState = receivedState(aiState) ? aiState : {};
    const liveGovernanceState = receivedState(governanceState)
        ? governanceState
        : {};

    const marketUpdated = running && (
        snapshot.marketReady === true
        || traceReached(trace.ws_receive)
        || hasRuntimeValue(metrics.last_ws_message)
        || receivedState(marketState)
    );
    const orderBookUpdated = running && (
        snapshot.ws_connected === true
        || metrics.ws_connected === true
        || traceReached(trace.callback_fire)
    );
    const adapterUpdated = running && (
        traceReached(trace.bot_update)
        || hasRuntimeValue(metrics.last_bot_update)
    );
    const runtimeStateUpdated = running && hasRuntimeValue(
        snapshot.authoritativeRuntimeState,
    );
    const strategyUpdated = running && hasRuntimeValue(strategyState);
    const aiUpdated = running && (
        hasRuntimeValue(snapshot.ai_state)
        || hasRuntimeValue(liveAiState)
    );
    const governanceUpdated = running && (
        hasRuntimeValue(snapshot.governance_state)
        || hasRuntimeValue(liveGovernanceState)
    );
    const executionUpdated = running && hasRuntimeValue(combinedExecutionState);
    const exchangeUpdated = running && (
        snapshot.ws_connected === true
        || hasRuntimeValue(snapshot.exchange)
    );
    const statusUpdated = running && (
        traceReached(trace.status_api)
        || hasRuntimeValue(snapshot.timestamp)
        || hasRuntimeValue(statusReceivedAt)
    );
    const portfolioUpdated = running && (
        isFiniteNumber(snapshot.balance)
        || isFiniteNumber(snapshot.equity)
        || hasRuntimeValue(snapshot.position)
        || hasRuntimeValue(snapshot.actual_position)
    );

    const statusByStage = {
        "start-request": running ? "OK" : "WAIT",
        "trading-runtime": running ? "ACTIVE" : "WAIT",
        "market-data": marketUpdated ? "OK" : "WAIT",
        "order-book": orderBookUpdated ? "OK" : "WAIT",
        "runtime-adapter": adapterUpdated ? "OK" : "WAIT",
        "runtime-state": runtimeStateUpdated ? "OK" : "WAIT",
        "strategy-plugin": strategyUpdated ? "OK" : "WAIT",
        "ai-plugin": aiUpdated ? "OK" : "WAIT",
        "governance-runtime": governanceUpdated ? "OK" : "WAIT",
        "execution-runtime": executionUpdated ? "OK" : "WAIT",
        "execution-governance": executionUpdated ? "OK" : "WAIT",
        "execution-signal-adapter": executionUpdated ? "OK" : "WAIT",
        "execution-engine": executionUpdated ? "OK" : "WAIT",
        "exchange-client": exchangeUpdated ? "OK" : "WAIT",
        "exchange-api": statusUpdated ? "OK" : "WAIT",
    };

    const completed = running && Object.values(statusByStage).every(
        (status) => status !== "WAIT",
    );
    statusByStage.complete = completed ? "OK" : "WAIT";

    const outputByStage = {
        "start-request": {
            status: snapshot.status,
            symbol: snapshot.symbol,
        },
        "trading-runtime": {
            authoritativeRuntimeState: snapshot.authoritativeRuntimeState,
            runtimeSynchronizationState: snapshot.runtimeSynchronizationState,
        },
        "market-data": {
            price: snapshot.price,
            marketReady: snapshot.marketReady,
            lastWsMessage: metrics.last_ws_message,
        },
        "order-book": {
            wsConnected: snapshot.ws_connected ?? metrics.ws_connected,
            messageCount: metrics.message_count,
            lastCallback: metrics.last_callback,
        },
        "runtime-adapter": trace.bot_update,
        "runtime-state": {
            authoritativeRuntimeState: snapshot.authoritativeRuntimeState,
            runtimeSynchronizationState: snapshot.runtimeSynchronizationState,
        },
        "strategy-plugin": strategyState,
        "ai-plugin": snapshot.ai_state || liveAiState,
        "governance-runtime": snapshot.governance_state || liveGovernanceState,
        "execution-runtime": combinedExecutionState,
        "execution-governance": combinedExecutionState,
        "execution-signal-adapter": combinedExecutionState,
        "execution-engine": combinedExecutionState,
        "exchange-client": {
            wsConnected: snapshot.ws_connected,
            executionMode: snapshot.execution_mode,
        },
        "exchange-api": {
            status: snapshot.status,
            timestamp: snapshot.timestamp ?? statusReceivedAt,
        },
        complete: completed ? combinedExecutionState : undefined,
    };

    const inputByStage = {
        "start-request": {
            symbol: snapshot.symbol,
            mode: snapshot.execution_mode,
        },
        "market-data": trace.ws_receive,
        "order-book": trace.callback_fire,
        "runtime-adapter": trace.callback_fire,
        "runtime-state": trace.bot_update,
        "strategy-plugin": adapterUpdated ? trace.bot_update : undefined,
        "ai-plugin": strategyUpdated ? strategyState : undefined,
        "governance-runtime": aiUpdated ? (snapshot.ai_state || liveAiState) : undefined,
        "execution-runtime": governanceUpdated
            ? (snapshot.governance_state || liveGovernanceState)
            : undefined,
    };

    const stages = STAGE_DEFINITIONS.map((definition) => {
        const traceKey = TRACE_KEYS[definition.id];
        const traceState = traceKey ? trace[traceKey] : undefined;
        const exception = traceState?.exception
            || outputByStage[definition.id]?.exception;

        return {
            ...definition,
            status: statusByStage[definition.id],
            duration: statusByStage[definition.id] !== "WAIT" && (
                definition.id === "market-data"
                || definition.id === "order-book"
                || definition.id === "runtime-adapter"
            )
                ? durationValue(metrics.latency_ms)
                : "--",
            input: displayValue(inputByStage[definition.id]),
            output: displayValue(outputByStage[definition.id]),
            exception: hasRuntimeValue(exception)
                ? displayValue(exception)
                : "None",
            relatedFiles: definition.relatedFiles.join("\n") || "--",
        };
    });

    const loops = [
        { id: "runtime-loop", name: "Runtime Loop", status: running ? "RUNNING" : "WAIT" },
        { id: "market-feed", name: "Market Feed", status: marketUpdated ? "RUNNING" : "WAIT" },
        { id: "orderbook-ws", name: "OrderBook WS", status: orderBookUpdated ? "RUNNING" : "WAIT" },
        { id: "strategy-loop", name: "Strategy Loop", status: strategyUpdated ? "RUNNING" : "WAIT" },
        { id: "ai-loop", name: "AI Loop", status: aiUpdated ? "RUNNING" : "WAIT" },
        { id: "governance-loop", name: "Governance Loop", status: governanceUpdated ? "RUNNING" : "WAIT" },
        { id: "execution-queue", name: "Execution Queue", status: executionUpdated ? "OK" : "WAIT" },
        { id: "exchange-sync", name: "Exchange Sync", status: statusUpdated || exchangeUpdated ? "OK" : "WAIT" },
        { id: "portfolio-sync", name: "Portfolio Sync", status: portfolioUpdated ? "OK" : "WAIT" },
    ];
    const loopCount = loops.filter((loop) => loop.status !== "WAIT").length;

    return {
        running,
        stages,
        loops,
        pipelineStatus: !running ? "WAIT" : (completed ? "OK" : "ACTIVE"),
        loopCount: running ? loopCount : 0,
        timeline: [],
        runtimeHealthy: running && !snapshot.marketStale,
        health: running && !snapshot.marketStale ? "HEALTHY" : "CRITICAL",
        engineAvailable: snapshot.executionAuthorityScore > 0,
        executionEnabled: false,
        executionAllowed: false,
        executionReason: undefined,
    };
}
