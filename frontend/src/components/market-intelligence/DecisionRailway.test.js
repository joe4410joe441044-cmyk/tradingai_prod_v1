import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";
import { buildDecisionRailwayModel } from "../../features/market-intelligence/replay/decisionRailwayModel.js";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";

const componentDirectory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const sourceUrl = new URL("./DecisionRailway.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(componentDirectory, ".decision-railway-test-"));
    const output = join(temporary, "DecisionRailway.mjs");
    const modelUrl = pathToFileURL(join(componentDirectory,
        "../../features/market-intelligence/replay/decisionRailwayModel.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_RAILWAY_CONTEXT__";
    const labelsUrl = pathToFileURL(join(componentDirectory, "marketIntelligenceLabels.js")).href;
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/decisionRailwayModel.js";',
            `from "${modelUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";',
            `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=railway`);
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
    if (Array.isArray(children)) return children.map((child) => (
        typeof child === "object" ? textOf(child) : String(child ?? "")
    )).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("empty railway is compact and remains read-only", async () => {
    const { DecisionFinalSummary, DecisionRailwayView } = await loadModule();
    const model = buildDecisionRailwayModel(createInitialReplayEngineState());
    const nodes = descendants(DecisionRailwayView({ model }));
    assert.equal(nodes.filter(({ type }) => type === "article").length, 0);
    assert.equal(nodes.filter(({ type }) => type === "h3").length, 0);
    assert.equal(nodes.some((node) => textOf(node).includes("Load a replay dataset")), true);
    assert.equal(nodes.some(({ type }) => type === "button"), false);
    assert.equal(nodes.some(({ props }) => typeof props?.onClick === "function"), false);
    assert.equal(nodes.some(({ props }) => props?.tabIndex !== undefined), false);
    assert.doesNotMatch(nodes.map(textOf).join(" "), /QUALITY UNKNOWN/);
    const noReplay = descendants(DecisionFinalSummary({ model })).map(textOf).join(" ");
    assert.match(noReplay, /NO DECISION DATA/);
    assert.match(noReplay, /Load a replay to inspect the AI decision/);
    assert.doesNotMatch(noReplay, /UNKNOWN（未判定）/);
    assert.match(descendants(DecisionFinalSummary({ hasReplay: true, model })).map(textOf).join(" "),
        /NO DECISION AT CURRENT CURSOR/);
    assert.match(descendants(DecisionFinalSummary({ hasError: true, model })).map(textOf).join(" "), /UNKNOWN/);
});

test("loaded railway renders final summary and exactly one active station", async () => {
    const { DecisionRailwayView } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const nodes = descendants(DecisionRailwayView({ model: buildDecisionRailwayModel(engine) }));
    assert.equal(nodes.filter(({ props }) => props?.["aria-current"] === "step").length, 1);
    const text = nodes.map(textOf).join(" ");
    assert.match(text, /DECISION RAILWAY/);
    assert.match(text, /Market Data/);
    assert.match(text, /Python Detectors/);
    assert.match(text, /NOT REACHED/);
    assert.match(text, /XRPUSDTM/);
});

test("completed fixture safely renders execution and decision values", async () => {
    const { DecisionRailwayView } = await loadModule();
    let engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    const nodes = descendants(DecisionRailwayView({ model: buildDecisionRailwayModel(engine) }));
    const text = nodes.map(textOf).join(" ");
    assert.match(text, /BUY/);
    assert.match(text, /APPROVED/);
    assert.match(text, /ACKNOWLEDGED/);
    assert.equal(nodes.filter(({ type }) => type === "article").length, 7);
});
