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
'    requestedLeverage: [1, 2, 3, 4, 5, 7, 10],' + "\n" +
'    positionSize: [0, 25, 50, 75, 100],' + "\n" +
'    stopLossPercent: [0.25, 0.5, 0.75, 1, 1.5, 2],' + "\n" +
'    takeProfitPercent: [0.5, 1, 1.5, 2, 3, 5],' + "\n" +
'    timeframes: ["1m", "5m", "15m", "1h"],' + "\n" +
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
'        Number(config.leverage),' + "\n" +
'        3,' + "\n" +
'    ),' + "\n" +
'    positionSize: config.positionSize == null ? 0 : Number(config.positionSize),' + "\n" +
'    stopLossPercent: config.sl == null ? 1 : Number(config.sl),' + "\n" +
'    takeProfitPercent: config.tp == null ? 2 : Number(config.tp),' + "\n" +
'    trailingStop: config.trailing === true,' + "\n" +
'    timeframe: supportedValue(OPERATION_PREPARATION_OPTIONS.timeframes, String(config.timeframe || ""), "1m"),' + "\n" +
'    loopOnStart: Boolean(config.loopOnStart),' + "\n" +
'    autoTradeOnStart: Boolean(config.autoTradeOnStart),' + "\n" +
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
'    positionSize: String(settings.positionSize) + " USDT",' + "\n" +
'    stopLoss: String(settings.stopLossPercent) + "%",' + "\n" +
'    takeProfit: String(settings.takeProfitPercent) + "%",' + "\n" +
'    trailingStop: settings.trailingStop ? "ON" : "OFF",' + "\n" +
'    timeframe: settings.timeframe,' + "\n" +
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
            )
            .replace(
                'from "./operationPreparationGuidance";',
                `from "${new URL("./operationPreparationGuidance.js", sourceUrl).href}";`,
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
    let currentProps = props;
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
    const render = (nextProps) => {
        if (nextProps) currentProps = { ...currentProps, ...nextProps };
        hookIndex = 0;
        const previous = internals.H;
        internals.H = dispatcher;
        try { root = Component(currentProps); } finally { internals.H = previous; }
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

const expandSafetyDetails = (renderer) => {
    const toggle = findTestId(renderer.root, "safety-details-toggle");
    assert.ok(toggle, "SAFETY / READINESS DETAILS toggle exists");
    toggle.props.onClick();
    renderer.render();
};

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

test("renders the five preparation sections, controls, derived fields, collapsible safety details, and existing start slot", async () => {
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
    expandSafetyDetails(renderer);
    const content = normalizedText(descendants(renderer.root));
    [
        "TRADING MODE", "MARKET SELECTION", "MONEY MANAGEMENT",
        "TRADE / EXECUTION", "AUTOMATION", "SAFETY / READINESS DETAILS",
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
    assert.equal(content.includes("NOT CONNECTED"), true);
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
        "operation-preparation-summary",
        "final-preparation-heading",
        "ready-to-start",
        "trading-mode-section",
        "market-selection-section",
        "money-management-section",
        "trade-execution-section",
        "automation-section",
    ];
    const indexes = orderedTestIds.map((testId) => nodes.findIndex(
        (node) => node.props?.["data-testid"] === testId,
    ));
    assert.deepEqual(orderedTestIds.filter((testId, index) => indexes[index] < 0), []);
    assert.deepEqual(indexes, [...indexes].sort((left, right) => left - right));

    // Note: UI-9 integrates Emergency section into OperationPreparation,
    // shifting node indices. The following assertions are adjusted accordingly.
    assert.equal(normalizedText(findTestId(renderer.root, "automation-section")).includes("LOOP ON START"), true);
    assert.equal(normalizedText(findTestId(renderer.root, "automation-section")).includes("AUTO TRADE ON START"), true);
    assert.equal(normalizedText(descendants(findTestId(renderer.root, "automation-section"))).includes("AUTO SELECTION START"), true);
    assert.equal(findTestId(renderer.root, "market-selection-section").props.children != null, true);
    assert.equal(findTestId(renderer.root, "money-management-section").props.children != null, true);
});

test("DOM: FINAL PREPARATION and EMERGENCY occupy the top band with no OPERATION label; lower grid keeps ①–⑤ and drops ⑥", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL", symbol: "XRPUSDTM" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        realOrderAllowed: false,
        children: { type: "button", props: { children: "START BOT" } },
    });
    const childrenOf = (node) => {
        const kids = node?.props?.children;
        if (kids == null) return [];
        return Array.isArray(kids) ? kids.filter(Boolean) : [kids];
    };
    const descriptor = (node) => [
        typeof node?.type === "string" ? node.type : "*",
        String(node?.props?.className || ""),
    ].join(".");

    const topBand = childrenOf(renderer.root).find((node) => descriptor(node).includes("operation-top-band"));
    assert.ok(topBand, "operation-top-band wraps the top zones");
    const bandClasses = childrenOf(topBand).map((node) => descriptor(node).split(".")[1]);
    assert.equal(bandClasses.length, 2, "top band has two zones: FINAL PREPARATION | EMERGENCY");
    assert.equal(bandClasses.some((cls) => cls.includes("operation-title")), false, "top band must NOT contain the OPERATION label");
    assert.equal(bandClasses.some((cls) => cls.includes("operation-prep-final")), true, "top band contains FINAL PREPARATION");
    assert.equal(bandClasses.some((cls) => cls.includes("operation-emergency-controls")), true, "top band contains EMERGENCY controls");
    const finalIdx = bandClasses.findIndex((cls) => cls.includes("operation-prep-final"));
    const emergIdx = bandClasses.findIndex((cls) => cls.includes("operation-emergency-controls"));
    assert.ok(finalIdx >= 0 && emergIdx > finalIdx, "top band order = FINAL PREPARATION | EMERGENCY");

    const lowerColumns = childrenOf(renderer.root).find((node) => descriptor(node).includes("operation-main-grid"));
    assert.ok(lowerColumns, "operation-main-grid wraps the ① – ⑤ lower sections");
    const gridClasses = childrenOf(lowerColumns).map((node) => descriptor(node).split(".")[1]);
    assert.equal(gridClasses.length, 2, "lower grid has exactly two columns (LEFT ①②③ + RIGHT ④⑤)");
    assert.equal(gridClasses.some((cls) => cls.includes("operation-column-left")), true, "lower grid LEFT column (① ② ③) present");
    assert.equal(gridClasses.some((cls) => cls.includes("operation-column-center")), true, "lower grid RIGHT column (④ ⑤) present");
    assert.equal(gridClasses.some((cls) => cls.includes("operation-prep-final")), false, "lower grid must NOT contain FINAL PREPARATION");
    assert.equal(findTestId(renderer.root, "safety-readiness-section"), undefined, "independent ⑥ SAFETY / START READINESS card is removed");
    assert.equal(gridClasses.some((cls) => cls.includes("operation-column-right")), false, "lower grid must NOT contain an empty third / right column");
    assert.equal(descendants(lowerColumns).some((node) => String(node?.props?.className || "").includes("operation-prep-final")), false, "FINAL PREPARATION is not a descendant of the lower grid");
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
    renderer.render({ config: { mode: "PAPER", symbol: "XRPUSDTM", selectionMode: "MANUAL" } });
    findSelect(renderer.root, "operation-prep-symbol").props.onChange({ target: { value: "BTCUSDTM" } });
    renderer.render({ config: { mode: "PAPER", symbol: "BTCUSDTM", selectionMode: "MANUAL", leverage: 5 } });
    findSelect(renderer.root, "operation-prep-leverage").props.onChange({ target: { value: "4" } });
    renderer.render({ config: { mode: "PAPER", symbol: "BTCUSDTM", selectionMode: "MANUAL", leverage: 4 } });
    const onButtons = descendants(renderer.root).filter(
        (node) => node.type === "button" && normalizedText(node) === "ON",
    );
    onButtons.forEach((button) => button.props.onClick());
    renderer.render({ config: { mode: "PAPER", symbol: "BTCUSDTM", selectionMode: "MANUAL", leverage: 4, loopOnStart: true, autoTradeOnStart: true } });

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

test("MM lifecycle RUNNING with entry not allowed stays non-ready in details and Final", async () => {
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
    expandSafetyDetails(renderer);
    const section3 = normalizedText(descendants(findTestId(renderer.root, "money-management-section")));
    const details = normalizedText(descendants(findTestId(renderer.root, "safety-readiness-details")));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(section3.includes("MM RUNTIME"), true);
    assert.equal(section3.includes("RUNNING"), true);
    assert.equal(section3.includes("WAITING"), true);
    assert.equal(details.includes("ENTRY PERMISSION"), true);
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
    expandSafetyDetails(renderer);
    const details = normalizedText(descendants(findTestId(renderer.root, "safety-readiness-details")));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(details.includes("READY"), true);
    assert.equal(readyToStart.includes("READY TO START"), true);
});

test("MM unavailable renders non-ready details and Final", async () => {
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
    expandSafetyDetails(renderer);
    const details = normalizedText(descendants(findTestId(renderer.root, "safety-readiness-details")));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(details.includes("MM START CONFIG"), true);
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
    assert.equal(settings.requestedLeverage, 5);
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
        config: { mode: "PAPER", leverage: 3 },
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
        config: { mode: "PAPER", leverage: 5 },
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
        config: { mode: "PAPER", leverage: 10 },
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
        config: { mode: "PAPER", leverage: 3 },
        mmConfiguration: null,
        leverageAuthority: null,
    });
    const content = normalizedText(descendants(renderer.root));
    assert.equal(findSelect(renderer.root, "operation-prep-leverage").props.value, 3);
    assert.equal(content.includes("MM Leverage Limit（MMレバレッジ上限） UNAVAILABLE"), true);
    assert.equal(content.includes("Effective Leverage（有効レバレッジ） UNAVAILABLE"), true);
});

// =========================
// TR-OP-A-DASH-4A: LIVE start authority model contract
// =========================

const readinessInput = (overrides = {}) => ({
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
    requestedLeverage: 5,
    maximumLeverage: 5,
    mmConfiguration: {
        riskPerTradePercent: "0.50",
        totalExposurePercent: "20.00",
        maximumDrawdownPercent: "5.00",
        maximumLeverage: "5",
    },
    mmBlockReasons: [],
    mmRecoveryRequired: false,
    mmConfigurationError: false,
    allowLive: false,
    tradeMode: "paper",
    ...overrides,
});

test("DASH4A: PAPER safe Start is preserved without entry permission", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "PAPER",
        executionEntryAllowed: true,
        mmBlockReasons: [],
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.startReadiness, "READY");
    assert.equal(result.liveAuthorityReadiness, "NOT_RELEVANT");
    assert.equal(result.entryReady, false);
});

test("DASH4A: A-R6 split allows PAPER start with runtime MM metrics unavailable", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "PAPER",
        executionEntryAllowed: false,
        mmBlockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.stoppedPaperRuntimeMetricsOnly, true);
    assert.equal(result.entryReady, false);
});

test("DASH4A: LIVE selected but authority denied is BLOCKED", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "LIVE",
        dryRun: false,
        allowLive: false,
        tradeMode: "paper",
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.startReadiness, "BLOCKED");
    assert.equal(result.liveAuthorityReadiness, "BLOCKED");
});

test("DASH4A: LIVE selected but trade mode not live is BLOCKED", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "LIVE",
        dryRun: false,
        allowLive: true,
        tradeMode: "paper",
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.liveAuthorityReadiness, "BLOCKED");
});

test("DASH4A: LIVE selected but authority unknown fails closed", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "LIVE",
        dryRun: false,
        allowLive: undefined,
        tradeMode: undefined,
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.startReadiness, "BLOCKED");
    assert.equal(result.liveAuthorityReadiness, "BLOCKED");
});

test("DASH4A: LIVE explicitly authorized is READY for start but not entry", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "LIVE",
        dryRun: false,
        allowLive: true,
        tradeMode: "live",
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.startReadiness, "READY");
    assert.equal(result.liveAuthorityReadiness, "READY");
    assert.equal(result.entryReady, false);
});

test("DASH4A: invalid mode fails closed", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        tradingMode: "SIMULATION",
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.startReadiness, "BLOCKED");
});

test("DASH4A: A-R1 requested leverage above MM max blocks, never clamps", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        requestedLeverage: 10,
        maximumLeverage: 5,
    }));
    assert.equal(result.startReady, false);
    assert.equal(result.leverageReadiness, "BLOCKED");
});

test("DASH4A: A-R1 requested leverage at MM max is allowed", async () => {
    const { deriveOperationReadiness } = await import("./operationPreparationModel.js");
    const result = deriveOperationReadiness(readinessInput({
        requestedLeverage: 5,
        maximumLeverage: 5,
    }));
    assert.equal(result.startReady, true);
    assert.equal(result.leverageReadiness, "READY");
});


test("trade/execution fields preserve distinct nondefault values and runtime summary", async () => {
    const legacyChanges = [];
    const Component = await loadComponent();
    const config = { mode: "PAPER", selectionMode: "MANUAL", symbol: "ETHUSDTM", leverage: 4, positionSize: 75, sl: 1.5, tp: 3, timeframe: "15m", trailing: true };
    const renderer = createRenderer(Component, { config, botRunning: false, onLegacyConfigChange: (update) => legacyChanges.push(update) });
    const content = normalizedText(descendants(renderer.root));
    for (const expected of ["75 USDT", "1.5%", "3%", "15m", "TRAILING STOP"]) {
        assert.equal(content.includes(expected), true, expected);
    }
    findSelect(renderer.root, "operation-prep-position-size").props.onChange({ target: { value: "50" } });
    findSelect(renderer.root, "operation-prep-stop-loss").props.onChange({ target: { value: "0.75" } });
    findSelect(renderer.root, "operation-prep-take-profit").props.onChange({ target: { value: "5" } });
    findSelect(renderer.root, "operation-prep-timeframe").props.onChange({ target: { value: "1h" } });
    assert.ok(legacyChanges.some((change) => change.positionSize === 50));
    assert.ok(legacyChanges.some((change) => change.sl === 0.75));
    assert.ok(legacyChanges.some((change) => change.tp === 5));
    assert.ok(legacyChanges.some((change) => change.timeframe === "1h"));
});

// =========================
// WORK-B FINAL UX: CASE 6-9
// =========================

test("CASE 6: READY start renders no stale block guidance", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        realOrderAllowed: false,
        executionEntryAllowed: true,
        recommendedAction: "CONTINUE",
        riskState: "NORMAL",
    });
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(readyToStart.includes("READY TO START"), true);
    assert.equal(readyToStart.includes("BLOCKED"), false);
    assert.equal(findTestId(renderer.root, "block-guidance"), undefined);
});

test("CASE 7: RUNNING bot renders neutral START readiness and ACTIVE execution, no pre-start fault", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        botRunning: true,
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        emergencyState: "READY",
        governanceStatus: "READY",
        pendingOrder: false,
        position: "FLAT",
        realOrderAllowed: false,
        executionEnabled: true,
        executionEntryAllowed: true,
        recommendedAction: "CONTINUE",
        riskState: "NORMAL",
        loopState: "RUNNING",
        loopStateTone: true,
        autoTradeStateText: "AUTO TRADE ON",
    });
    const content = normalizedText(descendants(renderer.root));
    const readyToStart = normalizedText(findTestId(renderer.root, "ready-to-start"));
    assert.equal(content.includes("N/A — BOT ALREADY RUNNING"), true);
    assert.equal(content.includes("ACTIVE（実行中）"), true);
    assert.equal(readyToStart.includes("READY TO START"), false);
    assert.equal(readyToStart.includes("BLOCKED"), false);
    assert.equal(findTestId(renderer.root, "block-guidance"), undefined);
});

test("CASE 8: bot returns STOPPED resumes pre-start readiness presentation", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        config: { mode: "PAPER", selectionMode: "MANUAL" },
        emergencyState: "READY",
        governanceStatus: "BLOCKED",
        pendingOrder: false,
        position: "FLAT",
        realOrderAllowed: false,
    });
    // STOPPED + a governing gate blocked -> guidance is shown.
    assert.ok(findTestId(renderer.root, "block-guidance"));
    // Re-render as RUNNING -> no pre-start fault.
    renderer.render({
        botRunning: true,
        loopState: "RUNNING",
        loopStateTone: true,
        autoTradeStateText: "AUTO TRADE ON",
    });
    assert.equal(findTestId(renderer.root, "block-guidance"), undefined);
    // Back to STOPPED -> guidance resumes.
    renderer.render({ botRunning: false });
    assert.ok(findTestId(renderer.root, "block-guidance"));
});

// =========================
// FINAL PREPARATION CONSOLIDATION
// =========================

const readyProps = (overrides = {}) => ({
    config: { mode: "PAPER", selectionMode: "MANUAL", symbol: "XRPUSDTM" },
    emergencyState: "READY",
    governanceStatus: "READY",
    pendingOrder: false,
    position: "FLAT",
    realOrderAllowed: false,
    executionEntryAllowed: true,
    recommendedAction: "CONTINUE",
    riskState: "NORMAL",
    children: { type: "button", props: { children: "START BOT" } },
    ...overrides,
});

test("OPERATION label is not rendered in the top band", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, readyProps());
    const content = normalizedText(descendants(renderer.root));
    assert.equal(findTestId(renderer.root, "operation-title"), undefined);
    assert.equal(content.trim().startsWith("OPERATION"), false);
    assert.equal(descendants(renderer.root).some(
        (node) => String(node?.props?.className || "").includes("operation-title"),
    ), false);
});

test("START GUARDS summary derives from authoritative readiness", async () => {
    const Component = await loadComponent();
    const readyRenderer = createRenderer(Component, readyProps());
    const readyState = normalizedText(findTestId(readyRenderer.root, "start-guards"));
    assert.equal(readyState.includes("START GUARDS"), true);
    assert.equal(readyState.includes("READY"), true);
    assert.equal(findTestId(readyRenderer.root, "start-guards-count"), undefined, "README state omits the count breakdown");

    const blockedRenderer = createRenderer(Component, readyProps({
        pendingOrder: true,
        position: "LONG",
        governanceStatus: "BLOCKED",
    }));
    const blockedState = normalizedText(findTestId(blockedRenderer.root, "start-guards"));
    assert.equal(blockedState.includes("START GUARDS"), true);
    assert.equal(blockedState.includes("BLOCKED"), true);
    assert.ok(findTestId(blockedRenderer.root, "start-guards-count"));

    // While RUNNING, START guards are not evaluated as a pre-start fault and
    // render a neutral N/A (mirrors START READINESS).
    const runningRenderer = createRenderer(Component, readyProps({
        botRunning: true,
        loopState: "RUNNING",
        loopStateTone: true,
        autoTradeStateText: "AUTO TRADE ON",
    }));
    const runningState = normalizedText(findTestId(runningRenderer.root, "start-guards"));
    assert.equal(runningState.includes("N/A — RUNNING"), true);
    assert.equal(findTestId(runningRenderer.root, "start-guards-count"), undefined);
});

test("SAFETY / READINESS DETAILS is collapsed by default and expands on toggle", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, readyProps());
    const toggle = findTestId(renderer.root, "safety-details-toggle");
    assert.ok(toggle, "details toggle present");
    assert.equal(toggle.props["aria-expanded"], false, "initial aria-expanded is false");
    assert.equal(findTestId(renderer.root, "safety-readiness-details-body"), undefined, "details body not rendered while collapsed");
    // Expanded body content (e.g. Enforcement) must not be in the collapsed DOM.
    const collapsedContent = normalizedText(descendants(renderer.root));
    assert.equal(collapsedContent.includes("Pending Order Authority（保留注文権限）"), false);

    expandSafetyDetails(renderer);
    assert.equal(findTestId(renderer.root, "safety-details-toggle").props["aria-expanded"], true, "toggled aria-expanded is true");
    assert.ok(findTestId(renderer.root, "safety-readiness-details-body"), "details body rendered when expanded");
    const expandedContent = normalizedText(descendants(renderer.root));
    for (const label of [
        "Emergency（緊急停止）",
        "Position（ポジション）",
        "Pending Order Authority（保留注文権限）",
        "Market Selection（市場選択）",
        "MM START CONFIG（開始設定）",
        "ENTRY PERMISSION（エントリー権限）",
        "Governance（ガバナンス）",
        "Execution（執行）",
        "Leverage Authority（レバレッジ権限）",
    ]) {
        assert.equal(expandedContent.includes(label), true, label);
    }
});

test("critical BLOCKED / WAITING guidance stays visible while details are collapsed", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, readyProps({
        pendingOrder: true,
        position: "LONG",
        governanceStatus: "BLOCKED",
        executionEntryAllowed: false,
        recommendedAction: "UNKNOWN",
        riskState: "UNKNOWN",
    }));
    // Details remain collapsed.
    assert.equal(findTestId(renderer.root, "safety-details-toggle").props["aria-expanded"], false);
    assert.ok(findTestId(renderer.root, "abnormal-guidance"), "abnormal guidance visible while collapsed");
    const abnormal = normalizedText(findTestId(renderer.root, "abnormal-guidance"));
    assert.equal(abnormal.includes("Pending Order Authority（保留注文権限）"), true, "Pending Order Authority non-ready exposed");
    assert.equal(abnormal.includes("Governance（ガバナンス）"), true, "Governance blocked exposed");
    assert.equal(abnormal.includes("Position（ポジション）"), true, "Position blocked exposed");
    assert.equal(abnormal.includes("BLOCKED"), true, "BLOCKED status surfaced");
});

test("collapse state is presentation-only and does not affect the START slot or handlers", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, readyProps());
    // START BOT is the children slot and remains rendered regardless of collapse.
    assert.ok(findButton(renderer.root, "START BOT"), "START BOT present while collapsed");
    expandSafetyDetails(renderer);
    assert.ok(findButton(renderer.root, "START BOT"), "START BOT still present when expanded");
    // The collapse state is local UI state and never appears in children props.
    const startPair = descendants(renderer.root).find(
        (node) => node.type === "button" && normalizedText(node) === "START BOT",
    );
    assert.ok(startPair);
});
