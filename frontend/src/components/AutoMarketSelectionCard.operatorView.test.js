import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

const transformCard = async ({ stubReact = false } = {}) => {
    const sourceUrl = new URL("./AutoMarketSelectionCard.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".ams-card-g5-"));
    const output = join(temporary, "AutoMarketSelectionCard.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../features/auto-market-selection/autoMarketSelectionModel.js")).href;
    const operationModelUrl = pathToFileURL(join(directory,
        "./operation/operationPreparationModel.js")).href;
    let code = transformed.code
        .replace('from "../features/auto-market-selection/autoMarketSelectionModel.js";', `from "${modelUrl}";`)
        .replace('from "./operation/operationPreparationModel.js";', `from "${operationModelUrl}";`);
    if (stubReact) {
        const reactStub = moduleUrl(`
export function useState(initial){
    const store = globalThis.__AMS_HOOK_STORE__;
    const index = globalThis.__AMS_HOOK_INDEX__;
    if (store[index] === undefined) store[index] = initial;
    globalThis.__AMS_HOOK_INDEX__ = index + 1;
    return [store[index], (value) => { store[index] = typeof value === "function" ? value(store[index]) : value; }];
}`);
        code = code.replace('from "react";', `from "${reactStub}";`);
    }
    await writeFile(output, code);
    return { module: await import(`${pathToFileURL(output).href}?test=ams-g5-${stubReact}`), temporary };
};

const walk = (node, visit) => {
    if (node === null || node === undefined || typeof node === "boolean") return;
    if (Array.isArray(node)) { node.forEach((child) => walk(child, visit)); return; }
    if (typeof node !== "object") return;
    visit(node);
    if (node.props) walk(node.props.children, visit);
};

const findByTestId = (tree, testId) => {
    let found = null;
    walk(tree, (node) => {
        if (!found && node.props && node.props["data-testid"] === testId) found = node;
    });
    return found;
};

const criticalStatus = {
    selectionMode: "AUTO",
    activeSymbol: "XRPUSDTM",
    requestedSymbol: "MEWUSDT",
    topCandidate: { symbol: "DYMUSDT", score: "0.91", spreadScore: "0.8", liquidityScore: "0.7", activityScore: "0.6" },
    autoRuntime: {
        mode: "LIVE_READ_ONLY", runtimeState: "OBSERVING", status: "IDLE",
        cycleId: "ams-cycle-0123456789abcdef0123456789abcdef",
        lastCycleStatus: "COMPLETED_BLOCKED", lastCycleId: "ams-cycle-9",
        evaluatedAt: "2026-09-26 22:44:44",
        reasonCodes: ["MM_STALE", "ELIGIBILITY_STALE", "CAPITAL_INELIGIBLE"],
    },
    scanner: { status: "READY", universeCount: 120, evaluatedCount: 120, eligibleCount: 7, rejectedCount: 113, evaluatedAt: "2026-09-26 22:44:41" },
    ranking: { status: "RANKED_CANDIDATES_AVAILABLE", rankedCount: 7 },
    switch: { state: "IDLE", previousSymbol: "XRPUSDTM", proposedSymbol: "DYMUSDT", committedSymbol: "DYMUSDT", transactionId: "txn-0123456789abcdef", reasonCodes: [] },
    reasons: [],
    capitalEligibility: {
        status: "ELIGIBLE", availableCapital: "7.9184", riskBudget: "0.0396",
        remainingExposure: "0.0000", remainingPositionCapacity: "1",
        mmRegime: "CAPITAL_PROTECTION_STANDARD",
    },
    freshness: { universe: "FRESH", scanner: "FRESH", ranking: "FRESH", mm: "FRESH" },
};

const renderStatic = async (props) => {
    const { module, temporary } = await transformCard();
    try {
        return renderToStaticMarkup(createElement(module.default, props));
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

test("ESSENTIAL VIEW exposes only operator-critical values", async () => {
    const html = await renderStatic({ status: criticalStatus, collapsible: true });
    for (const expected of [
        "ACTIVE SYMBOL", "XRPUSDTM",
        "TOP CANDIDATE · PREVIEW", "DYMUSDT",
        ">STATUS<", "OBSERVING",
        "LAST EVALUATED", "2026-09-26 22:44:44",
        "SKIP / RESELECT",
        "CAPITAL", "ELIGIBLE", "AVAILABLE CAPITAL", "7.9184", "RISK BUDGET", "0.0396",
        "CURRENT REASONS",
    ]) {
        assert.ok(html.includes(expected), `essential view must include ${expected}`);
    }
});

test("DETAILS / DIAGNOSTICS is collapsed by default and hides diagnostic bulk", async () => {
    const html = await renderStatic({ status: criticalStatus, collapsible: true });
    assert.match(html, /data-testid="auto-market-selection-details-toggle"/);
    assert.match(html, /DETAILS \/ DIAGNOSTICS/);
    assert.match(html, /aria-expanded="false"/);
    assert.doesNotMatch(html, /data-testid="auto-market-selection-details"/);
    for (const hidden of [
        "SELECTION MODE", "NEXT REQUESTED SYMBOL", "AUTO RUNTIME MODE",
        "CYCLE STATUS", "CYCLE ID", "REJECTED", "TOP SCORE",
        "REMAINING EXPOSURE", "SYMBOL SWITCH", "LAST CYCLE REASONS",
    ]) {
        assert.ok(!html.includes(hidden), `collapsed diagnostics must not expose ${hidden}`);
    }
});

test("DETAILS / DIAGNOSTICS reveals every diagnostic group when expanded", async () => {
    const html = await renderStatic({ status: criticalStatus, collapsible: false });
    assert.match(html, /aria-expanded="true"/);
    assert.match(html, /data-testid="auto-market-selection-details"/);
    for (const expected of [
        "SELECTION MODE", "NEXT REQUESTED SYMBOL", "MEWUSDT", "AUTO RUNTIME MODE",
        "CYCLE STATUS", "CYCLE ID",
        "SCANNER", "REJECTED", "113",
        "RANKING", "TOP SCORE",
        "CAPITAL DETAILS", "REMAINING EXPOSURE", "POSITION CAPACITY", "MM REGIME",
        "SYMBOL SWITCH", "NEW ENTRIES PAUSED",
        "ams-freshness", "UNIVERSE: FRESH",
        "LAST CYCLE REASONS", "MM_STALE",
    ]) {
        assert.ok(html.includes(expected), `expanded diagnostics must include ${expected}`);
    }
});

test("critical operator values render in full without applying ellipsis", async () => {
    const html = await renderStatic({ status: criticalStatus, collapsible: false });
    for (const value of ["XRPUSDTM", "DYMUSDT", "MEWUSDT", "LIVE_READ_ONLY", "CAPITAL_PROTECTION_STANDARD"]) {
        assert.ok(html.includes(value), `full value ${value} must render`);
    }
    assert.match(html, /class="ams-field ams-field--wrap"/);
    // Active symbol / top candidate / next requested / runtime mode / MM regime must wrap.
    const css = await readFile(new URL("../styles/dashboard.css", import.meta.url), "utf8");
    const wrapBlock = css.match(/\.ams-field--wrap \.ams-field-value\s*\{[^}]*\}/);
    assert.ok(wrapBlock, "critical wrap rule must exist");
    assert.match(wrapBlock[0], /white-space:\s*normal/);
    assert.match(wrapBlock[0], /text-overflow:\s*clip/);
    assert.doesNotMatch(wrapBlock[0], /text-overflow:\s*ellipsis/);
});

test("long machine identifiers stay single-line but expose the full value via title", async () => {
    const html = await renderStatic({ status: criticalStatus, collapsible: false });
    assert.ok(html.includes('title="ams-cycle-0123456789abcdef0123456789abcdef"'));
    assert.ok(html.includes('title="txn-0123456789abcdef"'));
    const cycleField = html.match(/<div class="ams-field(?! ams-field--wrap)[^"]*"[^>]*>.*?CYCLE ID/s);
    assert.ok(cycleField, "CYCLE ID field must not force critical wrapping");
    const css = await readFile(new URL("../styles/dashboard.css", import.meta.url), "utf8");
    assert.match(css, /\.ams-field-value\s*\{[^}]*text-overflow:\s*ellipsis/);
});

test("opening and closing DETAILS / DIAGNOSTICS is keyboard-operable stateful disclosure", async () => {
    globalThis.__AMS_HOOK_STORE__ = [];
    globalThis.__AMS_HOOK_INDEX__ = 0;
    const { module, temporary } = await transformCard({ stubReact: true });
    try {
        const render = () => {
            globalThis.__AMS_HOOK_INDEX__ = 0;
            return module.default({ status: criticalStatus, collapsible: true });
        };
        let tree = render();
        let toggle = findByTestId(tree, "auto-market-selection-details-toggle");
        assert.equal(toggle.type, "button");
        assert.equal(toggle.props["aria-expanded"], false);
        assert.equal(toggle.props["aria-controls"], "ams-card-details");
        assert.equal(findByTestId(tree, "auto-market-selection-details"), null);

        toggle.props.onClick();
        tree = render();
        toggle = findByTestId(tree, "auto-market-selection-details-toggle");
        assert.equal(toggle.props["aria-expanded"], true);
        assert.ok(findByTestId(tree, "auto-market-selection-details"));

        toggle.props.onClick();
        tree = render();
        toggle = findByTestId(tree, "auto-market-selection-details-toggle");
        assert.equal(toggle.props["aria-expanded"], false);
        assert.equal(findByTestId(tree, "auto-market-selection-details"), null);
    } finally {
        delete globalThis.__AMS_HOOK_STORE__;
        delete globalThis.__AMS_HOOK_INDEX__;
        await rm(temporary, { recursive: true, force: true });
    }
});

test("AUTHORITY: active symbol source, top candidate preview, and SKIP handler are unchanged", async () => {
    globalThis.__AMS_HOOK_STORE__ = [];
    globalThis.__AMS_HOOK_INDEX__ = 0;
    const { module, temporary } = await transformCard({ stubReact: true });
    try {
        let calls = 0;
        const tree = module.default({
            status: criticalStatus,
            collapsible: true,
            onReselect: () => { calls += 1; },
        });
        const reselect = findByTestId(tree, "auto-market-selection-reselect");
        assert.ok(reselect, "SKIP / RESELECT must render in the essential view");
        assert.equal(reselect.props.disabled, false);
        reselect.props.onClick();
        assert.equal(calls, 1);
    } finally {
        delete globalThis.__AMS_HOOK_STORE__;
        delete globalThis.__AMS_HOOK_INDEX__;
        await rm(temporary, { recursive: true, force: true });
    }

    // Active symbol never falls back to requested/top candidate, and the top
    // candidate stays explicitly labeled PREVIEW.
    const fallback = await renderStatic({
        status: { ...criticalStatus, activeSymbol: null },
        collapsible: true,
    });
    assert.match(fallback, /ACTIVE SYMBOL/);
    assert.match(fallback, /TOP CANDIDATE · PREVIEW/);
    assert.ok(fallback.includes("DYMUSDT"));
    assert.doesNotMatch(fallback, /XRPUSDTM/);
});

test("AUTHORITY: SKIP / RESELECT disabled logic is unchanged", async () => {
    const html = await renderStatic({
        status: { ...criticalStatus, activeSymbol: null },
        collapsible: true,
        onReselect: () => {},
    });
    assert.match(html, /disabled=""/);
    assert.match(html, /NO_ACTIVE_SYMBOL/);
    assert.match(html, /ams-reselect--disabled/);
});

test("AUTHORITY: current reasons and last-cycle reasons stay semantically separate", async () => {
    const currentStatus = {
        ...criticalStatus,
        switch: { ...criticalStatus.switch, reasonCodes: ["POSITION_NOT_FLAT"] },
        reasons: ["NO_ELIGIBLE_MARKET"],
    };
    const collapsed = await renderStatic({ status: currentStatus, collapsible: true });
    assert.match(collapsed, /CURRENT REASONS/);
    assert.ok(collapsed.includes("POSITION_NOT_FLAT"));
    assert.ok(!collapsed.includes("LAST CYCLE REASONS"));
    assert.ok(!collapsed.includes("MM_STALE"));

    const expanded = await renderStatic({ status: currentStatus, collapsible: false });
    assert.match(expanded, /LAST CYCLE REASONS/);
    assert.ok(expanded.includes("MM_STALE"));
    assert.ok(expanded.includes("CURRENT REASONS"));
});

test("NO BACKEND / NO API CONTRACT CHANGE: reselect route and handler wiring are intact", async () => {
    const apiSource = await readFile(new URL("../api/index.js", import.meta.url), "utf8");
    assert.match(apiSource, /paperAutoReselect:\s*\(\)\s*=>\s*join\("\/runtime\/paper-auto\/reselect"\)/);
    const panelSource = await readFile(new URL("./market-intelligence/AutoMarketSelectionPanel.jsx", import.meta.url), "utf8");
    assert.match(panelSource, /authenticatedControlRequest\(API\.paperAutoReselect\(\),\s*\{\s*method:\s*"POST"\s*\}\)/);
    const cardSource = await readFile(new URL("./AutoMarketSelectionCard.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(cardSource, /from\s+["'][^"']*backend/);
});
