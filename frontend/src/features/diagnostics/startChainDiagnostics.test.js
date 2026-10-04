import assert from "node:assert/strict";
import test from "node:test";

import {
    getStartChainDiagnosticSnapshot,
    recordStartChainDiagnostic,
    resetStartChainDiagnosticsForTest,
    START_CHAIN_EVENTS,
} from "./startChainDiagnostics.js";

test("START diagnostics are ordered, bounded, sanitized, and browser-readable", () => {
    resetStartChainDiagnosticsForTest();
    recordStartChainDiagnostic(START_CHAIN_EVENTS.START_CLICK, {
        allowed: true,
        credential: { secret: "must-not-be-recorded" },
        outcome: "RECEIVED",
    });
    recordStartChainDiagnostic(START_CHAIN_EVENTS.LIVE_MODAL_OPEN, {
        outcome: "OPENED",
    });

    const snapshot = getStartChainDiagnosticSnapshot();
    assert.deepEqual(snapshot.map(({ event }) => event), [
        "START_CLICK",
        "LIVE_MODAL_OPEN",
    ]);
    assert.deepEqual(snapshot.map(({ sequence }) => sequence), [1, 2]);
    assert.equal(snapshot[0].allowed, true);
    assert.equal("credential" in snapshot[0], false);
    assert.equal(Number.isNaN(Date.parse(snapshot[0].timestamp)), false);
    assert.deepEqual(
        globalThis.__TRADINGAI_START_CHAIN_DIAGNOSTICS__.snapshot(),
        snapshot,
    );
});

test("unknown diagnostic events are ignored without throwing", () => {
    resetStartChainDiagnosticsForTest();
    assert.doesNotThrow(() => recordStartChainDiagnostic("NOT_ALLOWED", null));
    assert.deepEqual(getStartChainDiagnosticSnapshot(), []);
});
