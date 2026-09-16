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
