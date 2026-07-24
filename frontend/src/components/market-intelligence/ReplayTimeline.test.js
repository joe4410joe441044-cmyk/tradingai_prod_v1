import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { buildReplayTimelineModel } from "../../features/market-intelligence/replay/replayTimelineModel.js";

const componentDirectory = dirname(fileURLToPath(import.meta.url));

const loadTimelineModule = async () => {
    const sourceUrl = new URL("./ReplayTimeline.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(sourceUrl, "utf8"),
        fileURLToPath(sourceUrl),
    );
    const tempDirectory = await mkdtemp(join(componentDirectory, ".replay-timeline-test-"));
    const outputPath = join(tempDirectory, "ReplayTimeline.mjs");
    const modelUrl = pathToFileURL(join(
        componentDirectory,
        "../../features/market-intelligence/replay/replayTimelineModel.js",
    )).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_TIMELINE_CONTEXT__";
    const labelsUrl = pathToFileURL(join(componentDirectory, "marketIntelligenceLabels.js")).href;
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayTimelineModel.js";',
            `from "${modelUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";',
            `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`);
    try {
        await writeFile(outputPath, code);
        return await import(`${pathToFileURL(outputPath).href}?test=timeline`);
    } finally {
        await rm(tempDirectory, { recursive: true, force: true });
    }
};

const descendants = (node) => {
    if (node === null || node === undefined || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    return [node, ...descendants(node.props?.children)];
};

const textOf = (node) => {
    const children = node?.props?.children;
    if (Array.isArray(children)) return children.map((child) => (
        typeof child === "object" ? textOf(child) : String(child ?? "")
    )).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("initial timeline renders a compact accessible empty state", async () => {
    const { ReplayTimelineView } = await loadTimelineModule();
    const view = ReplayTimelineView({
        model: buildReplayTimelineModel(createInitialReplayEngineState()),
    });
    const nodes = descendants(view);
    const allText = nodes.map(textOf).join(" ");
    assert.match(allText, /REPLAY TIMELINE/);
    assert.match(allText, /NO TIMELINE EVENTS/);
    assert.doesNotMatch(allText, /QUALITY UNKNOWN/);
    assert.doesNotMatch(allText, /Total Events0/);
    assert.equal(nodes.some(({ props }) => props?.className === "mi-replay-timeline__summary"), false);
    assert.equal(nodes.some(({ type }) => type === "button"), false);
    assert.equal(nodes.some(({ props }) => typeof props?.onClick === "function"), false);
});

test("loaded timeline renders only reached events, metadata, and one current item", async () => {
    const { ReplayTimelineView } = await loadTimelineModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET,
        payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const view = ReplayTimelineView({ model: buildReplayTimelineModel(engine) });
    const nodes = descendants(view);
    const items = nodes.filter(({ type }) => type === "li");
    assert.equal(items.length, 1);
    assert.equal(items.filter(({ props }) => props["aria-current"] === "step").length, 1);
    const allText = nodes.map(textOf).join(" ");
    assert.match(allText, /MARKET_SNAPSHOT/);
    assert.match(allText, /replay-event-001/);
    assert.match(allText, /#1/);
    assert.match(allText, /CURRENT/);
    assert.match(allText, /VALID/);
    assert.doesNotMatch(allText, /DETECTOR_SIGNAL/);
    assert.doesNotMatch(allText, /FUTURE/);
});

test("timeline view tolerates normalized invalid items and remains read-only", async () => {
    const { ReplayTimelineView } = await loadTimelineModule();
    const model = buildReplayTimelineModel({
        replayCursor: null,
        projection: { timeline: [null, { id: "bad", timestamp: "bad" }] },
    });
    const nodes = descendants(ReplayTimelineView({ model }));
    assert.equal(nodes.filter(({ type }) => type === "li").length, 2);
    assert.equal(nodes.some(({ type }) => type === "button"), false);
    assert.equal(nodes.some(({ props }) => props?.tabIndex !== undefined), false);
    assert.equal(nodes.filter(({ props }) => props?.["aria-current"] === "step").length, 0);
});
