import assert from "node:assert/strict";
import test from "node:test";

import {
    performSaveSettings,
    SAVE_SETTINGS_CODES,
} from "./saveSettings.js";

test("PAPER save validates and does NOT refresh LIVE account context", async () => {
    let refreshed = false;
    const result = await performSaveSettings({
        draft: { mode: "PAPER", symbol: "XRPUSDTM" },
        refreshLiveContext: async () => { refreshed = true; },
    });
    assert.equal(result.ok, true);
    assert.equal(refreshed, false, "PAPER save must not read the LIVE account context");
});

test("LIVE save refreshes the authoritative LIVE account context (read-only)", async () => {
    let refreshed = 0;
    const result = await performSaveSettings({
        draft: { mode: "LIVE", symbol: "XRPUSDTM" },
        refreshLiveContext: async () => { refreshed += 1; },
    });
    assert.equal(result.ok, true);
    assert.equal(refreshed, 1);
});

test("LIVE save with a failed context refresh fails closed and does NOT succeed", async () => {
    const result = await performSaveSettings({
        draft: { mode: "LIVE", symbol: "XRPUSDTM" },
        refreshLiveContext: async () => {
            throw new Error("network down");
        },
    });
    assert.equal(result.ok, false);
    assert.equal(result.code, SAVE_SETTINGS_CODES.LIVE_ACCOUNT_CONTEXT_UNAVAILABLE);
});

test("invalid mode and empty symbol fail validation", async () => {
    let refreshed = false;
    const badMode = await performSaveSettings({
        draft: { mode: "REAL", symbol: "XRPUSDTM" },
        refreshLiveContext: async () => { refreshed = true; },
    });
    assert.equal(badMode.ok, false);
    assert.equal(badMode.code, SAVE_SETTINGS_CODES.INVALID_MODE);

    const badSymbol = await performSaveSettings({
        draft: { mode: "PAPER", symbol: "" },
        refreshLiveContext: async () => { refreshed = true; },
    });
    assert.equal(badSymbol.ok, false);
    assert.equal(badSymbol.code, SAVE_SETTINGS_CODES.INVALID_SYMBOL);
    assert.equal(refreshed, false);
});

test("SAVE SETTINGS never mutates runtime or orders: only the injected read may run", async () => {
    // The save core has exactly one injected dependency (the read-only LIVE
    // context refresh). There is no runtime-start, arm, order, cancel, or
    // position-mutation path in this module, so a successful save can only
    // invoke that single read.
    let reads = 0;
    const result = await performSaveSettings({
        draft: { mode: "LIVE", symbol: "XRPUSDTM" },
        refreshLiveContext: async () => { reads += 1; },
    });
    assert.equal(result.ok, true);
    assert.equal(reads, 1);
});
