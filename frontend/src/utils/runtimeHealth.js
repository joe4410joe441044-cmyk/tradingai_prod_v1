const EMPTY_TEXT_VALUES = new Set([
    "",
    "--",
    "UNKNOWN",
    "NO DATA",
    "NONE",
    "NULL",
    "UNDEFINED",
]);

const hasValue = (value) => {
    if (value === null || value === undefined) return false;
    if (typeof value === "number") return Number.isFinite(value);
    if (typeof value === "string") {
        return !EMPTY_TEXT_VALUES.has(value.trim().toUpperCase());
    }
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.keys(value).length > 0;
    return true;
};

const displayValue = (value) => {
    if (!hasValue(value)) return "--";
    if (typeof value === "string") return value;
    if (typeof value === "boolean" || typeof value === "number") {
        return String(value);
    }

    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return "--";
    }
};

const displayDuration = (value) => (
    typeof value === "number" && Number.isFinite(value)
        ? `${value.toFixed(2)} ms`
        : "--"
);

const missingSnapshot = () => ({
    snapshotPresent: false,
    snapshotId: null,
    statusFingerprint: null,
    running: false,
    browserWebSocket: { status: "DISCONNECTED", connected: false },
    exchangeWebSocket: { status: "UNKNOWN", connected: false },
    runtimeEngine: { status: "ERROR", healthy: false },
    runtimeLoop: { status: "STOPPED", running: false },
    marketFeed: { status: "UNKNOWN", healthy: false },
    orderBook: { status: "UNKNOWN", healthy: false },
    strategy: { status: "UNKNOWN", reached: false },
    ai: { status: "UNKNOWN", reached: false },
    governance: { status: "UNKNOWN", reached: false },
    executionQueue: { status: "UNKNOWN", reached: false },
    signalAdapter: { status: "UNKNOWN", reached: false },
    executionEngine: {
        status: "UNAVAILABLE",
        available: false,
        enabled: false,
        allowed: false,
        reason: "SNAPSHOT_MISSING",
    },
    tradingAction: { status: "UNKNOWN", reason: "SNAPSHOT_MISSING" },
    stages: [{
        id: "runtime-health",
        name: "Runtime Health Snapshot",
        status: "ERROR",
        backendFile: "backend/runtime/runtime_health_snapshot.py",
        functionName: "build_runtime_health_snapshot",
        duration: "--",
        input: "--",
        output: "--",
        exception: "SNAPSHOT_MISSING",
        reason: "SNAPSHOT_MISSING",
        relatedFiles: "backend/api/websocket.py\nbackend/api/bot_api.py",
    }],
    activeStageId: "runtime-health",
    loops: [],
    timeline: [],
    pipelineStatus: "ERROR",
    loopCount: 0,
    session: "UNKNOWN",
    version: "UNKNOWN",
    runtimeHealthy: false,
    health: "CRITICAL",
    blockingReason: "SNAPSHOT_MISSING",
    issues: ["SNAPSHOT_MISSING"],
    engineAvailable: false,
    executionEnabled: false,
    executionAllowed: false,
    executionReason: "SNAPSHOT_MISSING",
    latencyMs: null,
});

const normalizeStage = ([id, stage = {}]) => ({
    id: stage.id || id,
    name: stage.name || id,
    status: stage.status || "UNKNOWN",
    reached: stage.reached === true,
    backendFile: stage.backendFile || "--",
    functionName: stage.functionName || "--",
    duration: displayDuration(stage.durationMs),
    input: displayValue(stage.input),
    output: displayValue(stage.output),
    exception: displayValue(stage.exception) === "--"
        ? "None"
        : displayValue(stage.exception),
    reason: displayValue(stage.reason),
    relatedFiles: Array.isArray(stage.relatedFiles)
        ? stage.relatedFiles.join("\n") || "--"
        : displayValue(stage.relatedFiles),
});

const LOOP_NAMES = {
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

const normalizeTimelineEvent = (event = {}) => {
    const reason = String(event.reason ?? "").toUpperCase();
    const state = String(event.state ?? "").toUpperCase();

    return {
        ...event,
        state: state === "IDLE" && reason.includes("AI_HOLD")
            ? "IDLE_BY_AI_HOLD"
            : event.state,
    };
};

export function deriveRuntimeHealth({ botStatus } = {}) {
    const health = botStatus?.runtime_health;

    if (!health || typeof health !== "object" || !health.stages) {
        return missingSnapshot();
    }

    const stages = Object.entries(health.stages).map(normalizeStage);
    const loops = Object.entries(health.loops || {}).map(([id, status]) => ({
        id,
        name: LOOP_NAMES[id] || id,
        status,
    }));

    return {
        snapshotPresent: true,
        schemaVersion: health.schemaVersion,
        source: health.source,
        snapshotId: health.snapshotId,
        statusFingerprint: health.statusFingerprint,
        running: health.bot?.running === true,
        browserWebSocket: health.browserWebSocket || {},
        exchangeWebSocket: health.exchangeWebSocket || {},
        runtimeEngine: health.runtimeEngine || {},
        runtimeLoop: health.runtimeLoop || {},
        marketFeed: health.marketFeed || {},
        orderBook: health.orderBook || {},
        strategy: health.strategy || {},
        ai: health.ai || {},
        governance: health.governance || {},
        executionQueue: health.executionQueue || {},
        signalAdapter: health.signalAdapter || {},
        executionEngine: health.executionEngine || {},
        tradingAction: health.tradingAction || {},
        stages,
        activeStageId: health.activeStageId || stages[0]?.id,
        loops,
        timeline: Array.isArray(health.timeline)
            ? health.timeline.map(normalizeTimelineEvent)
            : [],
        pipelineStatus: health.pipeline?.status || health.pipelineStatus || "UNKNOWN",
        loopCount: loops.filter(({ status }) => (
            status === "RUNNING" || status === "OK"
        )).length,
        session: health.session?.status
            || health.states?.governance?.session_state
            || "UNKNOWN",
        version: health.schemaVersion == null
            ? "UNKNOWN"
            : `V${health.schemaVersion}`,
        runtimeHealthy: health.runtimeHealthy === true,
        health: health.severity || health.health || "CRITICAL",
        blockingReason: health.blockingReason,
        issues: Array.isArray(health.issues) ? health.issues : [],
        engineAvailable: health.executionEngine?.available === true,
        executionEnabled: health.executionEngine?.enabled === true,
        executionAllowed: health.executionEngine?.allowed === true,
        executionReason: health.executionEngine?.reason,
        latencyMs: health.latencyMs,
    };
}
