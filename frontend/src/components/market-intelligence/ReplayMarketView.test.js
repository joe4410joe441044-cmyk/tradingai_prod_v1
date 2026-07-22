import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { buildReplayMarketViewModel } from "../../features/market-intelligence/replay/replayMarketViewModel.js";
import { buildReplayMarkerOverlayModel } from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const sourceUrl = new URL("./ReplayMarketView.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".replay-market-view-test-"));
    const output = join(temporary, "ReplayMarketView.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/replay/replayMarketViewModel.js")).href;
    const markerModelUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/replay/replayMarkerOverlayModel.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_MARKET_CONTEXT__";
    const labelsUrl = pathToFileURL(join(directory, "marketIntelligenceLabels.js")).href;
    const overlayStub = `data:text/javascript,export const PriceMarkerLayer=()=>null;export const TimeMarkerLayer=()=>null;export default()=>null`;
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayMarketViewModel.js";', `from "${modelUrl}";`)
        .replace('from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";', `from "${markerModelUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`)
        .replace('from "./ReplayMarkerOverlay.jsx";', `from "${overlayStub}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=market-view`);
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
    if (Array.isArray(children)) return children.map((child) => typeof child === "object" ? textOf(child) : String(child ?? "")).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("empty market view renders accessible sections and empty states", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const nodes = descendants(ReplayMarketViewContent({ model: buildReplayMarketViewModel(null) }));
    const text = nodes.map(textOf).join(" ");
    for (const heading of ["REPLAY MARKET VIEW", "Market Summary", "ORDER BOOK / DOM", "RECENT TRADES", "Market Metrics",
        "Data Quality", "Diagnostics"]) assert.match(text, new RegExp(heading));
    assert.match(text, /ORDER BOOK EMPTY（板情報なし）/);
    assert.match(text, /RECENT TRADES EMPTY/);
    assert.doesNotMatch(text, /Time Marker Overlay|NO TIME MARKERS/);
    assert.equal(nodes.some(({ props }) => props?.["aria-labelledby"] === "mi-market-view-title"), true);
    assert.equal(nodes.filter(({ type }) => type === "details").length, 2);
    assert.equal(nodes.filter(({ type }) => type === "details").every(({ props }) => props.open === undefined), true);
});

test("loaded market view renders tables, side labels, summaries, and quality", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const model = buildReplayMarketViewModel(engine);
    const nodes = descendants(ReplayMarketViewContent({ model, markerModel: buildReplayMarkerOverlayModel(engine, model) }));
    const text = nodes.map(textOf).join(" ");
    assert.equal(nodes.filter(({ type }) => type === "table").length, 3);
    for (const expected of ["ASK LEVELS", "BID LEVELS", "LAST", "VISIBLE DEPTH RATIO", "Price", "Size", "Time", "Side",
        "Marker", "VISIBLE TRADE FLOW", "KUCOIN", "FUTURES", "XRPUSDTM", "SAMPLE REPLAY", "CURRENT", "VALID"])
        assert.match(text, new RegExp(expected));
    assert.match(text, /Market Analysis Details/);
    assert.match(text, /Marker Details/);
    assert.doesNotMatch(text, /Time Marker Overlay|NO TIME MARKERS/);
    assert.equal(nodes.some(({ props }) => props?.className === "mi-order-book__marker" && textOf({ props }) === "BUY"), true);
});

test("the same market component renders an alternate normalized exchange source", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const base = buildReplayMarketViewModel(engine);
    const model = { ...base, source: { ...base.source, exchange: "TEST_EXCHANGE", marketType: "FUTURES",
        exchangeSymbol: "XRP-PERP", canonicalSymbol: "XRPUSDT", isSample: true } };
    const text = descendants(ReplayMarketViewContent({ model })).map(textOf).join(" ");
    for (const value of ["TEST_EXCHANGE", "FUTURES", "XRP-PERP"]) assert.match(text, new RegExp(value));
});

test("DOM display controls are local callbacks and marker rows remain read-only", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const modes = [];
    const limits = []; const tradeLimits = [];
    const nodes = descendants(ReplayMarketViewContent({ model: buildReplayMarketViewModel({ projection: {
        currentEvent: { payload: { value: { unsafe: true } } }, visibleEvents: [],
    } }), onDisplayModeChange: (mode) => modes.push(mode), onRowLimitChange: (limit) => limits.push(limit),
    onTradeRowLimitChange: (limit) => tradeLimits.push(limit) }));
    const buttons = nodes.filter(({ type }) => type === "button");
    assert.deepEqual(buttons.map(textOf), ["BOTH", "BIDS", "ASKS"]);
    assert.equal(buttons[0].props["aria-pressed"], true);
    buttons[1].props.onClick();
    const selects = nodes.filter(({ type }) => type === "select");
    selects[0].props.onChange({ target: { value: "50" } });
    selects[1].props.onChange({ target: { value: "100" } });
    assert.deepEqual(modes, ["BIDS"]);
    assert.deepEqual(limits, [50]);
    assert.deepEqual(tradeLimits, [100]);
    assert.equal(nodes.filter(({ props }) => props?.className === "mi-order-book__marker").every(({ props }) => props.onClick === undefined), true);
    assert.equal(nodes.some(({ props }) => props?.tabIndex !== undefined), false);
    for (const node of nodes) {
        const children = Array.isArray(node.props?.children) ? node.props.children : [node.props?.children];
        assert.equal(children.some((child) => child && typeof child === "object" && !child.type), false);
    }
});
