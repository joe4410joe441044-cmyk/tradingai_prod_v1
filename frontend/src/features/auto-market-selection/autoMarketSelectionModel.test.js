import assert from "node:assert/strict";
import test from "node:test";

import { buildAutoMarketSelectionModel, displayAmsValue } from "./autoMarketSelectionModel.js";

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
