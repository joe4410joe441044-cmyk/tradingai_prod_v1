import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

const loadCard = async () => {
    const sourceUrl = new URL("./AutoMarketSelectionCard.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".ams-card-test-"));
    const output = join(temporary, "AutoMarketSelectionCard.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../features/auto-market-selection/autoMarketSelectionModel.js")).href;
    const operationModelUrl = pathToFileURL(join(directory,
        "./operation/operationPreparationModel.js")).href;
    const code = transformed.code
        .replace('from "../features/auto-market-selection/autoMarketSelectionModel.js";', `from "${modelUrl}";`)
        .replace('from "./operation/operationPreparationModel.js";', `from "${operationModelUrl}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=ams-card`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const status = {
    selectionMode: "AUTO",
    activeSymbol: "XRPUSDTM",
    requestedSymbol: "XRPUSDTM",
    topCandidate: { symbol: "ETHUSDT" },
    autoRuntime: {
        mode: "AUTO_PAPER", runtimeState: "OBSERVING", status: "IDLE", cycleId: null,
        lastCycleStatus: "COMPLETED_BLOCKED", lastCycleId: "ams-cycle-9",
        reasonCodes: ["MM_STALE", "ELIGIBILITY_STALE", "CAPITAL_INELIGIBLE"],
    },
    switch: { state: "IDLE", reasonCodes: [] },
    reasons: [],
    capitalEligibility: { status: "ELIGIBLE", mmRegime: "FRESH" },
    freshness: { mm: "FRESH" },
};

test("AUTO card labels last-cycle reasons as historical, not current blockers", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status }));
    assert.match(html, /LAST CYCLE STATUS/);
    assert.match(html, /COMPLETED_BLOCKED/);
    assert.match(html, /LAST CYCLE ID/);
    assert.match(html, /ams-cycle-9/);
    assert.match(html, /LAST CYCLE REASONS/);
    assert.match(html, /MM_STALE · ELIGIBILITY_STALE · CAPITAL_INELIGIBLE/);
    assert.doesNotMatch(html, />REASONS</);
    // current snapshot stays authoritative and untouched
    assert.match(html, /ELIGIBLE/);
    assert.match(html, /FRESH/);
});

test("AUTO card keeps active symbol and top candidate preview separate", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status }));
    assert.match(html, /ACTIVE SYMBOL · RUNTIME/);
    assert.match(html, /TOP CANDIDATE · PREVIEW/);
    assert.match(html, /XRPUSDTM/);
    assert.match(html, /ETHUSDT/);
});

test("AUTO card renders exactly one red SKIP / RESELECT button in the status grid", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status }));
    const matches = html.match(/data-testid="auto-market-selection-reselect"/g);
    assert.equal(matches.length, 1);
    assert.match(html, /SKIP \/ RESELECT/);
    assert.match(html, /class="ams-reselect"/);
    assert.match(html, /ams-reselect-cell/);
});

test("SKIP / RESELECT is not rendered inside the header", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status }));
    const headerIndex = html.indexOf('class="ams-card-header"');
    const gridIndex = html.indexOf('class="ams-symbol-grid"');
    const reselectIndex = html.indexOf('data-testid="auto-market-selection-reselect"');
    assert.ok(headerIndex !== -1 && gridIndex !== -1 && reselectIndex !== -1);
    assert.ok(gridIndex > headerIndex);
    assert.ok(reselectIndex > gridIndex);
});

test("SKIP / RESELECT sits right of LAST EVALUATED and below CYCLE ID", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status }));
    const cycleIdIndex = html.indexOf('>CYCLE ID<');
    const lastEvaluatedIndex = html.indexOf('>LAST EVALUATED<');
    const reselectIndex = html.indexOf('data-testid="auto-market-selection-reselect"');
    assert.ok(cycleIdIndex !== -1 && lastEvaluatedIndex !== -1 && reselectIndex !== -1);
    assert.ok(lastEvaluatedIndex > cycleIdIndex);
    assert.ok(reselectIndex > lastEvaluatedIndex);
});

test("AUTO card keeps AVAILABLE and collapse control in the header", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status, collapsible: true }));
    assert.match(html, /AVAILABLE/);
    assert.match(html, /ams-disclosure-icon/);
});

test("AUTO card keeps cycle metadata and the 4-column grid intact", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(Card, { status }));
    assert.match(html, /LAST CYCLE STATUS/);
    assert.match(html, /LAST CYCLE ID/);
    assert.match(html, /LAST EVALUATED/);
    assert.match(html, /ams-symbol-grid/);
});

test("AUTO card disables SKIP / RESELECT without an active symbol", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(
        Card,
        { status: { ...status, activeSymbol: null }, onReselect: () => {} },
    ));
    assert.match(html, /disabled=""/);
    assert.match(html, /NO_ACTIVE_SYMBOL/);
    assert.match(html, /ams-reselect--disabled/);
    assert.match(html, /SKIP \/ RESELECT/);
    assert.match(html, /aria-label="SKIP \/ RESELECT \(NO_ACTIVE_SYMBOL\)"/);
});

test("AUTO card honors an external reselect blocker", async () => {
    const { default: Card } = await loadCard();
    const html = renderToStaticMarkup(createElement(
        Card,
        { status, onReselect: () => {}, reselectDisabled: true, reselectReason: "POSITION_OPEN" },
    ));
    assert.match(html, /disabled=""/);
    assert.match(html, /POSITION_OPEN/);
});

test("reselect disabled style stays visible and never collapses to zero opacity or hidden", async () => {
    const css = await readFile(new URL("../styles/dashboard.css", import.meta.url), "utf8");
    const disabledBlock = css.match(/\.ams-reselect:disabled,\s*\.ams-reselect--disabled\s*\{[^}]*\}/);
    assert.ok(disabledBlock, "disabled selector block must exist");
    assert.match(disabledBlock[0], /background:\s*#4a2126/);
    assert.match(disabledBlock[0], /color:\s*#d7a9ad/);
    assert.match(disabledBlock[0], /cursor:\s*not-allowed/);
    assert.doesNotMatch(disabledBlock[0], /opacity:\s*0\b/);
    assert.doesNotMatch(disabledBlock[0], /visibility:\s*hidden/);
    assert.doesNotMatch(disabledBlock[0], /display:\s*none/);
});
