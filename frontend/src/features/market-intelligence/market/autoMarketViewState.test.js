import test from "node:test";
import assert from "node:assert/strict";

import { projectAutoMarketViewState } from "./autoMarketViewState.js";

const market = (status = "READY", symbol = "BTCUSDT") => ({
    status,
    context: { normalizedSymbol: symbol },
});
const selection = ({
    activeSymbol = "BTCUSDT",
    cycle = "IDLE",
    lifecycle = "RUNNING",
    mode = "AUTO",
    switching = "IDLE",
} = {}) => ({
    activeSymbol,
    selectionMode: mode,
    autoRuntime: { runtimeState: lifecycle, status: cycle },
    switch: { state: switching },
});
const project = (status, model = market()) => projectAutoMarketViewState({
    contextMode: "LIVE",
    marketModel: model,
    selectionStatus: status,
});

test("AUTO lifecycle and safe-switch states project to Market View states", () => {
    assert.equal(project(selection({ lifecycle: "RUNNING_CYCLE" })), "SELECTING");
    assert.equal(project(selection({ cycle: "EVALUATING" })), "SELECTING");
    for (const switching of ["PREPARING", "COMMITTING", "CLEANUP", "IN_PROGRESS"])
        assert.equal(project(selection({ switching })), "SWITCHING");
    for (const switching of ["SUBSCRIBING", "VALIDATING"])
        assert.equal(project(selection({ switching })), "CONNECTING");
    assert.equal(project(selection()), "READY");
});

test("READY requires valid data for the authoritative active symbol", () => {
    assert.equal(project(selection({ activeSymbol: "ETHUSDT" }), market("READY", "ETHUSDT")), "READY");
    assert.equal(project(selection({ activeSymbol: "BTCUSDT" }), market("WAITING", "BTCUSDT")), "WAITING");
    assert.equal(project(selection({ activeSymbol: "BTCUSDT" }), market("READY", "ETHUSDT")), "WAITING");
    assert.equal(project(selection({ activeSymbol: null, lifecycle: "READY" }), market()), "SELECTING");
    assert.equal(project(selection({ activeSymbol: null, lifecycle: "STOPPED" }), market("WAITING")), "WAITING");
});

test("failures and unsafe market data are never hidden by transient states", () => {
    assert.equal(project(selection({ lifecycle: "BLOCKED" })), "BLOCKED");
    assert.equal(project(selection({ switching: "FAILED" })), "FAILED");
    assert.equal(project(selection({ cycle: "NO_ELIGIBLE_MARKET" })), "NO_ELIGIBLE_MARKET");
    assert.equal(project(selection({ switching: "VALIDATING" }), market("STALE")), "STALE");
    assert.equal(project(selection({ switching: "SUBSCRIBING" }), market("INVALID")), "INVALID");
});

test("MANUAL and Replay keep their existing market presentation state", () => {
    assert.equal(project(selection({ mode: "MANUAL", switching: "VALIDATING" }), market("WAITING")), "WAITING");
    assert.equal(projectAutoMarketViewState({
        contextMode: "REPLAY",
        marketModel: market("READY"),
        selectionStatus: selection({ lifecycle: "RUNNING_CYCLE" }),
    }), null);
});
