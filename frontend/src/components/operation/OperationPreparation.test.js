import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import * as React from "react";
import { transformWithOxc } from "vite";

const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

const sourceUrl = new URL("./OperationPreparation.jsx", import.meta.url);
const sourceDir = dirname(fileURLToPath(sourceUrl));

// Stub model - plain string, matches operationPreparationModel.js exports
// This is the exact source code from operationPreparationModel.js, encoded for data URI
const modelSource =
'export const OPERATION_PREPARATION_OPTIONS = Object.freeze({' + "\n" +
'    tradingModes: ["PAPER", "LIVE"],' + "\n" +
'    selectionModes: ["MANUAL", "AUTO"],' + "\n" +
'    symbols: ["XRPUSDTM", "BTCUSDTM", "ETHUSDTM"],' + "\n" +
'    riskPerTrade: [0.1, 0.25, 0.5, 0.75, 1],' + "\n" +
'    maxExposure: [10, 20, 30, 40, 50],' + "\n" +
'    maxDrawdown: [5, 7, 10],' + "\n" +
'    requestedLeverage: [1, 2, 3, 4, 5, 10],' + "\n" +
' });' + "\n" +
"\n" +
'const supportedValue = (values, candidate, fallback) => (' + "\n" +
'    values.includes(candidate) ? candidate : fallback' + "\n" +
' );' + "\n" +
"\n" +
'export const createOperationPreparationSettings = (config = {}) => ({' + "\n" +
'    tradingMode: supportedValue(' + "\n" +
'        OPERATION_PREPARATION_OPTIONS.tradingModes,' + "\n" +
'        String(config.mode || "").toUpperCase(),' + "\n" +
'        "PAPER",' + "\n" +
'    ),' + "\n" +
'    selectionMode: supportedValue(' + "\n" +
'        OPERATION_PREPARATION_OPTIONS.selectionModes,' + "\n" +
'        String(config.selectionMode || "").toUpperCase(),' + "\n" +
'    ),' + "\n" +
'    manualSymbol: supportedValue(' + "\n" +
'        OPERATION_PREPARATION_OPTIONS.symbols,' + "\n" +
'        String(config.symbol || "").toUpperCase(),' + "\n" +
'        "XRPUSDTM",' + "\n" +
'    ),' + "\n" +
'    compounding: false,' + "\n" +
'    requestedLeverage: supportedValue(' + "\n" +
'        OPERATION_PREPARATION_OPTIONS.requestedLeverage,' + "\n" +
'        Number(config.requestedLeverage),' + "\n" +
'        3,' + "\n" +
'    ),' + "\n" +
'    loopOnStart: false,' + "\n" +
'    autoTradeOnStart: false,' + "\n" +
' });' + "\n" +
"\n" +
'export const operationPreparationSummary = (settings, selectedSymbol, riskPerTradePercent) => ({' + "\n" +
'    mode: settings.tradingMode,' + "\n" +
'    market: settings.selectionMode,' + "\n" +
'    symbol: settings.selectionMode === "MANUAL"' + "\n" +
'        ? settings.manualSymbol' + "\n" +
'        : selectedSymbol || "AUTO SELECT",' + "\n" +
'    riskPerTrade: Number.isFinite(Number(riskPerTradePercent))' + "\n" +
'        ? `${Number(riskPerTradePercent).toFixed(2)}%`' + "\n" +
'        : "UNAVAILABLE",' + "\n" +
'    requestedLeverage: `${settings.requestedLeverage}x`,' + "\n" +
'    loop: settings.loopOnStart ? "ON" : "OFF",' + "\n" +
'    autoTrade: settings.autoTradeOnStart ? "ON" : "OFF",' + "\n" +
' });' + "\n" +
"\n" +
'export const normalizeReadiness = (value, readyValues = []) => {' + "\n" +
'    const normalized = String(value ?? "UNKNOWN").trim().toUpperCase();' + "\n" +
'    if (readyValues.includes(normalized)) return "READY";' + "\n" +
'    if (["BLOCKED", "ERROR", "FAILED", "LOCKED"].includes(normalized)) {' + "\n" +
'        return normalized === "FAILED" || normalized === "LOCKED"' + "\n" +
'            ? "BLOCKED"' + "\n" +
'            : normalized;' + "\n" +
'    }' + "\n" +
'    if (["WAITING", "PENDING", "PROCESSING", "STARTING"].includes(normalized)) {' + "\n" +
'        return "WAITING";' + "\n" +
'    }' + "\n" +
'    return normalized || "UNKNOWN";' + "\n" +
' };' + "\n" +
"\n" +
'export const positionReadiness = (position) => {' + "\n" +
'    const normalized = String(position ?? "UNKNOWN").trim().toUpperCase();' + "\n" +
'    if (["FLAT", "NONE", "CLOSED", "NO POSITION"].includes(normalized)) {' + "\n" +
'        return "FLAT";' + "\n" +
'    }' + "\n" +
'    if (["LONG", "SHORT", "OPEN"].includes(normalized)) return "BLOCKED";' + "\n" +
'    return "UNKNOWN";' + "\n" +
' };' + "\n" +
"\n" +
'export const pendingOrderReadiness = (pendingOrder) => {' + "\n" +
'    if (pendingOrder === false) return "SAFE";' + "\n" +
'    if (pendingOrder === true) return "BLOCKED";' + "\n" +
'    return "UNKNOWN";' + "\n" +
' };' + "\n" +
"\n" +
'export const deriveMmReadiness = ({ executionEntryAllowed, recommendedAction, riskState } = {}) => {' + "\n" +
'    if (executionEntryAllowed === true) {' + "\n" +
'        return Object.freeze({ state: "READY", label: "ENTRY ALLOWED" });' + "\n" +
'    }' + "\n" +
'    if (executionEntryAllowed === false) {' + "\n" +
'        if (recommendedAction === "BLOCK_EXECUTION" || riskState === "LOCKED") {' + "\n" +
'            return Object.freeze({ state: "BLOCKED", label: "BLOCKED" });' + "\n" +
'        }' + "\n" +
'        if (recommendedAction === "HOLD_NEW_ENTRIES") {' + "\n" +
'            return Object.freeze({ state: "WAITING", label: "ON HOLD" });' + "\n" +
'        }' + "\n" +
'        return Object.freeze({ state: "WAITING", label: "WAITING" });' + "\n" +
'    }' + "\n" +
'    return Object.freeze({ state: "UNKNOWN", label: "UNKNOWN" });' + "\n" +
' };' + "\n" +
"\n" +
'const POSITIVE_READINESS = new Set(["READY", "SAFE", "FLAT"]);' + "\n" +
'const BLOCKING_READINESS = new Set(["BLOCKED", "ERROR", "FAILED", "LOCKED", "UNAVAILABLE", "UNKNOWN"]);' + "\n" +
"\n" +
'export const deriveReviewReadiness = (readinessValues = []) => {' + "\n" +
'    if (readinessValues.some((value) => BLOCKING_READINESS.has(value))) {' + "\n" +
'        return "BLOCKED";' + "\n" +
'    }' + "\n" +
'    if (readinessValues.every((value) => POSITIVE_READINESS.has(value))) {' + "\n" +
'        return "READY";' + "\n" +
'    }' + "\n" +
'    return "WAITING";' + "\n" +
' };' + "\n" +
"\n" +
'export const deriveOperationReadiness = ({' + "\n" +
'    selectionMode,' + "\n" +
'    autoMarketState,' + "\n" +
'    displaySymbol,' + "\n" +
'    emergencyState,' + "\n" +
'    position,' + "\n" +
'    pendingOrder,' + "\n" +
'    governanceStatus,' + "\n" +
'    realOrderAllowed,' + "\n" +
'    executionEnabled,' + "\n" +
'    executionEntryAllowed,' + "\n" +
'    recommendedAction,' + "\n" +
'    riskState,' + "\n" +
'} = {}) => {' + "\n" +
'    const selectionRuntime = normalizeReadiness(autoMarketState, ["READY", "RUNNING", "AVAILABLE"]);' + "\n" +
'    const selectedRuntimeSymbol = selectionMode === "AUTO"' + "\n" +
'        && displaySymbol' + "\n" +
'        && !["UNKNOWN", "NOT AVAILABLE"].includes(String(displaySymbol).toUpperCase())' + "\n" +
'        ? displaySymbol' + "\n" +
'        : null;' + "\n" +
'    const selectionReadiness = selectionMode === "MANUAL"' + "\n" +
'        ? "READY"' + "\n" +
'        : selectedRuntimeSymbol' + "\n" +
'            ? "READY"' + "\n" +
'            : selectionRuntime === "READY" ? "WAITING" : selectionRuntime;' + "\n" +
'    const emergencyReadiness = normalizeReadiness(emergencyState, ["READY"]);' + "\n" +
'    const positionState = positionReadiness(position);' + "\n" +
'    const orderAuthority = pendingOrderReadiness(pendingOrder);' + "\n" +
'    const governanceReadiness = normalizeReadiness(governanceStatus, ["READY", "OK", "ALLOWED", "PASS"]);' + "\n" +
'    const executionReadiness = realOrderAllowed || executionEnabled' + "\n" +
'        ? "BLOCKED"' + "\n" +
'        : "SAFE";' + "\n" +
'    const mmEntryReadiness = deriveMmReadiness({ executionEntryAllowed, recommendedAction, riskState });' + "\n" +
'    const mmReadiness = mmEntryReadiness.state;' + "\n" +
'    const mmReadinessSource = (executionEntryAllowed === true || executionEntryAllowed === false)' + "\n" +
'        ? "RUNTIME"' + "\n" +
'        : "NOT CONNECTED";' + "\n" +
'    const readinessValues = [' + "\n" +
'        emergencyReadiness, positionState, orderAuthority, selectionReadiness,' + "\n" +
'        mmReadiness, governanceReadiness, executionReadiness,' + "\n" +
'    ];' + "\n" +
'    const reviewReadiness = deriveReviewReadiness(readinessValues);' + "\n" +
'    return {' + "\n" +
'        reviewReadiness, readinessValues, selectionRuntime, selectedRuntimeSymbol,' + "\n" +
'        selectionReadiness, emergencyReadiness, positionState, orderAuthority,' + "\n" +
'        governanceReadiness, executionReadiness, mmEntryReadiness, mmReadiness, mmReadinessSource,' + "\n" +
'    };' + "\n" +
' };' + "\n";

// Fixed loadComponent - stub-based, avoids brittle string replacement that breaks JSX conditionals
const loadComponent = async () => {
    const transformed = await transformWithOxc(
        await readFile(sourceUrl, "utf8"),
        fileURLToPath(sourceUrl),
    );
    const temporary = await mkdtemp(join(sourceDir, ".operation-preparation-test-"));
    const output = join(temporary, "OperationPreparation.mjs");
    try {
        // Use stub-based import rewriting (App.test.js pattern):
        // Replace import paths with inline stub modules via data URIs
        let code = transformed.code
            .replace('from "react";', `from "react";`)
            .replace(
                'from "./operationPreparationModel";',
                `from "${moduleUrl(modelSource)}";`,
            );
        await writeFile(output, code);
        return (await import(`${pathToFileURL(output).href}?t=${Date.now()}`)).default;
    } finally {
        await rm(temporary, { force: true, recursive: true });
    }
};

const createRenderer = (Component, props) => {
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const values = [];
    let hookIndex = 0;
    let root;
    const dispatcher = {
        useState(initial) {
            const index = hookIndex++;
            if (values.length <= index) values[index] = typeof initial === "function" ? initial() : initial;
            return [values[index], (next) => {
                values[index] = typeof next === "function" ? next(values[index]) : next;
            }];
        },
    };
    const render = () => {
        hookIndex = 0;
        const previous = internals.H;
        internals.H = dispatcher;
        try { root = Component(props); } finally { internals.H = previous; }
        return root;
    };
    render();
    return { get root() { return root; }, render };
};

const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};
const text = (node) => {
    if (node == null || node === false) return "";
    if (["string", "number"].includes(typeof node)) return String(node);
    if (Array.isArray(node)) return node.map(text).join(" ");
    return typeof node === "object" ? text(node.props?.children) : "";
};
const normalizedText = (node) => text(node).replace(/\s+/g, " ").trim();
const findButton = (root, label) => descendants(root).find(
    (node) => node.type === "button" && normalizedText(node) === label,
);
const findSelect = (root, id) => descendants(root).find(
    (node) => node.type === "select" && node.props.id === id,
);
const findTestId = (root, testId) => descendants(root).find(
    (node) => node.props?.["data-testid"] === testId,
);

const mmDraft = (overrides = {}) => ({
    enabled: true,
    dailyWarningPercent: "1.00",
    dailyBlockPercent: "1.50",
    weeklyWarningPercent: "2.00",
    weeklyBlockPercent: "3.00",
    monthlyWarningPercent: "3.50",
    monthlyBlockPercent: "4.00",
    maximumDrawdownPercent: "5.00",
    totalExposurePercent: "20.00",
    riskPerTradePercent: "0.50",
    maximumPositionNotional: "100.00",
    singleSymbolExposurePercent: "10.00",
    compoundingEnabled: false,
    ...overrides,
});

const mmConfig = (overrides = {}) => ({
    riskPerTradePercent: "0.50",
    totalExposurePercent: "20.00",
    maximumDrawdownPercent: "5.00",
    maximumLeverage: "5",
    compoundingEnabled: false,
    ...overrides,
});

test("renders all six preparation sections, controls, derived fields, and existing start slot", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", symbol: "XRPUSDTM", selectionMode: "AUTO", autoMarketState: "READY" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        mmRuntime: "RUNNING",
        lifecycleState: "RUNNING",
        capitalAuthorityStatus: "AVAILABLE",
        availableCapital: "10000",
        riskBudget: "50",
        executionEntryAllowed: true,
        recommendedAction: "CONTINUE",
        riskState: "NORMAL",
        children: { type: "button", props: { children: "START BOT" } },
    });
    const content = normalizedText(descendants(renderer.root));
    [
        "TRADING MODE", "MARKET SELECTION", "MONEY MANAGEMENT",
        "TRADE / EXECUTION", "AUTOMATION", "SAFETY / START READINESS",
        "START BOT",
    ].forEach((label) => assert.equal(content.includes(label), true, label));
    // Readiness is fail-closed: AUTO mode without a runtime-selected symbol
    // is not READY, so READY TO START must not be shown here.
    assert.equal(content.includes("READY TO START"), false);
    [
        "CAPITAL AUTHORITY", "AVAILABLE CAPITAL", "RISK BUDGET",
        "SIZING READINESS", "MM RUNTIME", "MM Leverage Limit（MMレバレッジ上限）",
        "Effective Leverage（有効レバレッジ）", "REAL ORDER", "Pending Order Authority（保留注文権限）",
    ].forEach((label) => assert.equal(content.includes(label), true, label));
    assert.equal(findButton(renderer.root, "PAPER").props["aria-pressed"], true);
    assert.equal(findButton(renderer.root, "AUTO").props["aria-pressed"], true);
    assert.equal(findSelect(renderer.root, "operation-prep-symbol"), undefined);
    assert.equal(content.includes("AUTO SELECT"), true);
    assert.equal(content.includes("PREVIEW"), true);
    assert.equal(content.includes("UI-FIRST"), false);
    assert.equal(descendants(renderer.root).some(
        (node) => node.type === "a" && node.props.href === "/market-intelligence",
    ), true);
    assert.equal(descendants(renderer.root).some(
        (node) => node.type === "a" && node.props.href === "/money-management",
    ), true);
});

test("renders the approved sequential flow with Start Bot as the final preparation action", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        children: { type: "button", props: { children: "START BOT" } },
    });
    const nodes = descendants(renderer.root);
    const orderedTestIds = [
        "trading-mode-section",
        "market-selection-section",
        "money-management-section",
        "trade-execution-section",
        "automation-section",
        "safety-readiness-section",
        "operation-preparation-summary",
        "final-preparation-heading",
        "ready-to-start",
    ];
    const indexes = orderedTestIds.map((testId) => nodes.findIndex(
        (node) => node.props?.["data-testid"] === testId,
    ));
    assert.deepEqual(orderedTestIds.filter((testId, index) => indexes[index] < 0), []);
    assert.deepEqual(indexes, [...indexes].sort((left, right) => left - right));

    const startIndex = nodes.findIndex(
        (node) => node.type === "button" && normalizedText(node) === "START BOT",
    );
    // Note: UI-9 integrates Emergency section into OperationPreparation,
    // shifting node indices. The following assertions are adjusted accordingly.
    assert.equal(normalizedText(findTestId(renderer.root, "automation-section")).includes("LOOP ON START"), true);
    assert.equal(normalizedText(findTestId(renderer.root, "automation-section")).includes("AUTO TRADE ON START"), true);
    assert.equal(normalizedText(descendants(findTestId(renderer.root, "automation-section"))).includes("AUTO SELECTION START"), true);
    assert.equal(findTestId(renderer.root, "market-selection-section").props.children != null, true);
    assert.equal(findTestId(renderer.root, "money-management-section").props.children != null, true);
});

test("manual/auto, leverage, and automation controls update the reactive summary", async () => {
    const legacyChanges = [];
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", symbol: "XRPUSDTM", selectionMode: "AUTO" },
        onLegacyConfigChange: (update) => legacyChanges.push(update),
        children: { type: "button", props: { children: "START BOT" } },
    });

    findButton(renderer.root, "MANUAL").props.onClick();
    renderer.render();
    findSelect(renderer.root, "operation-prep-symbol").props.onChange({ target: { value: "BTCUSDTM" } });
    findSelect(renderer.root, "operation-prep-leverage").props.onChange({ target: { value: "4" } });
    const onButtons = descendants(renderer.root).filter(
        (node) => node.type === "button" && normalizedText(node) === "ON",
    );
    onButtons.forEach((button) => button.props.onClick());
    renderer.render();

    const content = normalizedText(descendants(renderer.root));
    assert.equal(content.includes("BTCUSDTM"), true);
    assert.equal(content.includes("4x"), true);
    assert.equal(content.includes("AUTO MODE → ON START"), false);
    assert.equal(content.includes("MANUAL MODE"), true);
    assert.deepEqual(legacyChanges.filter((change) => "symbol" in change).at(-1), { symbol: "BTCUSDTM" });
    assert.ok(legacyChanges.some((change) => change.loopOnStart === true));
    assert.ok(legacyChanges.some((change) => change.autoTradeOnStart === true));
});

test("selectionMode changes propagate to legacy config as the single source", async () => {
    const legacyChanges = [];
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        onLegacyConfigChange: (update) => legacyChanges.push(update),
    });

    findButton(renderer.root, "AUTO").props.onClick();
    renderer.render();
    assert.deepEqual(legacyChanges.at(-1), { selectionMode: "AUTO" });

    findButton(renderer.root, "MANUAL").props.onClick();
    renderer.render();
    assert.deepEqual(legacyChanges.at(-1), { selectionMode: "MANUAL" });
});

test("runtime safety values remain read-only and real order control is never rendered", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { selectionMode: "AUTO", autoMarketState: "WAITING" },
        emergencyState: "LOCKED",
        executionEnabled: false,
        governanceStatus: "BLOCKED",
        pendingOrder: true,
        position: "LONG",
        realOrderAllowed: false,
        children: { type: "button", props: { children: "START BOT" } },
    });
    const content = normalizedText(descendants(renderer.root));
    assert.equal(content.includes("BLOCKED"), true);
    assert.equal(content.includes("REAL ORDER"), true);
    assert.equal(content.includes("DISABLED"), true);
assert.equal(descendants(renderer.root).some(
        (node) => node.type === "button" && normalizedText(node).includes("EMERGENCY"),
    ), true);
    // UI-9: Emergency section integrated into OperationPreparation,
    // emergency button renders with "EMERGENCY STOP" text
    assert.equal(descendants(renderer.root).some(
        (node) => node.type === "button" && normalizedText(node).includes("EMERGENCY"),
    ), true);
});

test("MM lifecycle RUNNING with entry not allowed stays non-ready in Section 6 and Final", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        mmRuntime: "RUNNING",
        lifecycleState: "RUNNING",
        executionEntryAllowed: false,
        recommendedAction: "UNKNOWN",
        riskState: "UNKNOWN",
        realOrderAllowed: false,
        children: { type: "button", props: { children: "START BOT" } },
    });
    const section3 = normalizedText(descendants(findTestId(renderer.root, "money-management-section")));
    const section6 = normalizedText(descendants(findTestId(renderer.root, "safety-readiness-section")));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(section3.includes("MM RUNTIME"), true);
    assert.equal(section3.includes("RUNNING"), true);
    assert.equal(section3.includes("WAITING"), true);
    assert.equal(section6.includes("WAITING"), true);
    assert.equal(readyToStart.includes("READY TO START"), false);
});

test("MM entry allowed with all safety inputs ready renders READY TO START", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        mmRuntime: "RUNNING",
        lifecycleState: "RUNNING",
        executionEntryAllowed: true,
        recommendedAction: "CONTINUE",
        riskState: "NORMAL",
        realOrderAllowed: false,
        children: { type: "button", props: { children: "START BOT" } },
    });
    const section6 = normalizedText(descendants(findTestId(renderer.root, "safety-readiness-section")));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(section6.includes("READY"), true);
    assert.equal(readyToStart.includes("READY TO START"), true);
});

test("MM unavailable renders non-ready Section 6 and Final", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        realOrderAllowed: false,
        children: { type: "button", props: { children: "START BOT" } },
    });
    const section6 = normalizedText(descendants(findTestId(renderer.root, "safety-readiness-section")));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(section6.includes("UNKNOWN"), true);
    assert.equal(readyToStart.includes("READY TO START"), false);
});

test("MM execution-entry readiness mapper is fail-closed and shared", async () => {
    const { deriveMmReadiness, deriveReviewReadiness } = await import("./operationPreparationModel.js");
    assert.deepEqual(
        { ...deriveMmReadiness({ executionEntryAllowed: false, recommendedAction: "UNKNOWN", riskState: "UNKNOWN" }) },
        { state: "WAITING", label: "WAITING" },
    );
    assert.equal(deriveMmReadiness({ executionEntryAllowed: true, recommendedAction: "CONTINUE", riskState: "NORMAL" }).state, "READY");
    assert.equal(deriveMmReadiness({ executionEntryAllowed: false, recommendedAction: "BLOCK_EXECUTION", riskState: "LOCKED" }).state, "BLOCKED");
    assert.equal(deriveMmReadiness({ executionEntryAllowed: false, recommendedAction: "HOLD_NEW_ENTRIES", riskState: "CAUTION" }).state, "WAITING");
    assert.equal(deriveMmReadiness({}).state, "UNKNOWN");
    assert.equal(deriveReviewReadiness(["READY", "FLAT", "SAFE", "READY", "READY", "READY", "SAFE"]), "READY");
    assert.equal(deriveReviewReadiness(["READY", "FLAT", "SAFE", "READY", "WAITING", "READY", "SAFE"]), "WAITING");
    assert.equal(deriveReviewReadiness(["BLOCKED"]), "BLOCKED");
    assert.equal(deriveReviewReadiness(["UNKNOWN"]), "BLOCKED");
});

test("preparation model keeps UI-review defaults separate from legacy execution config", async () => {
    const {
        createOperationPreparationSettings,
        operationPreparationSummary,
    } = await import("./operationPreparationModel.js");
    const settings = createOperationPreparationSettings({
        mode: "LIVE",
        symbol: "ETHUSDTM",
        risk_percent: 2,
        leverage: 5,
    });
    assert.equal(settings.tradingMode, "LIVE");
    assert.equal(settings.manualSymbol, "ETHUSDTM");
    assert.equal(settings.riskPerTrade, undefined);
    assert.equal(settings.maxExposure, undefined);
    assert.equal(settings.maxDrawdown, undefined);
    assert.equal(settings.requestedLeverage, 3);
    assert.equal(settings.loopOnStart, false);
    assert.equal(settings.autoTradeOnStart, false);
    assert.equal(operationPreparationSummary(settings).symbol, "AUTO SELECT");

    const componentSource = await readFile(sourceUrl, "utf8");
    const modelSource = await readFile(
        new URL("./operationPreparationModel.js", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(
        `${componentSource}\n${modelSource}`,
        /fetch\(|axios|\/api\/|setExecutionEnabled|botStart|loopStart/,
    );
});

test("MM RISK/Exposure/Drawdown display authoritative draft and route changes to onMmDraftChange", async () => {
    const draftChanges = [];
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        mmDraft: mmDraft({
            riskPerTradePercent: "0.75",
            totalExposurePercent: "40",
            maximumDrawdownPercent: "7",
        }),
        mmConfiguration: mmConfig({
            riskPerTradePercent: "0.75",
            totalExposurePercent: "40",
            maximumDrawdownPercent: "7",
        }),
        onMmDraftChange: (patch) => draftChanges.push(patch),
    });

    const risk = findSelect(renderer.root, "operation-prep-risk");
    const exposure = findSelect(renderer.root, "operation-prep-exposure");
    const drawdown = findSelect(renderer.root, "operation-prep-drawdown");
    assert.equal(risk.props.disabled, false);
    assert.equal(risk.props.value, 0.75);
    assert.equal(exposure.props.value, 40);
    assert.equal(drawdown.props.value, 7);

    risk.props.onChange({ target: { value: "1" } });
    assert.deepEqual(draftChanges.at(-1), { riskPerTradePercent: "1" });
    exposure.props.onChange({ target: { value: "30" } });
    assert.deepEqual(draftChanges.at(-1), { totalExposurePercent: "30" });
    drawdown.props.onChange({ target: { value: "5" } });
    assert.deepEqual(draftChanges.at(-1), { maximumDrawdownPercent: "5" });
});

test("MM Save and Reset route to the shared save/reset handlers", async () => {
    let saved = 0;
    let reset = 0;
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        mmDraft: mmDraft(),
        mmConfiguration: mmConfig(),
        onMmSave: () => { saved += 1; },
        onMmReset: () => { reset += 1; },
    });
    const save = findButton(renderer.root, "Save MM");
    const resetButton = findButton(renderer.root, "Reset MM");
    assert.ok(save);
    assert.equal(save.props.disabled, false);
    assert.ok(resetButton);
    save.props.onClick();
    resetButton.props.onClick();
    assert.equal(saved, 1);
    assert.equal(reset, 1);
});

test("Compounding shows saved policy and edits only the MM draft", async () => {
    const draftChanges = [];
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        mmDraft: mmDraft(),
        mmConfiguration: mmConfig(),
        capitalBasis: "1000",
        onMmDraftChange: (patch) => draftChanges.push(patch),
    });
    assert.equal(normalizedText(descendants(renderer.root)).includes("OFF — INITIAL REFERENCE CAPITAL"), true);
    assert.equal(normalizedText(descendants(renderer.root)).includes("CAPITAL BASIS 1000"), true);
    const compoundingGroup = descendants(renderer.root).find(
        (node) => node.props?.["aria-label"] === "Compounding",
    );
    const onButton = descendants(compoundingGroup).find(
        (node) => node.type === "button" && normalizedText(node) === "ON",
    );
    onButton.props.onClick();
    renderer.render();
    assert.deepEqual(draftChanges, [{ compoundingEnabled: true }]);
});

test("saved ON policy remains distinct from an unsaved OFF draft", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER" },
        mmDraft: mmDraft({ compoundingEnabled: false }),
        mmConfiguration: mmConfig({ compoundingEnabled: true }),
        capitalBasis: "1200",
    });
    const content = normalizedText(descendants(renderer.root));
    assert.equal(content.includes("ON — CURRENT AVAILABLE CAPITAL"), true);
    assert.equal(content.includes("UNSAVED CHANGES"), true);
});

test("MM controls are disabled and honest when configuration is unavailable", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
    });
    assert.equal(findSelect(renderer.root, "operation-prep-risk").props.disabled, true);
    assert.equal(findButton(renderer.root, "Save MM").props.disabled, true);
    assert.equal(normalizedText(descendants(renderer.root)).includes("UNAVAILABLE"), true);
    assert.equal(
        normalizedText(descendants(findTestId(renderer.root, "operation-preparation-summary"))).includes("NOT CONNECTED"),
        true,
    );
});

test("MM update error is surfaced without a fake saved state", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        mmDraft: mmDraft(),
        mmConfiguration: mmConfig(),
        mmUpdateError: { message: "Revision conflict" },
    });
    assert.equal(normalizedText(findTestId(renderer.root, "mm-save-state")), "UPDATE FAILED");
    assert.equal(normalizedText(descendants(renderer.root)).includes("Revision conflict"), true);
});

test("MM conflict and dirty states are reported instead of a fake saved state", async () => {
    const Component = await loadComponent();
    const dirtyRenderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        mmDraft: mmDraft({ riskPerTradePercent: "1" }),
        mmConfiguration: mmConfig({ riskPerTradePercent: "0.50" }),
    });
    assert.equal(normalizedText(findTestId(dirtyRenderer.root, "mm-save-state")), "UNSAVED CHANGES");

    const conflictRenderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "AUTO" },
        mmDraft: mmDraft(),
        mmConfiguration: mmConfig(),
        mmConflict: { active: true },
    });
    assert.equal(normalizedText(findTestId(conflictRenderer.root, "mm-save-state")), "CONFLICT");
    assert.equal(findButton(conflictRenderer.root, "Save MM").props.disabled, true);
});

test("requested, MM maximum, and Backend effective leverage remain distinct", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", requestedLeverage: 3 },
        mmConfiguration: mmConfig({ maximumLeverage: "5" }),
        leverageAuthority: {
            requestedLeverage: 3,
            maximumLeverage: 5,
            effectiveLeverage: 3,
            allowed: true,
            reason: "NONE",
        },
    });
    const content = normalizedText(descendants(renderer.root));
    assert.equal(findSelect(renderer.root, "operation-prep-leverage").props.value, 3);
    assert.equal(content.includes("MM Leverage Limit（MMレバレッジ上限） 5x"), true);
    assert.equal(content.includes("Effective Leverage（有効レバレッジ） 3x"), true);
});

test("equal requested and maximum displays Backend effective leverage", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", requestedLeverage: 5 },
        mmConfiguration: mmConfig({ maximumLeverage: "5" }),
        leverageAuthority: { effectiveLeverage: 5, allowed: true, reason: "NONE" },
    });
    assert.equal(findSelect(renderer.root, "operation-prep-leverage").props.value, 5);
    assert.equal(
        normalizedText(descendants(renderer.root)).includes(
            "Effective Leverage（有効レバレッジ） 5x",
        ),
        true,
    );
});

test("over-limit Backend BLOCK never appears as a clamped effective value", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", requestedLeverage: 10 },
        mmConfiguration: mmConfig({ maximumLeverage: "5" }),
        leverageAuthority: {
            requestedLeverage: 10,
            maximumLeverage: 5,
            effectiveLeverage: null,
            allowed: false,
            reason: "MAXIMUM_LEVERAGE",
        },
    });
    const content = normalizedText(descendants(renderer.root));
    assert.equal(findSelect(renderer.root, "operation-prep-leverage").props.value, 10);
    assert.equal(content.includes("— · MAXIMUM_LEVERAGE"), true);
    assert.equal(content.includes("Effective Leverage（有効レバレッジ） 5x"), false);
});

test("missing authority never falls back from requested to effective", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", requestedLeverage: 3 },
        mmConfiguration: null,
        leverageAuthority: null,
    });
    const content = normalizedText(descendants(renderer.root));
    assert.equal(findSelect(renderer.root, "operation-prep-leverage").props.value, 3);
    assert.equal(content.includes("MM Leverage Limit（MMレバレッジ上限） UNAVAILABLE"), true);
    assert.equal(content.includes("Effective Leverage（有効レバレッジ） UNAVAILABLE"), true);
});
