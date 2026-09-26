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
import { MI_LABELS, bilingual, bilingualSlash, bilingualSlashText } from "./marketIntelligenceLabels.js";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const sourceUrl = new URL("./ReplayMarketView.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".mi-g6-market-view-"));
    const output = join(temporary, "ReplayMarketView.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/replay/replayMarketViewModel.js")).href;
    const markerModelUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/replay/replayMarkerOverlayModel.js")).href;
    const marketAdapterUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/market/replayMarketAdapter.js")).href;
    const marketContextSelectionUrl = pathToFileURL(join(directory,
        "../../features/market-intelligence/market/marketContextSelection.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_MARKET_CONTEXT__";
    const labelsUrl = pathToFileURL(join(directory, "marketIntelligenceLabels.js")).href;
    const overlayStub = `data:text/javascript,export const PriceMarkerLayer=()=>null;export const TimeMarkerLayer=()=>null;export default()=>null`;
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayMarketViewModel.js";', `from "${modelUrl}";`)
        .replace('from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";', `from "${markerModelUrl}";`)
        .replace('from "../../features/market-intelligence/market/replayMarketAdapter.js";', `from "${marketAdapterUrl}";`)
        .replace('from "../../features/market-intelligence/market/marketContextSelection.js";', `from "${marketContextSelectionUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`)
        .replace('from "./marketIntelligenceLabels.js";', `from "${labelsUrl}";`)
        .replace('from "./ReplayMarkerOverlay.jsx";', `from "${overlayStub}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=g6-market-view`);
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
const renderText = (element) => descendants(element).map(textOf).join(" ");

const loadedModel = () => {
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    return buildReplayMarketViewModel(engine);
};

test("G6 label model exposes the preferred ENGLISH / 日本語 standard", () => {
    assert.equal(bilingualSlash("marketView"), "MARKET VIEW / 市場情報");
    assert.equal(bilingualSlash("currentPrice"), "CURRENT PRICE / 現在価格");
    assert.equal(bilingualSlash("bestBid"), "BEST BID / 最良買値");
    assert.equal(bilingualSlash("bestAsk"), "BEST ASK / 最良売値");
    assert.equal(bilingualSlash("spread"), "SPREAD / スプレッド");
    assert.equal(bilingualSlash("rows"), "ROWS / 行数");
    assert.equal(bilingualSlash("timeLocal"), "TIME (LOCAL) / 時刻");
    assert.equal(bilingualSlash("sideUpper"), "SIDE / 売買");
    assert.equal(bilingualSlashText("PRICE", "価格"), "PRICE / 価格");
    // established titles keep the compact parenthesis form
    assert.equal(bilingual("orderBook"), "ORDER BOOK / DOM（板情報）");
    assert.equal(bilingual("recentTrades"), "RECENT TRADES（約定履歴）");
    assert.equal(MI_LABELS.price[1], "価格");
});

test("G6 MARKET VIEW renders bilingual main labels", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const text = renderText(ReplayMarketViewContent({ model: buildReplayMarketViewModel(null) }));
    for (const label of [
        "MARKET VIEW / 市場情報", "CURRENT PRICE / 現在価格",
        "BEST BID / 最良買値", "BEST ASK / 最良売値", "SPREAD / スプレッド",
        "ORDER BOOK / DOM（板情報）", "RECENT TRADES（約定履歴）",
    ]) assert.ok(text.includes(label), `missing ${label}`);
});

test("G6 ORDER BOOK / DOM headers are bilingual", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const text = renderText(ReplayMarketViewContent({ model: loadedModel() }));
    for (const label of [
        "ASK LEVELS / 売板", "BID LEVELS / 買板",
        "Price / 価格", "Size / 数量", "Total / 累積", "Marker / マーカー",
        "BOTH / 両方", "BIDS / 買板", "ASKS / 売板", "ROWS / 行数",
    ]) assert.ok(text.includes(label), `missing ${label}`);
});

test("G6 RECENT TRADES headers are bilingual", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const text = renderText(ReplayMarketViewContent({ model: loadedModel() }));
    for (const label of [
        "TIME (LOCAL) / 時刻", "PRICE / 価格", "SIZE / 数量", "SIDE / 売買", "MARKER / マーカー",
    ]) assert.ok(text.includes(label), `missing ${label}`);
});

test("G6 preserves dynamic values and machine identifiers", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const model = loadedModel();
    const text = renderText(ReplayMarketViewContent({ model, markerModel: buildReplayMarkerOverlayModel(null, model) }));
    for (const value of ["XRPUSDTM", "KUCOIN", "FUTURES", "BUY", "SELL", "BID", "ASK"])
        assert.ok(text.includes(value), `missing preserved value ${value}`);
    // Japanese accompaniment must not replace the raw side values.
    assert.doesNotMatch(text, /買い（BUY）|売り（SELL）/);
});
