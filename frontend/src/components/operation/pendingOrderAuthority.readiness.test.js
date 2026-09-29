import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
    createOperationPreparationSettings,
    deriveOperationReadiness,
} from "./operationPreparationModel.js";
import { deriveOperationBlockGuidance } from "./operationPreparationGuidance.js";

// REAL-004: FINAL PREPARATION / START guard visibility contract.
//
// The observed defect: with a saved LIVE next-start intent and a stopped PAPER
// runtime, Pending Order Authority was UNKNOWN and LIVE AUTHORITY was BLOCKED,
// but only one of the two blockers was explained. These tests pin the repaired
// contract: every guard that contributes to the BLOCKED summary is visible, and
// the next-start mode is never coerced.

const BLOCKED_VALUES = new Set([
    "BLOCKED",
    "ERROR",
    "FAILED",
    "LOCKED",
    "UNAVAILABLE",
    "UNKNOWN",
]);

const baseInputs = (overrides = {}) => ({
    botRunning: false,
    tradingMode: "LIVE",
    dryRun: false,
    selectionMode: "MANUAL",
    emergencyState: "READY",
    position: "FLAT",
    pendingOrder: false,
    governanceStatus: "READY",
    realOrderAllowed: false,
    executionEnabled: false,
    executionEntryAllowed: false,
    recommendedAction: "UNKNOWN",
    riskState: "UNKNOWN",
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

const guidanceFor = (readiness, inputs) => deriveOperationBlockGuidance({
    settings: {
        requestedLeverage: inputs.requestedLeverage,
        selectionMode: inputs.selectionMode,
        loopOnStart: inputs.loopOnStart,
        autoTradeOnStart: inputs.autoTradeOnStart,
    },
    config: {
        allowLive: inputs.allowLive,
        tradeMode: inputs.tradeMode,
        displaySymbol: "XRPUSDTM",
    },
    emergencyReadiness: readiness.emergencyReadiness,
    positionState: readiness.positionState,
    orderAuthority: readiness.orderAuthority,
    selectionReadiness: readiness.selectionReadiness,
    selectionRuntime: readiness.selectionRuntime,
    selectedRuntimeSymbol: readiness.selectedRuntimeSymbol,
    startMmReadiness: readiness.startMmReadiness,
    executionReadiness: readiness.executionReadiness,
    leverageReadiness: readiness.leverageReadiness,
    liveAuthorityReadiness: readiness.liveAuthorityReadiness,
    liveAutomationReadiness: readiness.liveAutomationReadiness,
    emergencyState: inputs.emergencyState,
    position: inputs.position,
    pendingOrder: inputs.pendingOrder,
    realOrderAllowed: inputs.realOrderAllowed,
    executionEnabled: inputs.executionEnabled,
    mmConfiguration: inputs.mmConfiguration,
    mmDraft: { riskPerTradePercent: "0.50", maximumDrawdownPercent: "5" },
});

const blockedCount = (readiness) => (
    readiness.startReadinessValues.filter((value) => BLOCKED_VALUES.has(value)).length
);

test("TEST A: saved LIVE + stopped PAPER runtime uses the correct source per guard", () => {
    const inputs = baseInputs({ allowLive: false, tradeMode: "paper" });
    const readiness = deriveOperationReadiness(inputs);

    // Next-start intent is LIVE -> the LIVE authority prerequisite is evaluated.
    assert.equal(readiness.liveAuthorityReadiness, "BLOCKED");
    // Current runtime execution authority (disabled) is NOT the next-start mode.
    assert.equal(readiness.executionReadiness, "SAFE");
    // Pending-order authority comes from authoritative pendingOrder evidence.
    assert.equal(readiness.orderAuthority, "SAFE");
    assert.equal(readiness.startReady, false);
});

test("TEST B: legitimate LIVE authority BLOCKED appears in count, guidance and details", async () => {
    const inputs = baseInputs({ allowLive: false, tradeMode: "paper" });
    const readiness = deriveOperationReadiness(inputs);
    const guidance = guidanceFor(readiness, inputs);

    assert.equal(blockedCount(readiness), 1);
    assert.equal(readiness.startReadiness, "BLOCKED");
    const entry = guidance.find((item) => item.id === "liveAuthority");
    assert.ok(entry, "LIVE authority guidance present");
    assert.equal(entry.status, "BLOCKED");

    const source = await readFile(new URL("./OperationPreparation.jsx", import.meta.url), "utf8");
    assert.match(source, /label: "LIVE Authority/);
    assert.match(source, /liveAuthorityReadiness/);
});

test("TEST C: two blocked guards render exactly two visible explanations", () => {
    const inputs = baseInputs({ pendingOrder: null, allowLive: false, tradeMode: "paper" });
    const readiness = deriveOperationReadiness(inputs);
    const guidance = guidanceFor(readiness, inputs);

    assert.equal(blockedCount(readiness), 2);
    assert.equal(guidance.length, 2);
    assert.deepEqual(
        guidance.map((item) => item.id).sort(),
        ["liveAuthority", "pendingOrder"],
    );
});

test("TEST D: no hidden blocker (visible guidance == blocked summary)", () => {
    const inputs = baseInputs({ pendingOrder: null, allowLive: false, tradeMode: "paper" });
    const readiness = deriveOperationReadiness(inputs);
    const guidance = guidanceFor(readiness, inputs);

    assert.equal(guidance.length, blockedCount(readiness));
});

test("TEST E: Pending Order Authority UNKNOWN remains visibly UNKNOWN", () => {
    const inputs = baseInputs({ pendingOrder: null, allowLive: true, tradeMode: "live" });
    const readiness = deriveOperationReadiness(inputs);
    const guidance = guidanceFor(readiness, inputs);

    assert.equal(readiness.orderAuthority, "UNKNOWN");
    const entry = guidance.find((item) => item.id === "pendingOrder");
    assert.ok(entry, "pending order guidance present");
    assert.equal(entry.status, "UNKNOWN");
});

test("TEST F: Pending Order Authority is SAFE only with verified authority", () => {
    const verifiedInputs = baseInputs({ pendingOrder: false });
    const verified = deriveOperationReadiness(verifiedInputs);
    assert.equal(verified.orderAuthority, "SAFE");
    assert.equal(
        guidanceFor(verified, verifiedInputs).find((item) => item.id === "pendingOrder"),
        undefined,
    );

    const unknownInputs = baseInputs({ pendingOrder: null });
    const unknown = deriveOperationReadiness(unknownInputs);
    assert.equal(unknown.orderAuthority, "UNKNOWN");
    assert.ok(
        guidanceFor(unknown, unknownInputs).find((item) => item.id === "pendingOrder"),
    );
});

test("TEST G: saved LIVE intent stays LIVE for the next-start request", () => {
    const inputs = baseInputs({ allowLive: false, tradeMode: "paper" });
    const readiness = deriveOperationReadiness(inputs);
    // The gate blocks the LIVE prerequisite without rewriting the requested mode.
    assert.equal(readiness.liveAuthorityReadiness, "BLOCKED");

    const settings = createOperationPreparationSettings({ mode: "live" });
    assert.equal(settings.tradingMode, "LIVE");
    assert.notEqual(settings.tradingMode, "PAPER");
});

test("TEST H: LIVE automation intent is a visible guard when requested", () => {
    const inputs = baseInputs({
        allowLive: true,
        tradeMode: "live",
        loopOnStart: true,
    });
    const readiness = deriveOperationReadiness(inputs);
    const guidance = guidanceFor(readiness, inputs);

    assert.equal(readiness.liveAutomationReadiness, "BLOCKED");
    assert.ok(guidance.find((item) => item.id === "liveAutomation"));
    assert.equal(guidance.length, blockedCount(readiness));
});
