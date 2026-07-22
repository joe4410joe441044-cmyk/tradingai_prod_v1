import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { buildReplayInspectorModel } from "../../features/market-intelligence/replay/replayInspectorModel.js";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const sourceUrl = new URL("./ReplayInspector.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".replay-inspector-test-"));
    const output = join(temporary, "ReplayInspector.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/replay/replayInspectorModel.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_INSPECTOR_CONTEXT__";
    const labelsUrl = pathToFileURL(join(directory, "marketIntelligenceLabels.js")).href;
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayInspectorModel.js";',
            `from "${modelUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";',
            `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=inspector`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};
const textOf = (node) => {
    const children = node?.props?.children;
    if (Array.isArray(children)) return children.map((child) => (
        typeof child === "object" ? textOf(child) : String(child ?? "")
    )).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("empty inspector stays compact without rendering advanced field grids", async () => {
    const { ReplayInspectorView } = await loadModule();
    const nodes = descendants(ReplayInspectorView({
        model: buildReplayInspectorModel(createInitialReplayEngineState()),
    }));
    const text = nodes.map(textOf).join(" ");
    assert.match(text, /NO CURRENT EVENT（現在イベントなし）/);
    assert.equal(nodes.some(({ type }) => type === "details"), false);
    assert.doesNotMatch(text, /Position Context/);
    assert.doesNotMatch(text, /Station Context/);
});

test("loaded inspector displays current, adjacent, context, marker, and station data", async () => {
    const { ReplayInspectorView } = await loadModule();
    let engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    const nodes = descendants(ReplayInspectorView({ model: buildReplayInspectorModel(engine) }));
    const text = nodes.map(textOf).join(" ");
    const details = nodes.find(({ type }) => type === "details");
    assert.equal(details.props.open, undefined);
    assert.match(text, /Replay Inspector Details/);
    assert.match(text, /Final Decision/);
    assert.match(text, /POSITION_CLOSED/);
    assert.match(text, /replay-event-010/);
    assert.match(text, /CLOSED/);
    assert.match(text, /marker-position-closed/);
    assert.match(text, /Execution/);
    assert.match(text, /VALID/);
});

test("inspector is strictly read-only and renders only safe child values", async () => {
    const { ReplayInspectorView } = await loadModule();
    const model = buildReplayInspectorModel({
        projection: { currentEvent: { payload: { object: { unsafe: true }, array: [1, 2] } } },
    });
    const nodes = descendants(ReplayInspectorView({ model }));
    assert.equal(nodes.some(({ type }) => type === "button" || type === "input"), false);
    assert.equal(nodes.some(({ props }) => typeof props?.onClick === "function"), false);
    assert.equal(nodes.some(({ props }) => props?.tabIndex !== undefined), false);
    for (const node of nodes) {
        const children = Array.isArray(node.props?.children) ? node.props.children : [node.props?.children];
        assert.equal(children.some((child) => child && typeof child === "object" && !child.type), false);
    }
});
