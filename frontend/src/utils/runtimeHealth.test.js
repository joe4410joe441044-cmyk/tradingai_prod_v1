import test from "node:test";
import assert from "node:assert/strict";

import { deriveRuntimeHealth } from "./runtimeHealth.js";

const backendHealth = {
    schemaVersion: 2,
    source: "BotManager.get_result",
    snapshotId: "cycle-1",
    statusFingerprint: "same-health",
    bot: { status: "RUNNING", running: true },
    executionAuthority: { status: "ENABLED", enabled: true },
    browserWebSocket: { status: "LIVE", connected: true, clientCount: 1 },
    exchangeWebSocket: { status: "LIVE", connected: true },
    runtimeEngine: { status: "ACTIVE", healthy: true },
    runtimeLoop: { status: "RUNNING", running: true },
    marketFeed: { status: "LIVE", healthy: true },
    orderBook: { status: "LIVE", healthy: true },
    strategy: { reached: true, status: "IDLE", reason: "NO_SIGNAL" },
    ai: { reached: true, status: "IDLE", reason: "AI_HOLD" },
    governance: { reached: true, status: "IDLE", reason: "AI_HOLD" },
    executionQueue: { reached: true, status: "RUNNING", reason: "AI_HOLD" },
    signalAdapter: { reached: false, status: "IDLE", reason: "AI_HOLD" },
    executionEngine: {
        available: true,
        enabled: true,
        allowed: false,
        status: "ENABLED_IDLE_BY_AI_HOLD",
        reason: "AI_HOLD",
    },
    tradingAction: {
        status: "IDLE_BY_AI_HOLD",
        reason: "AI_HOLD",
        decision: "HOLD",
    },
    pipeline: { status: "OK" },
    severity: "HEALTHY",
    blockingReason: null,
    issues: [],
    runtimeHealthy: true,
    latencyMs: 2.5,
    activeStageId: "trading-runtime",
    stages: {
        "trading-runtime": {
            id: "trading-runtime",
            name: "TradingRuntime",
            status: "ACTIVE",
            reached: true,
            backendFile: "backend/main.py",
            functionName: "TradingRuntime.process_runtime",
            relatedFiles: ["backend/runtime/runtime_registry.py"],
            durationMs: null,
            input: null,
            output: { runtimeHealthy: true },
            exception: null,
            reason: null,
        },
        "execution-runtime": {
            id: "execution-runtime",
            name: "Execution Runtime",
            status: "IDLE",
            reached: true,
            backendFile: "backend/runtime/ExecutionRuntime.py",
            functionName: "process_execution_runtime",
            relatedFiles: [],
            reason: "AI_HOLD",
        },
    },
    loops: {
        "runtime-loop": "RUNNING",
        "execution-queue": "RUNNING",
    },
    timeline: [{
        timestamp: "2026-07-04T00:00:00+00:00",
        source: "Execution Runtime",
        state: "IDLE",
        reason: "AI_HOLD",
    }],
};

test("authoritative backend health snapshot drives every monitor status", () => {
    const result = deriveRuntimeHealth({
        botStatus: { runtime_health: backendHealth },
    });

    assert.equal(result.snapshotPresent, true);
    assert.equal(result.runtimeHealthy, true);
    assert.equal(result.health, "HEALTHY");
    assert.equal(result.browserWebSocket.status, "LIVE");
    assert.equal(result.exchangeWebSocket.status, "LIVE");
    assert.equal(result.runtimeEngine.status, "ACTIVE");
    assert.equal(result.executionAuthority.status, "ENABLED");
    assert.equal(result.executionEngine.status, "ENABLED_IDLE_BY_AI_HOLD");
    assert.equal(result.tradingAction.status, "IDLE_BY_AI_HOLD");
    assert.equal(result.executionReason, "AI_HOLD");
    assert.equal(result.pipelineStatus, "OK");
    assert.equal(result.loopCount, 2);
    assert.equal(result.activeStageId, "trading-runtime");
    assert.equal(
        result.stages.find(({ id }) => id === "execution-runtime").status,
        "IDLE",
    );
    assert.equal(result.stages[0].backendFile, "backend/main.py");
    assert.equal(result.timeline[0].reason, "AI_HOLD");
    assert.equal(result.timeline[0].state, "IDLE_BY_AI_HOLD");
    assert.equal(result.session, "UNKNOWN");
    assert.equal(result.version, "V2");
});

test("missing snapshot is explicit critical telemetry, not a WAIT placeholder", () => {
    const result = deriveRuntimeHealth({ botStatus: {} });

    assert.equal(result.snapshotPresent, false);
    assert.equal(result.health, "CRITICAL");
    assert.equal(result.blockingReason, "SNAPSHOT_MISSING");
    assert.equal(result.stages[0].name, "Runtime Health Snapshot");
    assert.equal(result.stages[0].status, "ERROR");
    assert.equal(result.timeline.length, 0);
});

test("stopped snapshot keeps the previous hold out of current UI state", () => {
    const stoppedHealth = {
        ...backendHealth,
        bot: { status: "STOPPED", running: false },
        lifecycleRevision: 8,
        lifecycle: { state: "STOPPED", revision: 8 },
        executionEngine: {
            available: false,
            enabled: true,
            allowed: false,
            status: "UNAVAILABLE_BY_BOT_STOP",
            reason: "BOT_STOPPED",
        },
        tradingAction: {
            status: "NONE_BY_BOT_STOP",
            decision: "N/A",
            reason: "BOT_STOPPED",
        },
        timeline: [],
    };
    const result = deriveRuntimeHealth({
        botStatus: { runtime_health: stoppedHealth },
    });

    assert.equal(result.running, false);
    assert.equal(result.executionAuthority.status, "ENABLED");
    assert.equal(result.executionEnabled, true);
    assert.equal(result.executionEngine.status, "UNAVAILABLE_BY_BOT_STOP");
    assert.equal(result.tradingAction.status, "NONE_BY_BOT_STOP");
    assert.equal(result.tradingAction.decision, "N/A");
    assert.equal(result.timeline.length, 0);
    assert.equal(result.lifecycleRevision, 8);
});
