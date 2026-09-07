import assert from "node:assert/strict";
import test from "node:test";

import { deriveOperationBlockGuidance } from "./operationPreparationGuidance.js";

const readySettings = { requestedLeverage: 3, selectionMode: "MANUAL" };
const readyConfig = { displaySymbol: "XRPUSDTM" };
const readyContext = (overrides = {}) => ({
    settings: readySettings,
    config: readyConfig,
    emergencyReadiness: "READY",
    positionState: "FLAT",
    orderAuthority: "SAFE",
    selectionReadiness: "READY",
    selectionRuntime: "READY",
    selectedRuntimeSymbol: "XRPUSDTM",
    startMmReadiness: "READY",
    mmEntryReadiness: { state: "READY", label: "ENTRY ALLOWED" },
    governanceReadiness: "READY",
    executionReadiness: "SAFE",
    leverageReadiness: "READY",
    emergencyState: "READY",
    position: "FLAT",
    pendingOrder: false,
    governanceStatus: "READY",
    realOrderAllowed: false,
    executionEnabled: false,
    mmConfiguration: { maximumLeverage: "5" },
    mmDraft: { riskPerTradePercent: "0.50", maximumDrawdownPercent: "5" },
    ...overrides,
});

test("CASE 1: over-limit requested leverage renders ④ TRADE / EXECUTION guidance", () => {
    const guidance = deriveOperationBlockGuidance(readyContext({
        leverageReadiness: "BLOCKED",
        settings: { ...readySettings, requestedLeverage: 7 },
        mmConfiguration: { maximumLeverage: "5" },
    }));
    const leverage = guidance.find((item) => item.id === "leverage");
    assert.ok(leverage, "leverage guidance present");
    assert.equal(leverage.status, "BLOCKED");
    assert.equal(leverage.current, "Requested: 7x");
    assert.equal(leverage.required, "MM Limit: 5x");
    assert.equal(leverage.section, "④ TRADE / EXECUTION");
    assert.equal(leverage.en, "Requested leverage exceeds MM leverage limit.");
});

test("CASE 2: correcting leverage 7→3 removes the leverage guidance", () => {
    const guidance = deriveOperationBlockGuidance(readyContext({
        leverageReadiness: "READY",
        settings: { ...readySettings, requestedLeverage: 3 },
        mmConfiguration: { maximumLeverage: "5" },
    }));
    assert.equal(guidance.find((item) => item.id === "leverage"), undefined);
});

test("CASE 3: AUTO selection not ready renders ② MARKET SELECTION guidance", () => {
    const guidance = deriveOperationBlockGuidance(readyContext({
        selectionReadiness: "WAITING",
        settings: { ...readySettings, selectionMode: "AUTO" },
        selectionRuntime: "WAITING",
        selectedRuntimeSymbol: null,
        config: { displaySymbol: "XRPUSDTM" },
    }));
    const market = guidance.find((item) => item.id === "marketSelection");
    assert.ok(market, "market selection guidance present");
    assert.equal(market.section, "② MARKET SELECTION");
    assert.equal(market.status, "WAITING");
    assert.ok(market.current.includes("AUTO runtime=WAITING"));
});

test("CASE 4: unsaved MM draft divergence renders ③ guidance for auto-reconcile", () => {
    const guidance = deriveOperationBlockGuidance(readyContext({
        startMmReadiness: "BLOCKED",
        mmDraft: { riskPerTradePercent: "0.75", maximumDrawdownPercent: "7" },
        mmConfiguration: {
            riskPerTradePercent: "0.50",
            maximumDrawdownPercent: "5",
            maximumLeverage: "5",
        },
    }));
    const mmStart = guidance.find((item) => item.id === "mmStart");
    assert.ok(mmStart, "MM START guidance present");
    assert.equal(mmStart.section, "③ MONEY MANAGEMENT");
    assert.ok(mmStart.current.includes("draft risk=0.75%"));
    assert.ok(mmStart.current.includes("saved risk=0.50%"));
    assert.ok(!mmStart.en.includes("Save MM"));
    assert.ok(mmStart.en.includes("auto-reconcile"));
});

test("CASE 5: multiple simultaneous blockers all render", () => {
    const guidance = deriveOperationBlockGuidance(readyContext({
        leverageReadiness: "BLOCKED",
        selectionReadiness: "WAITING",
        startMmReadiness: "BLOCKED",
        settings: { ...readySettings, selectionMode: "AUTO", requestedLeverage: 7 },
        selectionRuntime: "WAITING",
        selectedRuntimeSymbol: null,
        mmConfiguration: { riskPerTradePercent: "0.50", maximumDrawdownPercent: "5", maximumLeverage: "5" },
        mmDraft: { riskPerTradePercent: "0.75", maximumDrawdownPercent: "7" },
    }));
    const ids = guidance.map((item) => item.id);
    assert.ok(ids.includes("leverage"));
    assert.ok(ids.includes("marketSelection"));
    assert.ok(ids.includes("mmStart"));
});

test("CASE 6: fully READY start renders no stale block guidance", () => {
    assert.deepEqual(deriveOperationBlockGuidance(readyContext()), []);
});

test("WF-1 coverage: each START readiness dimension maps to the correct section", () => {
    // ENTRY PERMISSION and Governance are runtime-only post-START guards and
    // are intentionally NOT part of the START block guidance (Problems 5/6).
    const expectation = [
        ["emergency", "emergencyReadiness"],
        ["position", "positionState"],
        ["pendingOrder", "orderAuthority"],
        ["execution", "executionReadiness"],
    ];
    for (const [id, key] of expectation) {
        const guidance = deriveOperationBlockGuidance(readyContext({ [key]: "BLOCKED" }));
        const item = guidance.find((entry) => entry.id === id);
        assert.ok(item, `${id} guidance present`);
        assert.equal(item.section, "FINAL PREPARATION", `${id} consolidates into FINAL PREPARATION`);
        assert.ok(item.en.length > 0 && item.ja.length > 0 && item.fix.length > 0);
    }
});

test("Problem 5/6: EnTRY Permission and Governance never render as START blockers", () => {
    const guidance = deriveOperationBlockGuidance(readyContext({
        mmEntryReadiness: { state: "WAITING", label: "WAITING" },
        governanceReadiness: "SUSPENDED_BY_BOT_STOP",
    }));
    assert.equal(guidance.find((item) => item.id === "entryPermission"), undefined);
    assert.equal(guidance.find((item) => item.id === "governance"), undefined);
});
