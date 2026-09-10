import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
    createOperationPreparationSettings,
    deriveOperationReadiness,
    operationPreparationSummary,
} from "../components/operation/operationPreparationModel.js";

// Mirror of the Dashboard FINAL PREPARATION SYMBOL feed (frontend/src/pages/Dashboard.jsx):
// primary authority = botStatus.activeSymbol (canonical committed runtime symbol),
// AUTO consistency fallback = botStatus.autoMarketSelection.activeSymbol,
// fail closed to "NOT AVAILABLE" when the active authority is absent.
// topCandidate.symbol is NEVER promoted to the active symbol.
const dashboardDisplaySymbol = (botStatus) => (
    botStatus?.activeSymbol
    ?? botStatus?.autoMarketSelection?.activeSymbol
    ?? "NOT AVAILABLE"
);

const summarySymbolFor = (botStatus, autoMarketState = "READY") => {
    const config = {
        mode: "PAPER",
        selectionMode: "AUTO",
        autoMarketState,
        displaySymbol: dashboardDisplaySymbol(botStatus),
    };
    const settings = createOperationPreparationSettings(config);
    const readiness = deriveOperationReadiness({
        botRunning: false,
        tradingMode: settings.tradingMode,
        dryRun: true,
        selectionMode: settings.selectionMode,
        autoMarketState: config.autoMarketState,
        displaySymbol: config.displaySymbol,
        emergencyState: "READY",
        position: "FLAT",
        pendingOrder: false,
        governanceStatus: "READY",
        realOrderAllowed: false,
        executionEnabled: false,
        executionEntryAllowed: false,
        recommendedAction: "HOLD_NEW_ENTRIES",
        riskState: "SAFE",
        requestedLeverage: settings.requestedLeverage,
        maximumLeverage: 5,
        mmConfiguration: {
            riskPerTradePercent: 0.5,
            totalExposurePercent: 20,
            maximumDrawdownPercent: 7,
            maximumLeverage: 5,
        },
        allowLive: false,
        tradeMode: "paper",
    });
    return operationPreparationSummary(
        settings,
        readiness.selectedRuntimeSymbol,
        0.5,
    ).symbol;
};

test("Dashboard SYMBOL uses the canonical active symbol, never the top candidate", async () => {
    const dashboard = await readFile(
        new URL("./Dashboard.jsx", import.meta.url),
        "utf8",
    );
    assert.match(dashboard, /displaySymbol: botStatus\?\.activeSymbol/);
    assert.doesNotMatch(dashboard, /displaySymbol: botStatus\?\.autoMarketSelection\?\.topCandidate\?\.symbol/);
});

// CASE A — candidate differs from the active symbol. The FINAL PREPARATION
// SYMBOL must be the committed active symbol, and must legitimately differ
// from topCandidate.
test("CASE A: candidate differs from active symbol", () => {
    const botStatus = {
        activeSymbol: "NOMUSDT",
        autoMarketSelection: {
            activeSymbol: "NOMUSDT",
            topCandidate: { symbol: "C98USDT" },
        },
    };
    const summarySymbol = summarySymbolFor(botStatus);
    assert.equal(summarySymbol, "NOMUSDT");
    assert.notEqual(summarySymbol, botStatus.autoMarketSelection.topCandidate.symbol);
});

// CASE B — candidate changes without a committed safe switch. The active
// symbol and the displayed FINAL PREPARATION SYMBOL must remain unchanged.
test("CASE B: candidate change without a committed switch does not move the active symbol", () => {
    const initial = {
        activeSymbol: "NOMUSDT",
        autoMarketSelection: {
            activeSymbol: "NOMUSDT",
            topCandidate: { symbol: "C98USDT" },
        },
    };
    const afterRankingUpdate = {
        activeSymbol: "NOMUSDT",
        autoMarketSelection: {
            activeSymbol: "NOMUSDT",
            topCandidate: { symbol: "PIXELUSDT" },
        },
    };
    assert.equal(summarySymbolFor(initial), "NOMUSDT");
    assert.equal(summarySymbolFor(afterRankingUpdate), "NOMUSDT");
});

// CASE C — committed safe switch. The active symbol and displayed SYMBOL both
// move to the newly committed symbol.
test("CASE C: committed safe switch drives the active symbol", () => {
    const afterSwitch = {
        activeSymbol: "C98USDT",
        autoMarketSelection: {
            activeSymbol: "C98USDT",
            topCandidate: { symbol: "C98USDT" },
        },
    };
    assert.equal(summarySymbolFor(afterSwitch), "C98USDT");
});

// CASE D — missing active authority. Must fail closed (never display the
// top candidate as the active symbol).
test("CASE D: missing active authority fails closed without promoting the top candidate", () => {
    const botStatus = {
        activeSymbol: null,
        autoMarketSelection: {
            activeSymbol: null,
            topCandidate: { symbol: "C98USDT" },
        },
    };
    const summarySymbol = summarySymbolFor(botStatus);
    assert.notEqual(summarySymbol, "C98USDT");
    assert.equal(summarySymbol, "AUTO SELECT");
    // The fail-closed sentinel feeds the readiness model; it is never treated
    // as a real runtime symbol.
    assert.equal(dashboardDisplaySymbol(botStatus), "NOT AVAILABLE");
});

// MANUAL mode regression — the FINAL PREPARATION SYMBOL must continue to use
// the operator-selected manual symbol, independent of the active symbol feed.
test("MANUAL mode: operator symbol contract is preserved", () => {
    const config = {
        mode: "PAPER",
        selectionMode: "MANUAL",
        symbol: "ETHUSDTM",
        displaySymbol: "NOMUSDT",
    };
    const settings = createOperationPreparationSettings(config);
    const readiness = deriveOperationReadiness({
        botRunning: false,
        tradingMode: settings.tradingMode,
        dryRun: true,
        selectionMode: settings.selectionMode,
        autoMarketState: "NOT AVAILABLE",
        displaySymbol: config.displaySymbol,
        emergencyState: "READY",
        position: "FLAT",
        pendingOrder: false,
        governanceStatus: "READY",
        realOrderAllowed: false,
        executionEnabled: false,
        executionEntryAllowed: false,
        recommendedAction: "HOLD_NEW_ENTRIES",
        riskState: "SAFE",
        requestedLeverage: settings.requestedLeverage,
        maximumLeverage: 5,
        mmConfiguration: {
            riskPerTradePercent: 0.5,
            totalExposurePercent: 20,
            maximumDrawdownPercent: 7,
            maximumLeverage: 5,
        },
        allowLive: false,
        tradeMode: "paper",
    });
    const summary = operationPreparationSummary(
        settings,
        readiness.selectedRuntimeSymbol,
        0.5,
    );
    assert.equal(summary.symbol, "ETHUSDTM");
});
