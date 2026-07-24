import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./MarketIntelligenceToolbar.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".mi-toolbar-test-"));
    const output = join(temporary, "MarketIntelligenceToolbar.mjs");
    const engineUrl = pathToFileURL(join(directory, "../../features/market-intelligence/replay/replayEngine.js")).href;
    const labelsUrl = pathToFileURL(join(directory, "marketIntelligenceLabels.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_TOOLBAR_CONTEXT__";
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayEngine.js";', `from "${engineUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=toolbar`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    return [node, ...descendants(node.props?.children)];
};
const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    return textOf(node.props?.children);
};

test("empty replay status renders only mode and one replay status", async () => {
    const { default: Toolbar } = await loadModule();
    globalThis.__MI_TOOLBAR_CONTEXT__ = { replayEngine: { dataset: null, machine: { state: "IDLE" } },
        applyReplayCommand: () => {} };
    const nodes = descendants(Toolbar());
    const text = textOf(Toolbar());
    assert.equal(nodes.filter(({ props }) => props?.className?.includes("mi-toolbar__field")).length, 2);
    assert.equal(text.match(/NO REPLAY SELECTED/g)?.length, 1);
    assert.doesNotMatch(text, /Timestamp unavailable|Quality（品質）|Position（対象ポジション）/);
});

test("loaded replay restores position, timestamp, quality, mode, and status", async () => {
    const { default: Toolbar } = await loadModule();
    globalThis.__MI_TOOLBAR_CONTEXT__ = { replayEngine: {
        dataset: { datasetId: "daily-replay" }, replayCursor: 1_700_000_000_000,
        machine: { state: "REPLAY_READY" }, projection: { currentEvent: {}, dataQuality: "VALID" },
    }, applyReplayCommand: () => {} };
    const text = textOf(Toolbar());
    for (const expected of ["daily-replay", "REPLAY_READY", "2023-11-14", "VALID", "REPLAY READY"])
        assert.match(text, new RegExp(expected));
});
