import test from "node:test";
import assert from "node:assert/strict";

import {
    formatActivityTime,
    formatLatency,
    getAutoTradeActivity,
    getLastExecutionActivity,
    getRuntimeReasonLabel,
    getRuntimeSourceLabel,
} from "./runtimeDisplay.js";

test("runtime source labels are operator friendly with an unknown fallback", () => {
    assert.equal(getRuntimeSourceLabel("AI Plugin"), "AI Decision");
    assert.equal(getRuntimeSourceLabel("Strategy Plugin"), "Strategy Evaluation");
    assert.equal(getRuntimeSourceLabel("Governance Runtime"), "Safety / Governance Check");
    assert.equal(getRuntimeSourceLabel("Execution Runtime"), "Execution Check");
    assert.equal(getRuntimeSourceLabel("Custom Source"), "Custom Source");
});

test("runtime reasons preserve codes while supplying readable labels", () => {
    assert.equal(getRuntimeReasonLabel("LIQUIDITY_DETERIORATION"), "Liquidity deterioration");
    assert.equal(getRuntimeReasonLabel("AI_HOLD"), "AI HOLD");
    assert.equal(getRuntimeReasonLabel("IDLE_BY_AI_HOLD"), "Waiting — AI HOLD");
});

test("auto trade HOLD is presented as enabled and waiting", () => {
    assert.deepEqual(getAutoTradeActivity({
        enabled: true,
        emergencyState: "READY",
        tradingAction: "IDLE_BY_AI_HOLD",
        decision: "HOLD",
    }), { state: "ENABLED", detail: "WAITING FOR SIGNAL" });
    assert.deepEqual(getAutoTradeActivity({ enabled: false }), {
        state: "DISABLED", detail: null,
    });
});

test("latency formatting is finite and consistently rounded", () => {
    assert.equal(formatLatency("184.52835083007812"), "184.53 ms");
    assert.equal(formatLatency(null), "--");
    assert.equal(formatLatency(Number.NaN), "--");
});

test("last activity prefers actual orders, then execution checks", () => {
    const check = { source: "Execution Runtime", state: "IDLE", timestamp: "2026-07-19T13:42:08Z" };
    assert.equal(getLastExecutionActivity([check]).label, "LAST EXECUTION CHECK");
    const result = getLastExecutionActivity([
        check,
        { source: "Execution Runtime", state: "ORDER_SUBMITTED", timestamp: "2026-07-19T13:43:08Z" },
    ]);
    assert.equal(result.label, "LAST ORDER");
    assert.notEqual(formatActivityTime(result.timestamp), "NONE THIS SESSION");
    assert.equal(formatActivityTime(null), "NONE THIS SESSION");
});
