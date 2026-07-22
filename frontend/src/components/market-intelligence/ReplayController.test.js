import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

import {
    REPLAY_ENGINE_COMMANDS as C,
    applyReplayCommand,
    createInitialReplayEngineState,
} from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { buildReplayControllerModel } from "../../features/market-intelligence/replay/replayControllerModel.js";

const componentDirectory = dirname(fileURLToPath(import.meta.url));

const loadControllerModule = async () => {
    const sourceUrl = new URL("./ReplayController.jsx", import.meta.url);
    const source = await readFile(sourceUrl, "utf8");
    const transformed = await transformWithOxc(source, fileURLToPath(sourceUrl));
    const tempDirectory = await mkdtemp(join(componentDirectory, ".replay-controller-test-"));
    const outputPath = join(tempDirectory, "ReplayController.mjs");
    const replayDirectory = join(componentDirectory, "../../features/market-intelligence/replay");
    const engineUrl = pathToFileURL(join(replayDirectory, "replayEngine.js")).href;
    const fixtureUrl = pathToFileURL(join(replayDirectory, "replayFixtures.js")).href;
    const modelUrl = pathToFileURL(join(replayDirectory, "replayControllerModel.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_TEST_CONTEXT__";
    const labelsUrl = pathToFileURL(join(componentDirectory, "marketIntelligenceLabels.js")).href;
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayEngine.js";',
            `from "${engineUrl}";`)
        .replace('from "../../features/market-intelligence/replay/replayFixtures.js";',
            `from "${fixtureUrl}";`)
        .replace('from "../../features/market-intelligence/replay/replayControllerModel.js";',
            `from "${modelUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";',
            `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`);
    try {
        await writeFile(outputPath, code);
        return await import(`${pathToFileURL(outputPath).href}?test=controller`);
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

test("initial controller view is safe, accessible, and does not auto-load", async () => {
    const { ReplayControllerView } = await loadControllerModule();
    const commands = [];
    const model = buildReplayControllerModel(createInitialReplayEngineState());
    const view = ReplayControllerView({
        model,
        seekPercent: 0,
        seekTimestamp: null,
        onSeekPercentChange() {},
        onCommand: (...args) => commands.push(args),
    });
    const nodes = descendants(view);
    const buttons = nodes.filter(({ type }) => type === "button");
    const byLabel = Object.fromEntries(buttons.map((button) => [textOf(button), button]));
    assert.equal(textOf(nodes.find(({ props }) => props?.id === "mi-replay-controller-title")),
        "REPLAY CONTROLLER（リプレイ操作）");
    assert.equal(nodes.some((node) => textOf(node) === "IDLE"), true);
    assert.equal(byLabel["LOAD SAMPLE REPLAY（サンプル読込）"].props.disabled, false);
    assert.deepEqual(Object.keys(byLabel), ["LOAD SAMPLE REPLAY（サンプル読込）"]);
    assert.equal(nodes.some(({ type }) => type === "input"), false);
    assert.deepEqual(commands, []);
});

test("load button emits the fixture command through the supplied command path", async () => {
    const { ReplayControllerView } = await loadControllerModule();
    const commands = [];
    const view = ReplayControllerView({
        model: buildReplayControllerModel(createInitialReplayEngineState()),
        seekPercent: 0,
        seekTimestamp: null,
        onSeekPercentChange() {},
        onCommand: (...args) => commands.push(args),
    });
    const loadButton = descendants(view).find((node) => (
        node.type === "button" && textOf(node) === "LOAD SAMPLE REPLAY（サンプル読込）"
    ));
    loadButton.props.onClick();
    assert.deepEqual(commands, [[C.LOAD_DATASET, { dataset: XRP_REPLAY_FIXTURE }]]);
});

test("loaded and playing views expose state, summary, controls, and manual mode notice", async () => {
    const { ReplayControllerView } = await loadControllerModule();
    const loaded = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET,
        payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const playing = applyReplayCommand(loaded, { type: C.PLAY });
    const view = ReplayControllerView({
        model: buildReplayControllerModel(playing),
        seekPercent: 50,
        seekTimestamp: "2026-07-20T12:00:45.000Z",
        onSeekPercentChange() {},
        onCommand() {},
    });
    const nodes = descendants(view);
    const allText = nodes.map(textOf).join(" ");
    assert.match(allText, /PLAYING/);
    assert.match(allText, new RegExp(XRP_REPLAY_FIXTURE.datasetId));
    assert.match(allText, /MARKET_SNAPSHOT/);
    assert.match(allText, /Automatic advancement is not enabled/);
    const buttons = nodes.filter(({ type }) => type === "button");
    const byLabel = Object.fromEntries(buttons.map((button) => [textOf(button), button]));
    assert.equal(byLabel["PAUSE（一時停止）"].props.disabled, false);
    assert.equal(byLabel["PLAY（再生）"].props.disabled, true);
    assert.equal(byLabel["STEP FORWARD（1ステップ進む）"].props.disabled, true);
    assert.equal(byLabel["SEEK（移動）"].props.disabled, false);
});
