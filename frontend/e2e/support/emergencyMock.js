import {
    createNetworkIsolation,
} from "./networkIsolation.js";

export const ENDPOINTS = {
    status: "/api/bot/status",
    botStart: "/api/bot/start",
    botStop: "/api/bot/stop",
    execution: "/api/governance/execution",
    emergency: "/api/governance/emergency-orchestrate",
    unlock: "/api/governance/emergency/unlock",
};

const clone = (value) => JSON.parse(JSON.stringify(value));

const delay = (ms) => new Promise((resolve) => {
    setTimeout(resolve, ms);
});

const jsonFulfill = async (route, body, status = 200) => {
    await route.fulfill({
        status,
        contentType: "application/json",
        headers: {
            "cache-control": "no-store",
        },
        body: JSON.stringify(body),
    });
};

const nowIso = () => new Date().toISOString();

const createTimelineEvent = ({
    operationId,
    event,
    state,
    reason,
}) => ({
    type: "EMERGENCY",
    source: "GOVERNANCE",
    level: event === "EMERGENCY_ACTION_REQUIRED" ? "WARN" : "INFO",
    event,
    label: event,
    state,
    reason,
    message: reason,
    operationId,
    timestamp: nowIso(),
});

const toApiEmergencyResult = (lastResult) => ({
    success: lastResult.success,
    completed: lastResult.completed,
    partial: lastResult.partial,
    state_unknown: lastResult.stateUnknown,
    position_remaining: lastResult.positionRemaining,
    emergency_locked: true,
    auto_trade_disabled: true,
    retryable: lastResult.retryable,
    error_code: lastResult.errorCode,
    operation_id: lastResult.operationId,
    operationId: lastResult.operationId,
    result: lastResult.result,
    path: lastResult.path,
    cancel: lastResult.cancelResult,
    flatten: lastResult.flattenResult,
    cancel_result: lastResult.cancelResult,
    flatten_result: lastResult.flattenResult,
});

const baseCancelResult = () => ({
    status: "NOT_REQUIRED",
    success: true,
    completed: true,
    orders_cancelled: 0,
    ordersCancelled: 0,
});

const baseFlattenResult = () => ({
    status: "NOT_REQUIRED",
    success: true,
    completed: true,
    position_closed: false,
    positionClosed: false,
});

const createLastResult = ({
    operationId,
    state,
    result,
    success,
    completed,
    partial,
    stateUnknown,
    positionRemaining,
    retryable,
    errorCode = null,
    message,
}) => ({
    operationId,
    state,
    result,
    success,
    completed,
    partial,
    stateUnknown,
    positionRemaining,
    retryable,
    errorCode,
    path: "paper",
    cancelResult: baseCancelResult(),
    flattenResult: baseFlattenResult(),
    completedAt: completed ? nowIso() : null,
                message: message || (
                    errorCode
                        ? `Emergency requires operator action: ${errorCode}`
                        : "Manual safety confirmation is required."
                ),
            });

const initialState = () => ({
    revision: 0,
    operationCounter: 0,
    botStatus: "STOPPED",
    loopEnabled: false,
    loopState: "STOPPED",
    autoTradeEnabled: false,
    executionEnabled: false,
    emergencyStop: false,
    emergencyLocked: false,
    emergencyState: "READY",
    selectedMode: "PAPER",
    dryRun: true,
    positionRemaining: false,
    pendingOrder: false,
    stateUnknown: false,
    currentOperationId: null,
    lastResult: null,
    timeline: [],
    nextEmergencyOutcome: "success",
});

const buildRuntimeHealth = (state) => {
    const running = state.botStatus === "RUNNING";
    const blockedByEmergency = state.emergencyState !== "READY";
    const loopStatus = state.loopEnabled ? "RUNNING" : "STOPPED";
    const pipelineStatus = running ? "OK" : "SUSPENDED_BY_BOT_STOP";
    const executionStatus = running
        ? (state.executionEnabled ? "AVAILABLE" : "DISABLED")
        : "UNAVAILABLE_BY_BOT_STOP";
    const actionReason = running ? "AI_HOLD" : "BOT_STOPPED";

    return {
        schemaVersion: 1,
        source: "E2E_LOCAL_MOCK",
        snapshotId: `e2e-${state.revision}`,
        lifecycleRevision: state.revision,
        generatedAt: nowIso(),
        cycleId: `e2e-cycle-${state.revision}`,
        statusFingerprint: `e2e-${state.revision}-${state.emergencyState}`,
        bot: {
            status: state.botStatus,
            running,
        },
        executionAuthority: {
            status: state.executionEnabled
                ? "ENABLED"
                : "DISABLED_BY_OPERATOR",
            enabled: state.executionEnabled,
        },
        browserWebSocket: {
            status: "DISCONNECTED",
            connected: false,
        },
        exchangeWebSocket: {
            status: running ? "LIVE" : "DISCONNECTED_BY_BOT_STOP",
            connected: running,
        },
        runtimeEngine: {
            status: running ? "ACTIVE" : "STOPPED",
            healthy: running,
        },
        runtimeLoop: {
            status: loopStatus,
            running: state.loopEnabled,
        },
        marketFeed: {
            status: running ? "LIVE" : "SUSPENDED_BY_BOT_STOP",
            healthy: running,
        },
        orderBook: {
            status: running ? "LIVE" : "SUSPENDED_BY_BOT_STOP",
            healthy: running,
        },
        strategy: {
            status: running ? "EVALUATED" : "SUSPENDED_BY_BOT_STOP",
            reached: running,
        },
        ai: {
            status: running ? "EVALUATED" : "SUSPENDED_BY_BOT_STOP",
            reached: running,
        },
        governance: {
            status: blockedByEmergency ? state.emergencyState : "IDLE",
            reached: true,
        },
        executionQueue: {
            status: state.executionEnabled ? "READY" : "DISABLED",
            reached: true,
        },
        signalAdapter: {
            status: running ? "READY" : "SUSPENDED_BY_BOT_STOP",
            reached: running,
        },
        executionEngine: {
            status: running && state.executionEnabled
                ? "ENABLED_IDLE_BY_AI_HOLD"
                : executionStatus,
            available: running,
            enabled: state.executionEnabled,
            allowed: running && state.executionEnabled,
            reason: running
                ? (state.executionEnabled ? "READY" : "EXECUTION_DISABLED")
                : "BOT_STOPPED",
        },
        tradingAction: {
            status: running && state.executionEnabled
                ? "IDLE_BY_AI_HOLD"
                : running ? "WAIT" : "NONE_BY_BOT_STOP",
            decision: running ? "HOLD" : "N/A",
            reason: actionReason,
        },
        stages: {
            "trading-runtime": {
                id: "trading-runtime",
                name: "Trading Runtime",
                status: running ? "OK" : "STOPPED",
                reached: true,
                durationMs: 0.5,
                input: {
                    bot: state.botStatus,
                },
                output: {
                    loop: loopStatus,
                },
                exception: null,
                reason: actionReason,
                relatedFiles: [
                    "frontend/e2e/support/emergencyMock.js",
                ],
            },
            governance: {
                id: "governance",
                name: "Emergency Governance",
                status: blockedByEmergency ? state.emergencyState : "IDLE",
                reached: true,
                durationMs: 0.5,
                input: {
                    state: state.emergencyState,
                },
                output: {
                    locked: state.emergencyLocked,
                },
                exception: null,
                reason: blockedByEmergency
                    ? state.emergencyState
                    : "READY",
                relatedFiles: [
                    "frontend/e2e/emergency.spec.js",
                ],
            },
        },
        activeStageId: "trading-runtime",
        loops: {
            "runtime-loop": loopStatus,
            "market-feed": running ? "RUNNING" : "STOPPED",
            "orderbook-ws": running ? "RUNNING" : "STOPPED",
            "strategy-loop": running ? "RUNNING" : "STOPPED",
            "ai-loop": running ? "RUNNING" : "STOPPED",
            "governance-loop": blockedByEmergency
                ? state.emergencyState
                : "IDLE",
            "execution-queue": state.executionEnabled ? "READY" : "DISABLED",
        },
        timeline: clone(state.timeline),
        pipeline: {
            status: pipelineStatus,
        },
        pipelineStatus,
        session: {
            status: running ? "ACTIVE" : "STOPPED",
        },
        states: {
            governance: {
                session_state: running ? "ACTIVE" : "STOPPED",
            },
        },
        runtimeHealthy: running && !blockedByEmergency,
        severity: blockedByEmergency ? "DEGRADED" : "HEALTHY",
        health: blockedByEmergency ? "DEGRADED" : "HEALTHY",
        blockingReason: blockedByEmergency ? state.emergencyState : null,
        issues: blockedByEmergency ? [state.emergencyState] : [],
        latencyMs: 1,
    };
};

const buildStatus = (state) => {
    const timestamp = Date.now() / 1000;

    return {
        status: state.botStatus,
        timestamp,
        last_update: timestamp,
        price: 0.5,
        marketReady: false,
        marketStale: false,
        execution_mode: "SIMULATION",
        real_order_allowed: false,
        accountSource: "PAPER_SIMULATION",
        balanceSource: "PAPER_SIMULATION",
        positionSource: "PAPER_SIMULATION",
        realOrderAllowed: false,
        executionMode: "SIMULATION",
        dryRun: state.dryRun,
        selectedMode: state.selectedMode,
        safetyReason: "DRY_RUN_ACTIVE",
        allowLive: false,
        tradeMode: "paper",
        exchangeAuth: "NOT_VERIFIED",
        realAccountConnected: false,
        realBalance: null,
        realEquity: null,
        realAvailableBalance: null,
        realPosition: null,
        realPositionState: "NO_OPEN_POSITION",
        realAccountLastSync: null,
        realLastSync: null,
        exchangeConnection: "NOT_CONNECTED",
        apiKeyStatus: "MISSING",
        permission: "NOT_VERIFIED",
        accountType: "UNKNOWN",
        accountRuntime: {
            paperAccount: {
                available: true,
                balance: 10000,
                equity: 10000,
                availableBalance: 10000,
                positions: [],
                totalPnl: 0,
                source: "PAPER_SIMULATION",
            },
            realAccount: {
                connected: false,
                positions: [],
                balance: null,
                equity: null,
                availableBalance: null,
                positionSummary: "NO_OPEN_POSITION",
                accountReason: "ACCOUNT_NOT_SYNCED",
                balanceReason: "ACCOUNT_NOT_SYNCED",
                positionReason: "ACCOUNT_NOT_SYNCED",
            },
            connection: {
                apiKeyStatus: "MISSING",
            },
        },
        ws_connected: false,
        position_active: state.positionRemaining,
        pendingOrder: state.pendingOrder,
        balance: 10000,
        equity: 10000,
        availableBalance: 10000,
        available_balance: 10000,
        pnl: 0,
        position_size: 100,
        positionSize: 100,
        risk_percent: 1,
        leverage: 5,
        timeframe: "1m",
        max_drawdown_pct: 5,
        maxDd: 5,
        tp_percent: 1,
        sl_percent: 1,
        current_drawdown_pct: 0,
        risk_block_reason: null,
        risk_config: {},
        risk_state: {},
        trade_settings: {},
        tradeSettings: {},
        liveReadiness: {},
        liveBlockReasons: [],
        exchangeClientReady: false,
        exchangeAuthReady: false,
        balanceCheckOk: true,
        positionCheckOk: true,
        executionEnabled: state.executionEnabled,
        loopEnabled: state.loopEnabled,
        loopState: state.loopState,
        autoTradeEnabled: state.autoTradeEnabled,
        emergencyStop: state.emergencyStop,
        emergencyLocked: state.emergencyLocked,
        emergencyState: state.emergencyState,
        emergency: {
            active: state.emergencyStop,
            locked: state.emergencyLocked,
            state: state.emergencyState,
            operationId: state.currentOperationId,
            lastResult: state.lastResult ? clone(state.lastResult) : null,
        },
        executionAuthorityScore: state.executionEnabled ? 100 : 0,
        authoritativeRuntimeState: state.botStatus,
        runtimeSynchronizationState: "SYNCED",
        runtime_trace: {},
        runtime_metrics: {},
        strategy_state: {},
        execution_state: {},
        ai_state: null,
        governance_state: null,
        runtime_health: buildRuntimeHealth(state),
        latestRuntimeResult: null,
        executionRuntimeReached: state.botStatus === "RUNNING",
        signalAdapterReached: state.botStatus === "RUNNING",
        normalizedDirection: null,
        adapterOutput: null,
        symbol: "XRPUSDT",
        exchange: "KUCOIN",
        orderbookSource: "E2E_LOCAL_MOCK",
        orderbookSymbol: "XRPUSDT",
        position: [],
        actual_position: [],
    };
};

const makeHttpError = (status, reason) => ({
    detail: {
        reason,
        message: reason,
    },
});

export function createEmergencyMock() {
    let state = initialState();
    let calls = {};
    let queuedFailures = {};
    let routeDelays = {};
    const unexpectedApiRequests = [];
    const networkIsolation = createNetworkIsolation({
        apiHandler: async (route, { path }) => {
            await handleApi(route, path);
        },
    });

    const reset = () => {
        state = initialState();
        calls = {};
        queuedFailures = {};
        routeDelays = {};
    };

    const increment = (path) => {
        calls[path] = (calls[path] || 0) + 1;
    };

    const mutate = (update) => {
        update(state);
        state.revision += 1;
    };

    const nextOperationId = () => {
        state.operationCounter += 1;
        return `e2e-emergency-${state.operationCounter}`;
    };

    const appendEvent = (event) => {
        state.timeline.push(createTimelineEvent(event));
    };

    const beginOperation = () => {
        const operationId = nextOperationId();

        mutate((current) => {
            current.currentOperationId = operationId;
            current.emergencyStop = true;
            current.emergencyLocked = true;
            current.emergencyState = "PROCESSING";
            current.botStatus = "STOPPED";
            current.loopEnabled = false;
            current.loopState = "STOPPED";
            current.autoTradeEnabled = false;
            current.executionEnabled = false;
            current.lastResult = createLastResult({
                operationId,
                state: "PROCESSING",
                result: "PROCESSING",
                success: false,
                completed: false,
                partial: false,
                stateUnknown: false,
                positionRemaining: false,
                retryable: false,
                message: "Emergency processing in progress.",
            });
        });
        appendEvent({
            operationId,
            event: "EMERGENCY_STARTED",
            state: "STARTED",
            reason: "E2E_LOCAL_EMERGENCY_STARTED",
        });

        return operationId;
    };

    const completeSuccess = (operationId) => {
        mutate((current) => {
            current.currentOperationId = operationId;
            current.emergencyStop = true;
            current.emergencyLocked = true;
            current.emergencyState = "LOCKED";
            current.botStatus = "STOPPED";
            current.loopEnabled = false;
            current.loopState = "STOPPED";
            current.autoTradeEnabled = false;
            current.executionEnabled = false;
            current.pendingOrder = false;
            current.positionRemaining = false;
            current.stateUnknown = false;
            current.lastResult = createLastResult({
                operationId,
                state: "LOCKED",
                result: "SUCCESS",
                success: true,
                completed: true,
                partial: false,
                stateUnknown: false,
                positionRemaining: false,
                retryable: false,
                message: "Emergency stopped safely.",
            });
        });
        appendEvent({
            operationId,
            event: "EMERGENCY_COMPLETED",
            state: "LOCKED",
            reason: "SUCCESS",
        });

        return state.lastResult;
    };

    const completeActionRequired = (
        operationId,
        {
            stateUnknown = true,
            positionRemaining = false,
            pendingOrder = false,
            errorCode = "STATE_UNKNOWN",
        } = {},
    ) => {
        mutate((current) => {
            current.currentOperationId = operationId;
            current.emergencyStop = true;
            current.emergencyLocked = true;
            current.emergencyState = "ACTION_REQUIRED";
            current.botStatus = "STOPPED";
            current.loopEnabled = false;
            current.loopState = "STOPPED";
            current.autoTradeEnabled = false;
            current.executionEnabled = false;
            current.pendingOrder = pendingOrder;
            current.positionRemaining = positionRemaining;
            current.stateUnknown = stateUnknown;
            current.lastResult = createLastResult({
                operationId,
                state: "ACTION_REQUIRED",
                result: "ACTION_REQUIRED",
                success: false,
                completed: false,
                partial: true,
                stateUnknown,
                positionRemaining,
                retryable: true,
                errorCode,
                message: "Manual safety confirmation is required.",
            });
        });
        appendEvent({
            operationId,
            event: "EMERGENCY_ACTION_REQUIRED",
            state: "ACTION_REQUIRED",
            reason: errorCode,
        });

        return state.lastResult;
    };

    const seedLockedSuccess = () => {
        const operationId = beginOperation();
        completeSuccess(operationId);
        return operationId;
    };

    const seedActionRequired = (options = {}) => {
        const operationId = beginOperation();
        completeActionRequired(operationId, options);
        return operationId;
    };

    const seedProcessing = () => {
        return beginOperation();
    };

    const handleQueuedFailure = async (route, path) => {
        const failures = queuedFailures[path] || [];

        if (failures.length === 0) {
            return false;
        }

        const failure = failures.shift();
        queuedFailures[path] = failures;

        if (failure.type === "network") {
            await route.abort("failed");
            return true;
        }

        await jsonFulfill(
            route,
            makeHttpError(failure.status, failure.reason),
            failure.status,
        );
        return true;
    };

    const handleEmergency = async (route, path) => {
        increment(path);

        if (await handleQueuedFailure(route, path)) {
            return;
        }

        if (state.emergencyState !== "READY") {
            await jsonFulfill(route, makeHttpError(409, "PROCESSING"), 409);
            return;
        }

        const operationId = beginOperation();

        if (routeDelays[path]) {
            await delay(routeDelays[path]);
        }

        const result = state.nextEmergencyOutcome === "action_required"
            ? completeActionRequired(operationId)
            : state.nextEmergencyOutcome === "snapshot_stale"
                ? completeActionRequired(operationId, {
                    errorCode: "SNAPSHOT_STALE",
                    stateUnknown: true,
                    positionRemaining: false,
                    pendingOrder: false,
                })
                : completeSuccess(operationId);

        await jsonFulfill(route, toApiEmergencyResult(result));
    };

    const handleUnlock = async (route, path) => {
        increment(path);

        if (await handleQueuedFailure(route, path)) {
            return;
        }

        const lastResult = state.lastResult;
        const safeToUnlock = (
            state.emergencyState !== "READY"
            && state.emergencyState !== "PROCESSING"
            && state.emergencyLocked === true
            && state.emergencyStop === true
        );

        if (!safeToUnlock) {
            await jsonFulfill(route, makeHttpError(409, "ACTION_REQUIRED"), 409);
            return;
        }

        if (routeDelays[path]) {
            await delay(routeDelays[path]);
        }

        mutate((current) => {
            current.emergencyStop = false;
            current.emergencyLocked = false;
            current.emergencyState = "READY";
            current.botStatus = "STOPPED";
            current.loopEnabled = false;
            current.loopState = "STOPPED";
            current.autoTradeEnabled = false;
            current.executionEnabled = false;
        });
        appendEvent({
            operationId: lastResult.operationId,
            event: "EMERGENCY_UNLOCKED",
            state: "READY",
            reason: "UNLOCKED",
        });

        await jsonFulfill(route, {
            success: true,
            unlocked: true,
            emergency_stop: false,
            emergency_state: "READY",
            execution_enabled: false,
            operation_id: lastResult.operationId,
        });
    };

    const handleBotStart = async (route, path) => {
        increment(path);

        if (state.emergencyState !== "READY") {
            await jsonFulfill(
                route,
                makeHttpError(409, "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK"),
                409,
            );
            return;
        }

        mutate((current) => {
            current.botStatus = "RUNNING";
            current.loopEnabled = true;
            current.loopState = "RUNNING";
        });
        await jsonFulfill(route, {
            status: "started",
        });
    };

    const handleBotStop = async (route, path) => {
        increment(path);
        mutate((current) => {
            current.botStatus = "STOPPED";
            current.loopEnabled = false;
            current.loopState = "STOPPED";
            current.autoTradeEnabled = false;
            current.executionEnabled = false;
        });
        await jsonFulfill(route, {
            status: "stopped",
        });
    };

    const handleExecution = async (route, path) => {
        increment(path);

        const body = route.request().postDataJSON?.() || {};

        if (state.emergencyState !== "READY") {
            await jsonFulfill(
                route,
                makeHttpError(409, "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK"),
                409,
            );
            return;
        }

        mutate((current) => {
            current.executionEnabled = body.enabled === true;
            current.autoTradeEnabled = body.enabled === true;
        });
        await jsonFulfill(route, {
            success: true,
            execution_enabled: state.executionEnabled,
        });
    };

    const handleApi = async (route, path) => {
        if (path === ENDPOINTS.status) {
            increment(path);
            await jsonFulfill(route, buildStatus(state));
            return;
        }

        if (path === ENDPOINTS.emergency) {
            await handleEmergency(route, path);
            return;
        }

        if (path === ENDPOINTS.unlock) {
            await handleUnlock(route, path);
            return;
        }

        if (path === ENDPOINTS.botStart) {
            await handleBotStart(route, path);
            return;
        }

        if (path === ENDPOINTS.botStop) {
            await handleBotStop(route, path);
            return;
        }

        if (path === ENDPOINTS.execution) {
            await handleExecution(route, path);
            return;
        }

        unexpectedApiRequests.push(path);
        await jsonFulfill(
            route,
            {
                error: "UNMOCKED_API_REQUEST",
                path,
            },
            599,
        );
        throw new Error(`UNMOCKED_API_REQUEST ${path}`);
    };

    const install = async (page) => {
        await networkIsolation.install(page);
    };

    reset();

    return {
        install,
        reset,
        seedLockedSuccess,
        seedActionRequired,
        seedProcessing,
        setNextEmergencyOutcome(outcome) {
            state.nextEmergencyOutcome = outcome;
        },
        setRouteDelay(path, ms) {
            routeDelays[path] = ms;
        },
        queueHttpError(path, status, reason) {
            queuedFailures[path] = queuedFailures[path] || [];
            queuedFailures[path].push({
                type: "http",
                status,
                reason,
            });
        },
        queueNetworkError(path) {
            queuedFailures[path] = queuedFailures[path] || [];
            queuedFailures[path].push({
                type: "network",
            });
        },
        getStatus() {
            return buildStatus(state);
        },
        getState() {
            return clone(state);
        },
        getCallCount(path) {
            return calls[path] || 0;
        },
        getExternalRequests() {
            return networkIsolation.getExternalRequests();
        },
        getExternalHttpRequests() {
            return networkIsolation.getExternalHttpRequests();
        },
        getExternalWebSocketRequests() {
            return networkIsolation.getExternalWebSocketRequests();
        },
        getProductionIpRequests() {
            return networkIsolation.getProductionIpRequests();
        },
        getNetworkIsolationCounts() {
            return networkIsolation.getCounts();
        },
        getUnexpectedApiRequests() {
            return [
                ...unexpectedApiRequests,
                ...networkIsolation.getUnmockedApiRequests(),
            ];
        },
        assertNetworkClean(expect) {
            networkIsolation.assertClean(expect);
            expect(unexpectedApiRequests).toEqual([]);
        },
    };
}
