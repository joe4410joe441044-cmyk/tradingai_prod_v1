import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
    createOperationPreparationSettings,
    deriveOperationReadiness,
    operationPreparationSummary,
    resolveOperationDisplaySymbol,
} from "../components/operation/operationPreparationModel.js";

// Mirrors the Dashboard FINAL PREPARATION SYMBOL feed
// (frontend/src/pages/Dashboard.jsx). The Dashboard delegates to the single
// shared resolver, so Operation display, START readiness, the LIVE confirmation
// symbol, and the START payload bootstrap symbol all share one authority:
//
//   POST-START : canonical committed runtime symbol (activeSymbol) always wins.
//   PRE-START  : canonical active symbol wins when present; otherwise a fresh,
//                production-ready AUTO top candidate is the bootstrap symbol.
//   FAIL CLOSED: no valid authority -> "NOT AVAILABLE".
const evaluate = (botStatus, autoMarketState = "READY") => {
    const config = {
        mode: "PAPER",
        selectionMode: "AUTO",
        autoMarketState,
        displaySymbol: resolveOperationDisplaySymbol(botStatus),
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
    const summary = operationPreparationSummary(
        settings,
        readiness.selectedRuntimeSymbol,
        0.5,
    );
    return { config, settings, readiness, summary };
};

const stoppedAutoStatus = (overrides = {}) => ({
    status: "STOPPED",
    activeSymbol: null,
    autoMarketSelection: {
        activeSymbol: null,
        productionIntegration: { status: "READY" },
        topCandidate: { symbol: "SAGAUSDT" },
    },
    ...overrides,
});

test("Dashboard delegates the display/bootstrap symbol to the shared resolver", async () => {
    const dashboard = await readFile(
        new URL("./Dashboard.jsx", import.meta.url),
        "utf8",
    );
    assert.match(dashboard, /displaySymbol: resolveOperationDisplaySymbol\(botStatus\)/);
    assert.match(dashboard, /resolveOperationDisplaySymbol/);
    // No inline symbol derivation / competing symbol values inside BotControl's
    // config payload.
    assert.doesNotMatch(dashboard, /displaySymbol: botStatus\?\.autoMarketSelection\?\.topCandidate\?\.symbol/);
});

// CASE 1 / CASE 8 — restart-shaped STOPPED AUTO state: the canonical runtime
// symbol is null but a fresh, production-ready candidate exists. The candidate
// is the pre-start bootstrap/display symbol and START becomes READY.
test("CASE 1/8: STOPPED AUTO with a valid ready candidate unlocks START", () => {
    const { summary, readiness } = evaluate(stoppedAutoStatus());
    assert.equal(summary.symbol, "SAGAUSDT");
    assert.equal(readiness.selectedRuntimeSymbol, "SAGAUSDT");
    assert.equal(readiness.startReady, true);
});

// CASE A — candidate differs from the committed active symbol. The committed
// active symbol stays authoritative and must legitimately differ from the
// topCandidate.
test("CASE A: candidate differs from active symbol", () => {
    const botStatus = {
        status: "STOPPED",
        activeSymbol: "NOMUSDT",
        autoMarketSelection: {
            activeSymbol: "NOMUSDT",
            productionIntegration: { status: "READY" },
            topCandidate: { symbol: "C98USDT" },
        },
    };
    const { summary } = evaluate(botStatus);
    assert.equal(summary.symbol, "NOMUSDT");
    assert.notEqual(summary.symbol, botStatus.autoMarketSelection.topCandidate.symbol);
});

// CASE B — candidate changes without a committed safe switch. The active symbol
// and displayed FINAL PREPARATION SYMBOL must remain unchanged.
test("CASE B: candidate change without a committed switch does not move the active symbol", () => {
    const initial = {
        status: "STOPPED",
        activeSymbol: "NOMUSDT",
        autoMarketSelection: {
            activeSymbol: "NOMUSDT",
            productionIntegration: { status: "READY" },
            topCandidate: { symbol: "C98USDT" },
        },
    };
    const afterRankingUpdate = {
        status: "STOPPED",
        activeSymbol: "NOMUSDT",
        autoMarketSelection: {
            activeSymbol: "NOMUSDT",
            productionIntegration: { status: "READY" },
            topCandidate: { symbol: "PIXELUSDT" },
        },
    };
    assert.equal(evaluate(initial).summary.symbol, "NOMUSDT");
    assert.equal(evaluate(afterRankingUpdate).summary.symbol, "NOMUSDT");
});

// CASE C — committed safe switch. The active symbol and displayed SYMBOL both
// move to the newly committed symbol.
test("CASE C: committed safe switch drives the active symbol", () => {
    const afterSwitch = {
        status: "STOPPED",
        activeSymbol: "C98USDT",
        autoMarketSelection: {
            activeSymbol: "C98USDT",
            productionIntegration: { status: "READY" },
            topCandidate: { symbol: "C98USDT" },
        },
    };
    assert.equal(evaluate(afterSwitch).summary.symbol, "C98USDT");
});

// CASE 2 — candidate missing. START must fail closed.
test("CASE 2: STOPPED AUTO with a missing candidate fails closed", () => {
    const botStatus = stoppedAutoStatus();
    botStatus.autoMarketSelection.topCandidate = { symbol: null };
    const { summary, readiness } = evaluate(botStatus);
    assert.equal(summary.symbol, "AUTO SELECT");
    assert.equal(readiness.selectedRuntimeSymbol, null);
    assert.equal(readiness.startReady, false);
    assert.equal(resolveOperationDisplaySymbol(botStatus), "NOT AVAILABLE");
});

// CASE 3 / 29 — production integration not READY. A present candidate must NOT
// unlock START (the old AUTO READY false positive is not reintroduced).
test("CASE 3: production integration not READY does not unlock START", () => {
    const botStatus = stoppedAutoStatus();
    botStatus.autoMarketSelection.productionIntegration = { status: "BLOCKED" };
    const { summary, readiness } = evaluate(botStatus, "BLOCKED");
    assert.equal(summary.symbol, "AUTO SELECT");
    assert.equal(readiness.selectedRuntimeSymbol, null);
    assert.equal(readiness.startReady, false);
    assert.equal(resolveOperationDisplaySymbol(botStatus), "NOT AVAILABLE");
});

// CASE 4 — candidate blank. START must fail closed.
test("CASE 4: STOPPED AUTO with a blank candidate fails closed", () => {
    const botStatus = stoppedAutoStatus();
    botStatus.autoMarketSelection.topCandidate = { symbol: "   " };
    const { summary, readiness } = evaluate(botStatus);
    assert.equal(summary.symbol, "AUTO SELECT");
    assert.equal(readiness.startReady, false);
    assert.equal(resolveOperationDisplaySymbol(botStatus), "NOT AVAILABLE");
});

// CASE 6 — runtime active symbol present. The canonical committed symbol keeps
// priority over the candidate.
test("CASE 6: runtime active symbol keeps canonical priority", () => {
    const botStatus = stoppedAutoStatus({
        activeSymbol: "ETHUSDT",
    });
    assert.equal(resolveOperationDisplaySymbol(botStatus), "ETHUSDT");
    assert.equal(evaluate(botStatus).summary.symbol, "ETHUSDT");
});

// CASE 7 — post-START (RUNNING) the pre-start candidate must never be promoted
// to the runtime execution symbol when the canonical symbol is absent.
test("CASE 7: RUNNING without canonical symbol never promotes the candidate", () => {
    const botStatus = stoppedAutoStatus({ status: "RUNNING" });
    assert.equal(resolveOperationDisplaySymbol(botStatus), "NOT AVAILABLE");
    assert.equal(evaluate(botStatus).summary.symbol, "AUTO SELECT");
});

// MANUAL mode regression — the FINAL PREPARATION SYMBOL must continue to use
// the operator-selected manual symbol, independent of the active symbol feed.
test("MANUAL mode: operator symbol contract is preserved", () => {
    const config = {
        mode: "PAPER",
        selectionMode: "MANUAL",
        symbol: "ETHUSDTM",
        displaySymbol: resolveOperationDisplaySymbol(stoppedAutoStatus()),
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
    assert.equal(readiness.startReady, true);
});
