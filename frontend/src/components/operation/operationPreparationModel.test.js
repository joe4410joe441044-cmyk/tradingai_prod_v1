import assert from "node:assert/strict";
import test from "node:test";

import {
    deriveOperationReadiness,
    pendingOrderAuthorityValue,
} from "./operationPreparationModel.js";

const readyInputs = (overrides = {}) => ({
    botRunning: false,
    tradingMode: "PAPER",
    dryRun: true,
    selectionMode: "MANUAL",
    emergencyState: "READY",
    position: "FLAT",
    pendingOrder: false,
    governanceStatus: "READY",
    realOrderAllowed: false,
    executionEnabled: false,
    executionEntryAllowed: true,
    recommendedAction: "CONTINUE",
    riskState: "NORMAL",
    requestedLeverage: 3,
    maximumLeverage: 5,
    mmConfiguration: {
        riskPerTradePercent: "0.50",
        totalExposurePercent: "20",
        maximumDrawdownPercent: "5",
        maximumLeverage: "5",
    },
    ...overrides,
});

for (const [name, requestedLeverage, maximumLeverage, expected] of [
    ["requested 3 / maximum 5 allows", 3, 5, "READY"],
    ["requested 5 / maximum 5 allows", 5, 5, "READY"],
    ["requested 7 / maximum 5 blocks", 7, 5, "BLOCKED"],
    ["zero requested blocks", 0, 5, "BLOCKED"],
    ["negative requested blocks", -1, 5, "BLOCKED"],
    ["malformed requested blocks", "invalid", 5, "BLOCKED"],
    ["non-finite requested blocks", Infinity, 5, "BLOCKED"],
    ["missing maximum blocks", 3, undefined, "BLOCKED"],
    ["malformed maximum blocks", 3, "invalid", "BLOCKED"],
    ["non-finite maximum blocks", 3, Infinity, "BLOCKED"],
]) {
    test(name, () => {
        const result = deriveOperationReadiness(readyInputs({
            requestedLeverage,
            maximumLeverage,
        }));
        assert.equal(result.leverageReadiness, expected);
        assert.equal(result.reviewReadiness, expected);
    });
}

test("PAPER stopped runtime-only MM unavailability permits START but not entry", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        recommendedAction: "UNKNOWN",
        riskState: "UNKNOWN",
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
    }));
    assert.equal(result.stoppedPaperRuntimeMetricsOnly, true);
    assert.equal(result.startReady, true);
    assert.equal(result.entryReady, false);
    assert.equal(result.entryReadiness, "WAITING");
});

test("PAPER stopped recovery remains an entry guard, not a BOT START guard", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        recommendedAction: "UNKNOWN",
        riskState: "UNKNOWN",
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        mmRecoveryRequired: true,
    }));
    assert.equal(result.startMmReadiness, "READY");
    assert.equal(result.startReady, true);
    assert.equal(result.entryReadiness, "WAITING");
    assert.equal(result.entryReady, false);
});

test("AUTO pre-start rejects a stale candidate while runtime is not ready", () => {
    const result = deriveOperationReadiness(readyInputs({
        selectionMode: "AUTO",
        autoMarketState: "OBSERVING",
        displaySymbol: "YGGUSDT",
    }));
    assert.equal(result.selectedRuntimeSymbol, null);
    assert.equal(result.selectionReadiness, "OBSERVING");
    assert.equal(result.startReady, false);
});

test("AUTO pre-start accepts the formal candidate only while runtime is ready", () => {
    const result = deriveOperationReadiness(readyInputs({
        selectionMode: "AUTO",
        autoMarketState: "READY",
        displaySymbol: "YGGUSDT",
    }));
    assert.equal(result.selectedRuntimeSymbol, "YGGUSDT");
    assert.equal(result.selectionReadiness, "READY");
    assert.equal(result.startReady, true);
});

test("typed pending authority distinguishes stale projection from known pending", () => {
    assert.equal(pendingOrderAuthorityValue({
        pendingOrder: true,
        pendingOrderState: { known: false, pending: null },
    }), null);
    assert.equal(pendingOrderAuthorityValue({
        pendingOrder: true,
        pendingOrderState: { known: true, pending: true },
    }), true);
    assert.equal(pendingOrderAuthorityValue({ pendingOrder: false }), false);
});

for (const [name, overrides] of [
    ["Pending exists", { pendingOrder: true }],
    ["Position OPEN", { position: "OPEN" }],
    ["Emergency unsafe", { emergencyState: "LOCKED" }],
    ["saved MM invalid", { mmConfiguration: { maximumLeverage: 5 } }],
    ["leverage over maximum", { requestedLeverage: 7 }],
]) {
    test(`${name} blocks PAPER START`, () => {
        const result = deriveOperationReadiness(readyInputs({
            executionEntryAllowed: false,
            mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
            ...overrides,
        }));
        assert.equal(result.startReady, false);
    });
}

test("Pending UNKNOWN allows PAPER bootstrap with backend authority", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        pendingOrder: null,
        paperBootstrapEligible: true,
    }));
    assert.equal(result.startReady, true);
});

test("Position UNKNOWN allows PAPER bootstrap with backend authority", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: null,
        paperBootstrapEligible: true,
    }));
    assert.equal(result.startReady, true);
});

test("STOPPED PAPER bootstrap allows START with runtime-only unknowns", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: null,
        pendingOrder: null,
        paperBootstrapEligible: true,
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.entryReady, false);
    assert.equal(result.entryReadiness, "WAITING");
});

test("STOPPED PAPER bootstrap still blocks entry permission", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: null,
        pendingOrder: null,
        paperBootstrapEligible: true,
    }));
    assert.equal(result.entryReady, false);
    assert.equal(result.entryReadiness, "WAITING");
    assert.equal(result.startReady, true);
});

test("STOPPED PAPER bootstrap blocks on known position", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: "OPEN",
        paperBootstrapEligible: true,
    }));
    assert.equal(result.startReady, false);
});

test("STOPPED PAPER bootstrap blocks on known pending order", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        pendingOrder: true,
        paperBootstrapEligible: true,
    }));
    assert.equal(result.startReady, false);
});

test("paperBootstrapEligible=false blocks START with UNKNOWN position/order", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: null,
        pendingOrder: null,
        paperBootstrapEligible: false,
    }));
    assert.equal(result.startReady, false);
});

test("missing paperBootstrapEligible blocks START with UNKNOWN position/order", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: null,
        pendingOrder: null,
    }));
    assert.equal(result.startReady, false);
});

test("LIVE bootstrap prohibits START with unknown runtime authority", () => {
    const result = deriveOperationReadiness(readyInputs({
        tradingMode: "LIVE",
        dryRun: false,
        realOrderAllowed: true,
        allowLive: false,
        tradeMode: "paper",
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.liveAuthorityReadiness, "BLOCKED");
});

test("LIVE bootstrap allows START only when ALLOW_LIVE and TRADE_MODE=live", () => {
    const result = deriveOperationReadiness(readyInputs({
        tradingMode: "LIVE",
        dryRun: false,
        realOrderAllowed: true,
        allowLive: true,
        tradeMode: "live",
    }));
    assert.equal(result.liveAuthorityReadiness, "READY");
});

test("START after STOP confirms safe state restoration", () => {
    const result = deriveOperationReadiness(readyInputs({
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
        position: null,
        pendingOrder: null,
        paperBootstrapEligible: true,
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.executionReadiness, "SAFE");
    assert.equal(result.emergencyReadiness, "READY");
});

test("Max Drawdown regression: saved config matches readiness", () => {
    const result = deriveOperationReadiness(readyInputs({
        mmConfiguration: {
            riskPerTradePercent: "0.50",
            totalExposurePercent: "20",
            maximumDrawdownPercent: "5",
            maximumLeverage: "5",
        },
    }));
    assert.equal(result.savedMmReadiness, "READY");
    assert.equal(result.startMmReadiness, "READY");
});

test("Max Drawdown regression: missing field blocks", () => {
    const result = deriveOperationReadiness(readyInputs({
        mmConfiguration: {
            riskPerTradePercent: "0.50",
            totalExposurePercent: "20",
            maximumLeverage: "5",
        },
    }));
    assert.equal(result.savedMmReadiness, "BLOCKED");
    assert.equal(result.startMmReadiness, "BLOCKED");
});

test("running runtime authority allows entry only with MM and execution authority", () => {
    const allowed = deriveOperationReadiness(readyInputs({
        botRunning: true,
        executionEnabled: true,
    }));
    assert.equal(allowed.entryReady, true);

    const blocked = deriveOperationReadiness(readyInputs({
        botRunning: true,
        executionEnabled: true,
        executionEntryAllowed: false,
        recommendedAction: "BLOCK_EXECUTION",
        riskState: "LOCKED",
        mmBlockReasons: ["DAILY_LOSS_LIMIT"],
    }));
    assert.equal(blocked.entryReady, false);
});

test("runtime-only exception is PAPER pre-start only", () => {
    const inputs = {
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
    };
    assert.equal(deriveOperationReadiness(readyInputs({
        ...inputs, tradingMode: "LIVE", dryRun: false, realOrderAllowed: true,
    })).startReady, false);
    assert.equal(deriveOperationReadiness(readyInputs({
        ...inputs, mmRecoveryRequired: true,
    })).startReady, true);
    assert.equal(deriveOperationReadiness(readyInputs({
        ...inputs, mmBlockReasons: [
            "TRADING_RUNTIME_METRICS_UNAVAILABLE",
            "MM_CONFIGURATION_INVALID",
        ],
    })).startReady, false);
});


test("LIVE DISARMED runtime readiness does not require order-entry permission", () => {
    const result = deriveOperationReadiness(readyInputs({
        tradingMode: "LIVE",
        dryRun: false,
        allowLive: true,
        tradeMode: "live",
        realOrderAllowed: false,
        executionEnabled: false,
        executionEntryAllowed: false,
        loopOnStart: false,
        autoTradeOnStart: false,
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.liveAuthorityReadiness, "READY");
    assert.equal(result.liveAutomationReadiness, "READY");
    assert.equal(result.executionReadiness, "SAFE");
});

test("LIVE DISARMED runtime readiness blocks Loop or Auto intent", () => {
    const result = deriveOperationReadiness(readyInputs({
        tradingMode: "LIVE",
        dryRun: false,
        allowLive: true,
        tradeMode: "live",
        realOrderAllowed: false,
        executionEnabled: false,
        loopOnStart: true,
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.liveAutomationReadiness, "BLOCKED");
});

test("CASE 9: RUNNING bot with active execution stays fail-closed (START not made available)", () => {
    // A RUNNING bot with execution enabled must NOT report START ready; the
    // pre-start readiness semantics are unchanged by the presentation-only
    // RUNNING neutralization.
    const running = deriveOperationReadiness(readyInputs({
        botRunning: true,
        executionEnabled: true,
    }));
    assert.equal(running.startReady, false);
    assert.equal(running.startReadiness, "BLOCKED");
    assert.equal(running.executionReadiness, "BLOCKED");

    // SAFE state (execution disabled, running) keeps the normal gate.
    const idling = deriveOperationReadiness(readyInputs({
        botRunning: true,
        executionEnabled: false,
        realOrderAllowed: false,
    }));
    assert.equal(idling.executionReadiness, "SAFE");
});
