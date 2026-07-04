import test from "node:test";
import assert from "node:assert/strict";

import { deriveRuntimeHealth } from "./runtimeHealth.js";

test("authoritative backend health snapshot drives monitor statuses", () => {
    const result = deriveRuntimeHealth({
        botStatus: {
            status: "RUNNING",
            runtime_metrics: { latency_ms: 2.5 },
            runtime_health: {
                runtimeHealthy: true,
                health: "HEALTHY",
                pipelineStatus: "OK",
                engineAvailable: true,
                executionEnabled: true,
                executionAllowed: false,
                executionReason: "AI_HOLD",
                stages: {
                    "strategy-plugin": { status: "OK", reached: true },
                    "execution-runtime": {
                        status: "OK",
                        reached: true,
                        reason: "AI_HOLD",
                    },
                    "execution-engine": {
                        status: "IDLE",
                        reached: false,
                        reason: "AI_HOLD",
                    },
                },
                loops: {
                    "strategy-loop": "RUNNING",
                    "ai-loop": "RUNNING",
                    "governance-loop": "RUNNING",
                    "execution-queue": "RUNNING",
                },
                timeline: [{
                    timestamp: "2026-07-04T00:00:00+00:00",
                    source: "Execution Runtime",
                    state: "OK",
                }],
                states: {
                    strategy: {},
                    ai: {},
                    governance: {},
                    execution: {},
                },
            },
        },
    });

    assert.equal(result.runtimeHealthy, true);
    assert.equal(result.health, "HEALTHY");
    assert.equal(result.engineAvailable, true);
    assert.equal(result.executionEnabled, true);
    assert.equal(result.executionAllowed, false);
    assert.equal(result.executionReason, "AI_HOLD");
    assert.equal(
        result.stages.find((stage) => stage.id === "execution-engine").status,
        "IDLE",
    );
    assert.equal(
        result.loops.find((loop) => loop.id === "strategy-loop").status,
        "RUNNING",
    );
    assert.equal(result.timeline.length, 1);
});
