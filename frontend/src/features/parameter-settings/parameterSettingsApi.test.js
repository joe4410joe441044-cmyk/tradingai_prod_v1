import assert from "node:assert/strict";
import test from "node:test";

import { getParameterSettingsPerformance } from "./parameterSettingsApi.js";


test("parameter performance request is revision-scoped", async () => {
    const calls = [];
    const original = globalThis.fetch;
    globalThis.fetch = async (url) => {
        calls.push(String(url));
        return { ok: true, status: 200, json: async () => ({}) };
    };
    try {
        await getParameterSettingsPerformance("PAPER", 3);
        assert.equal(calls.length, 1);
        assert.match(calls[0], /scope=PAPER/);
        assert.match(calls[0], /revision=3/);

        // No revision selection must not fabricate a revision filter.
        await getParameterSettingsPerformance("PAPER", null);
        assert.match(calls[1], /scope=PAPER/);
        assert.doesNotMatch(calls[1], /revision=/);
    } finally {
        globalThis.fetch = original;
    }
});
