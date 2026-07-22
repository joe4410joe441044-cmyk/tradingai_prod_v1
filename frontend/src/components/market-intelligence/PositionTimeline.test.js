import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { buildReplayPositionTimelineModel } from "../../features/market-intelligence/replay/replayPositionTimelineModel.js";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./PositionTimeline.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".position-timeline-test-"));
    const output = join(temporary, "PositionTimeline.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/replay/replayPositionTimelineModel.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_POSITION_CONTEXT__";
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayPositionTimelineModel.js";', `from "${modelUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=position-timeline`);
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
    const children = node?.props?.children;
    if (Array.isArray(children)) return children.map((child) => typeof child === "object" ? textOf(child) : String(child ?? "")).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("position timeline renders an accessible empty state", async () => {
    const { PositionTimelineView } = await loadModule();
    const nodes = descendants(PositionTimelineView({ model: buildReplayPositionTimelineModel(null) }));
    const text = nodes.map(textOf).join(" ");
    assert.match(text, /POSITION TIMELINE/);
    assert.match(text, /NO POSITION EVENTS/);
    assert.equal(nodes.some(({ type }) => type === "button"), false);
});

test("position timeline renders reached open, update, and close events read-only", async () => {
    const { PositionTimelineView } = await loadModule();
    let engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    const nodes = descendants(PositionTimelineView({ model: buildReplayPositionTimelineModel(engine) }));
    const text = nodes.map(textOf).join(" ");
    for (const value of ["OPEN", "UPDATE", "CLOSE", "POSITION_OPENED", "POSITION_UPDATED", "POSITION_CLOSED",
        "TARGET_REACHED", "Data QualityVALID"]) assert.match(text, new RegExp(value));
    assert.equal(nodes.filter(({ type }) => type === "li").length, 3);
    assert.equal(nodes.filter(({ props }) => props?.["aria-current"] === "step").length, 1);
    assert.equal(nodes.some(({ props }) => typeof props?.onClick === "function" || props?.tabIndex !== undefined), false);
});
