import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import * as React from "react";
import { transformWithOxc } from "vite";

const sourceUrl = new URL("./OperationPreparation.jsx", import.meta.url);
const sourceDir = dirname(fileURLToPath(sourceUrl));

const loadComponent = async () => {
    const transformed = await transformWithOxc(
        await readFile(sourceUrl, "utf8"),
        fileURLToPath(sourceUrl),
    );
    const temporary = await mkdtemp(join(sourceDir, ".operation-preparation-test-"));
    const output = join(temporary, "OperationPreparation.mjs");
    const modelUrl = new URL("./operationPreparationModel.js", import.meta.url).href;
    try {
        await writeFile(output, transformed.code.replace(
            'from "./operationPreparationModel";',
            `from "${modelUrl}";`,
        ));
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
        children: { type: "button", props: { children: "START BOT" } },
    });
    const content = normalizedText(descendants(renderer.root));
    [
        "TRADING MODE", "MARKET SELECTION", "MONEY MANAGEMENT",
        "TRADE / EXECUTION", "AUTOMATION", "SAFETY / START READINESS",
        "READY TO START", "START BOT",
    ].forEach((label) => assert.equal(content.includes(label), true, label));
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
    const automationIndex = indexes[4];
    const readyIndex = indexes.at(-1);
    assert.equal(startIndex > readyIndex, true);
    assert.equal(startIndex > automationIndex, true);
    assert.equal(normalizedText(findTestId(renderer.root, "automation-section")).includes("LOOP ON START"), true);
    assert.equal(normalizedText(findTestId(renderer.root, "automation-section")).includes("AUTO TRADE ON START"), true);
    assert.equal(normalizedText(descendants(findTestId(renderer.root, "automation-section"))).includes("AUTO SELECTION START"), true);
    assert.equal(nodes.slice(startIndex + 1).some((node) => node.type === "button"), false);
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
        (node) => node.type === "button" && normalizedText(node).includes("REAL ORDER"),
    ), false);
    assert.equal(descendants(renderer.root).some(
        (node) => node.type === "button" && normalizedText(node).includes("EMERGENCY"),
    ), false);
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
