import assert from "node:assert/strict";
import test from "node:test";

import { normalizeAdvisorRuntimeResponse } from "./advisorRuntimeModel.js";

const fullResponse = () => ({
    bot: {
        state: "RUNNING",
        mode: "PAPER",
        exchange: "kucoin",
        symbol: "XRPUSDTM",
        ignored: "not exposed",
    },
    operation: {
        loopEnabled: true,
        loopState: "RUNNING",
        autoTradeEnabled: false,
    },
    safety: {
        emergencyLocked: false,
        emergencyState: "READY",
        dryRun: true,
        realOrderAllowed: false,
    },
    runtime: {
        capturedAt: "2026-07-25T10:00:00+00:00",
        sourceUpdatedAt: "2026-07-25T09:59:58+00:00",
        freshness: "FRESH",
    },
    warnings: ["SAFE_WARNING"],
    credential: "not exposed",
});

test("normalization keeps only the frontend runtime contract", () => {
    const normalized = normalizeAdvisorRuntimeResponse(fullResponse());

    assert.equal(normalized.bot.state, "RUNNING");
    assert.equal(normalized.operation.loopEnabled, true);
    assert.equal(normalized.safety.realOrderAllowed, false);
    assert.equal(normalized.runtime.freshness, "FRESH");
    assert.deepEqual(normalized.warnings, ["SAFE_WARNING"]);
    assert.equal("ignored" in normalized.bot, false);
    assert.equal("credential" in normalized, false);
});

test("partial and malformed values remain unknown instead of inferred", () => {
    const normalized = normalizeAdvisorRuntimeResponse({
        bot: { state: "BROKEN" },
        operation: {
            loopEnabled: "true",
            loopState: "BROKEN",
            autoTradeEnabled: 0,
        },
        safety: {
            emergencyLocked: {},
            emergencyState: "BROKEN",
            dryRun: "false",
            realOrderAllowed: 1,
        },
        runtime: {
            capturedAt: "not-a-time",
            freshness: "BROKEN",
        },
    });

    assert.equal(normalized.bot.state, "UNKNOWN");
    assert.equal(normalized.bot.mode, null);
    assert.equal(normalized.operation.loopEnabled, null);
    assert.equal(normalized.operation.autoTradeEnabled, null);
    assert.equal(normalized.safety.dryRun, null);
    assert.equal(normalized.safety.realOrderAllowed, null);
    assert.equal(normalized.safety.emergencyState, "UNKNOWN");
    assert.equal(normalized.runtime.freshness, "UNKNOWN");
    assert.equal(normalized.runtime.capturedAt, null);
    assert.equal(normalized.runtime.sourceUpdatedAt, null);
    assert.ok(normalized.warnings.length >= 6);
});

test("normal backend enum values are preserved and unsupported bot states fail closed", () => {
    for (const state of ["NOT_CONNECTED", "STOPPED", "RUNNING", "UNKNOWN"]) {
        const value = fullResponse();
        value.bot.state = state;
        assert.equal(normalizeAdvisorRuntimeResponse(value).bot.state, state);
    }
    for (const state of [
        "NOT_CONNECTED", "STOPPED", "STARTING", "RUNNING", "STOPPING", "UNKNOWN",
    ]) {
        const value = fullResponse();
        value.operation.loopState = state;
        assert.equal(normalizeAdvisorRuntimeResponse(value).operation.loopState, state);
    }
    for (const state of [
        "READY", "PROCESSING", "LOCKED", "ACTION_REQUIRED", "UNKNOWN",
    ]) {
        const value = fullResponse();
        value.safety.emergencyState = state;
        assert.equal(normalizeAdvisorRuntimeResponse(value).safety.emergencyState, state);
    }
    for (const state of ["FRESH", "STALE", "UNKNOWN"]) {
        const value = fullResponse();
        value.runtime.freshness = state;
        assert.equal(normalizeAdvisorRuntimeResponse(value).runtime.freshness, state);
    }

    const unsupported = fullResponse();
    unsupported.bot.state = "STARTING";
    assert.equal(normalizeAdvisorRuntimeResponse(unsupported).bot.state, "UNKNOWN");
});

test("invalid warning entries are removed and represented by a contract warning", () => {
    const value = fullResponse();
    value.warnings = ["FIRST", { code: "RAW_OBJECT" }, null];

    assert.deepEqual(
        normalizeAdvisorRuntimeResponse(value).warnings,
        ["FIRST", "WARNINGS_INVALID"],
    );
});
