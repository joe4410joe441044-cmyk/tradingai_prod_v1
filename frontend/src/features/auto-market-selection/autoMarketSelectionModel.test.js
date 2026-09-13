import assert from "node:assert/strict";
import test from "node:test";

import { buildAutoMarketSelectionModel, buildAutoMarketSelectionReasons, displayAmsValue } from "./autoMarketSelectionModel.js";

test("active symbol never falls back to requested symbol or top candidate", () => {
    const status = { selectionMode: "MANUAL", activeSymbol: "ETHUSDT",
        requestedSymbol: "SOLUSDT", topCandidate: { symbol: "BTCUSDT" } };
    const first = buildAutoMarketSelectionModel(status, "XRPUSDT");
    assert.equal(first.activeSymbol, "ETHUSDT");
    assert.equal(first.requestedSymbol, "XRPUSDT");
    assert.equal(first.topCandidate.symbol, "BTCUSDT");
    const missing = buildAutoMarketSelectionModel({ ...status, activeSymbol: null }, "XRPUSDT");
    assert.equal(missing.activeSymbol, null);
});

test("API unavailable and null values render without fake zero", () => {
    const model = buildAutoMarketSelectionModel(null, "BTCUSDT");
    assert.equal(model.availability, "UNAVAILABLE");
    assert.equal(model.scanner.status, "UNAVAILABLE");
    assert.equal(displayAmsValue(null), "—");
    assert.equal(displayAmsValue(0), "0");
});

test("failed, stale, no-eligible and no-rankable states remain intact", () => {
    const status = { scanner: { status: "NO_ELIGIBLE_MARKET" },
        ranking: { status: "NO_RANKABLE_MARKET" }, switch: { state: "FAILED" },
        freshness: { scanner: "STALE" } };
    const model = buildAutoMarketSelectionModel(status);
    assert.equal(model.scanner.status, "NO_ELIGIBLE_MARKET");
    assert.equal(model.ranking.status, "NO_RANKABLE_MARKET");
    assert.equal(model.switch.state, "FAILED");
    assert.equal(model.freshness.scanner, "STALE");
});

test("historical last-cycle reasons never leak into current snapshot reasons", () => {
    const model = buildAutoMarketSelectionModel({
        activeSymbol: "XRPUSDTM",
        topCandidate: { symbol: "ETHUSDT" },
        autoRuntime: {
            mode: "AUTO_PAPER", runtimeState: "OBSERVING", status: "IDLE", cycleId: null,
            lastCycleStatus: "COMPLETED_BLOCKED", lastCycleId: "ams-cycle-9",
            reasonCodes: ["MM_STALE", "ELIGIBILITY_STALE", "CAPITAL_INELIGIBLE"],
        },
        switch: { state: "IDLE", reasonCodes: [] },
        reasons: [],
        capitalEligibility: { status: "ELIGIBLE", mmRegime: "FRESH" },
        freshness: { mm: "FRESH" },
    });
    const reasons = buildAutoMarketSelectionReasons(model);
    assert.deepEqual(reasons.historical, ["MM_STALE", "ELIGIBILITY_STALE", "CAPITAL_INELIGIBLE"]);
    assert.deepEqual(reasons.current, []);
    assert.equal(model.autoRuntime.lastCycleStatus, "COMPLETED_BLOCKED");
    assert.equal(model.autoRuntime.lastCycleId, "ams-cycle-9");
    // current snapshot semantics are untouched by historical reasons
    assert.equal(model.capitalEligibility.status, "ELIGIBLE");
    assert.equal(model.freshness.mm, "FRESH");
});

test("current switch and snapshot reasons stay distinct from historical reasons", () => {
    const model = buildAutoMarketSelectionModel({
        autoRuntime: { status: "IDLE", reasonCodes: ["MM_STALE"] },
        switch: { state: "IDLE", reasonCodes: ["POSITION_NOT_FLAT"] },
        reasons: ["NO_ELIGIBLE_MARKET", "POSITION_NOT_FLAT"],
    });
    const reasons = buildAutoMarketSelectionReasons(model);
    assert.deepEqual(reasons.historical, ["MM_STALE"]);
    assert.deepEqual(reasons.current, ["POSITION_NOT_FLAT", "NO_ELIGIBLE_MARKET"]);
});

test("missing last-cycle payload stays explicit instead of inferred", () => {
    const model = buildAutoMarketSelectionModel({ activeSymbol: "BTCUSDT" });
    assert.equal(model.autoRuntime.lastCycleStatus, null);
    assert.equal(model.autoRuntime.lastCycleId, null);
});

test("active symbol and top candidate preview keep separate authority", () => {
    const model = buildAutoMarketSelectionModel({
        selectionMode: "AUTO", activeSymbol: "XRPUSDTM",
        requestedSymbol: "SOLUSDT", topCandidate: { symbol: "ETHUSDT" },
    });
    assert.equal(model.activeSymbol, "XRPUSDTM");
    assert.equal(model.requestedSymbol, "SOLUSDT");
    assert.equal(model.topCandidate.symbol, "ETHUSDT");
    assert.notEqual(model.activeSymbol, model.topCandidate.symbol);
});

test("model is read-only and contains no action surface", () => {
    const model = buildAutoMarketSelectionModel({ activeSymbol: "BTCUSDT" });
    assert.equal(model.commitActiveSymbol, undefined);
    assert.equal(model.createOrder, undefined);
    assert.equal(model.enableLive, undefined);
});

test("AUTO Paper cycle status remains visible without an action surface", () => {
    const model = buildAutoMarketSelectionModel({
        autoRuntime: { mode: "AUTO_PAPER", runtimeState: "READY", status: "SWITCH_BLOCKED",
            cycleId: "ams-4a-cycle", evaluatedAt: "2026-08-09T03:00:00Z",
            reasonCodes: ["POSITION_NOT_FLAT"] },
    });
    assert.equal(model.autoRuntime.mode, "AUTO_PAPER");
    assert.equal(model.autoRuntime.runtimeState, "READY");
    assert.equal(model.autoRuntime.status, "SWITCH_BLOCKED");
    assert.deepEqual(model.autoRuntime.reasonCodes, ["POSITION_NOT_FLAT"]);
    assert.equal(model.startAuto, undefined);
});
