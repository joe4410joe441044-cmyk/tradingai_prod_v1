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
'    riskPerTrade: [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2],' + "\n" +
'    maxExposure: [10, 20, 30, 40, 50],' + "\n" +
'    maxDrawdown: [2, 3, 5, 7, 10],' + "\n" +
'    requestedLeverage: [1, 2, 3, 4, 5],' + "\n" +
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
'    riskPerTrade: 0.5,' + "\n" +
'    compounding: false,' + "\n" +
'    maxExposure: 30,' + "\n" +
'    maxDrawdown: 5,' + "\n" +
'    requestedLeverage: 3,' + "\n" +
'    loopOnStart: false,' + "\n" +
'    autoTradeOnStart: false,' + "\n" +
' });' + "\n" +
"\n" +
'export const operationPreparationSummary = (settings, selectedSymbol) => ({' + "\n" +
'    mode: settings.tradingMode,' + "\n" +
'    market: settings.selectionMode,' + "\n" +
'    symbol: settings.selectionMode === "MANUAL"' + "\n" +
'        ? settings.manualSymbol' + "\n" +
'        : selectedSymbol || "AUTO SELECT",' + "\n" +
'    riskPerTrade: "0.50%",' + "\n" +
'    requestedLeverage: "3x",' + "\n" +
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

test("manual/auto, MM, leverage, and automation controls update the reactive summary", async () => {
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
    findSelect(renderer.root, "operation-prep-risk").props.onChange({ target: { value: "1.5" } });
    findSelect(renderer.root, "operation-prep-exposure").props.onChange({ target: { value: "40" } });
    findSelect(renderer.root, "operation-prep-drawdown").props.onChange({ target: { value: "7" } });
    findSelect(renderer.root, "operation-prep-leverage").props.onChange({ target: { value: "4" } });
    const onButtons = descendants(renderer.root).filter(
        (node) => node.type === "button" && normalizedText(node) === "ON",
    );
    onButtons.forEach((button) => button.props.onClick());
    renderer.render();

    const content = normalizedText(descendants(renderer.root));
    assert.equal(content.includes("BTCUSDTM"), true);
    assert.equal(content.includes("1.50%"), true);
    assert.equal(content.includes("4x"), true);
    assert.equal(content.includes("AUTO MODE → ON START"), false);
    assert.equal(content.includes("MANUAL MODE"), true);
    assert.deepEqual(legacyChanges.at(-1), { symbol: "BTCUSDTM" });
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
    assert.equal(settings.riskPerTrade, 0.5);
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