import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { buildReplayMarketViewModel } from "../../features/market-intelligence/replay/replayMarketViewModel.js";
import { buildReplayMarkerOverlayModel, reconcileMarkerUiSelection, resolveSelectedMarker } from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";

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
    for (const heading of ["MARKET VIEW", "CURRENT PRICE", "SPREAD", "ORDER BOOK / DOM", "RECENT TRADES", "Market Metrics",
        "Data Quality", "Diagnostics"]) assert.match(text, new RegExp(heading));
    assert.match(text, /NO MARKET SELECTED/);
    assert.match(text, /NO MARKET SELECTED/);
    assert.doesNotMatch(text, /UNKNOWN \/ UNKNOWN|NO REPLAY SELECTED/);
    assert.equal(nodes.filter(({ type }) => type === "select").length, 0);
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
    for (const expected of ["ASK LEVELS", "BID LEVELS", "LAST", "VISIBLE DEPTH RATIO", "Price", "Size", "TIME", "SIDE",
        "Marker", "VISIBLE TRADE FLOW", "KUCOIN", "FUTURES", "XRPUSDTM", "REPLAY", "CURRENT", "VALID"])
        assert.match(text, new RegExp(expected));
    assert.match(text, /Market Analysis Details/);
    assert.match(text, /Marker Details/);
    assert.doesNotMatch(text, /Time Marker Overlay|NO TIME MARKERS/);
    assert.equal(nodes.some(({ props }) => props?.className === "mi-order-book__marker"
        && props["aria-label"] === "BUY at 0.6123" && textOf({ props }) === "B"), true);
});

test("the same market component renders an alternate normalized exchange source", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const base = buildReplayMarketViewModel(engine);
    const model = { ...base,
        source: { ...base.source, exchange: "TEST_EXCHANGE", marketType: "SPOT",
            exchangeSymbol: "XRP-PERP", canonicalSymbol: "XRPUSDT", isSample: true },
        marketContext: { ...base.marketContext, exchange: "TEST_EXCHANGE", marketType: "SPOT",
            displaySymbol: "XRP-PERP", normalizedSymbol: "XRPUSDT" },
        currentPriceSummary: { ...base.currentPriceSummary, exchange: "TEST_EXCHANGE", marketType: "SPOT",
            displaySymbol: "XRP-PERP" } };
    const text = descendants(ReplayMarketViewContent({ model })).map(textOf).join(" ");
    for (const value of ["TEST_EXCHANGE", "SPOT", "XRP-PERP"]) assert.match(text, new RegExp(value));
});

test("DOM display controls are local callbacks and marker rows remain read-only", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const modes = [];
    const limits = []; const tradeLimits = [];
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const nodes = descendants(ReplayMarketViewContent({ model: buildReplayMarketViewModel(engine),
        onDisplayModeChange: (mode) => modes.push(mode), onRowLimitChange: (limit) => limits.push(limit),
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

test("DOM renders loading, unavailable, and one-sided states without inferred levels", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const base = buildReplayMarketViewModel(null);
    const render = (orderBook, summaryState = "WAITING") => descendants(ReplayMarketViewContent({
        model: { ...base, isEmpty: false, currentPriceSummary: { ...base.currentPriceSummary, state: summaryState },
            orderBook: { ...base.orderBook, ...orderBook } },
    })).map(textOf).join(" ");
    assert.match(render({ state: "LOADING" }, "LOADING"), /LOADING MARKET DATA/);
    assert.match(render({ state: "UNAVAILABLE" }, "UNAVAILABLE"), /ORDER BOOK UNAVAILABLE/);
    const askOnly = render({ state: "PARTIAL", hasData: true,
        asks: [{ id: "ask", side: "ASK", price: "2", size: "1", cumulativeSize: "1",
            numericPrice: 2, numericSize: 1 }], bids: [] });
    assert.match(askOnly, /2 ASK/);
    assert.match(askOnly, /NO BID DATA/);
    assert.doesNotMatch(askOnly, /NO ASK DATA/);
});

test("recent trades render formal columns, row limits, and explicit empty states", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const base = buildReplayMarketViewModel(null);
    const render = (state) => descendants(ReplayMarketViewContent({ model: { ...base,
        marketContext: { ...base.marketContext, key: state === "NO MARKET SELECTED" ? null : "market" },
        recentTrades: { ...base.recentTrades, state },
    } })).map(textOf).join(" ");
    assert.match(render("NO MARKET SELECTED"), /NO MARKET SELECTED/);
    assert.match(render("WAITING"), /WAITING FOR TRADE DATA/);
    assert.match(render("LOADING"), /LOADING TRADE DATA/);
    assert.match(render("NO TRADES"), /NO TRADES/);
    assert.match(render("UNAVAILABLE"), /TRADE DATA UNAVAILABLE/);

    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const nodes = descendants(ReplayMarketViewContent({ model: buildReplayMarketViewModel(engine) }));
    const tradeTable = nodes.filter(({ type }) => type === "table")[2];
    const tableText = textOf(tradeTable);
    assert.match(tableText, /TIMEPRICESIZESIDE/);
    assert.match(tableText, /BUY|SELL/);
    const tradeSelect = nodes.filter(({ type }) => type === "select")[1];
    assert.deepEqual(descendants(tradeSelect).filter(({ type }) => type === "option").map(({ props }) => props.value), [10, 20, 50]);
    assert.equal(tradeSelect.props.value, 20);
});

test("multiple DOM markers are compact, accessible, ordered, and report the remainder", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const model = buildReplayMarketViewModel(engine);
    const item = (id, type, timestamp, sequence) => ({
        id, displayKey: id, type, timestamp, sequence, numericPrice: 0.6123, domPrice: 0.6123,
        priceMatch: true, label: type, shortLabel: type[0], accessibilityLabel: `${type} at 0.6123`,
    });
    const markers = [item("m4", "EXIT", "2026-01-01T00:00:04Z", 4),
        item("m3", "SELL", "2026-01-01T00:00:03Z", 3), item("m2", "BUY", "2026-01-01T00:00:02Z", 2),
        item("m1", "BUY", "2026-01-01T00:00:01Z", 1)];
    const markerModel = { markers, priceMarkers: markers, domMarkers: markers, maxInlineMarkers: 3,
        domMarkerGroups: [{ price: 0.6123, markers, visibleMarkers: markers.slice(0, 3), remainingCount: 1 }] };
    const nodes = descendants(ReplayMarketViewContent({ model, markerModel }));
    const badges = nodes.filter(({ props }) => props?.className === "mi-order-book__marker");
    assert.equal(badges.some(({ props }) => props["aria-label"] === "EXIT at 0.6123"
        && props.title === "EXIT at 0.6123"), true);
    assert.equal(nodes.some(({ props }) => props?.className === "mi-marker-stack__more"
        && textOf({ props }) === "+1"), true);
    assert.equal(badges.every(({ type, props }) => type === "button" && props.type === "button"), true);
});

test("DOM and trade marker buttons select the same marker id without making rows interactive", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const model = buildReplayMarketViewModel(engine);
    const markerModel = buildReplayMarkerOverlayModel(engine, model);
    const selected = [];
    const nodes = descendants(ReplayMarketViewContent({ model, markerModel,
        onMarkerSelect: (id) => selected.push(id), selectedMarkerId: markerModel.markers[0].id }));
    const badges = nodes.filter(({ props }) => props?.className === "mi-order-book__marker");
    assert.equal(badges.length, 2);
    assert.equal(badges.every(({ props }) => props.type === "button" && props.tabIndex === undefined), true);
    assert.equal(badges.every(({ props }) => props["aria-pressed"] === true), true);
    badges.forEach(({ props }) => props.onClick());
    assert.deepEqual(selected, [markerModel.markers[0].id, markerModel.markers[0].id]);
    assert.equal(nodes.filter(({ type }) => type === "tr").every(({ props }) => props.onClick === undefined
        && props.tabIndex === undefined), true);
});

test("expanded marker groups expose every marker and close with aria-expanded", async () => {
    const { ReplayMarketViewContent } = await loadModule();
    const engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const model = buildReplayMarketViewModel(engine);
    const item = (index) => ({ id: `m${index}`, displayKey: `m${index}`, shortLabel: index % 2 ? "S" : "B",
        accessibilityLabel: `${index % 2 ? "SELL" : "BUY"} at 0.6123` });
    const markers = Array.from({ length: 6 }, (_, index) => item(index));
    const markerModel = { markers, domMarkerGroups: [{ price: 0.6123, markers,
        visibleMarkers: markers.slice(0, 3), remainingCount: 3 }] };
    const toggled = [];
    const collapsed = descendants(ReplayMarketViewContent({ model, markerModel,
        onMarkerGroupToggle: (key) => toggled.push(key) }));
    const openButton = collapsed.find(({ props }) => props?.className === "mi-marker-stack__more");
    assert.equal(openButton.props["aria-expanded"], false);
    assert.match(openButton.props["aria-label"], /Show 3 additional markers/);
    openButton.props.onClick();
    assert.deepEqual(toggled, ["dom:0.6123"]);
    assert.equal(collapsed.filter(({ props }) => props?.className === "mi-order-book__marker").length, 3);
    const expanded = descendants(ReplayMarketViewContent({ expandedMarkerGroupKey: "dom:0.6123",
        model, markerModel, onMarkerGroupToggle: (key) => toggled.push(key) }));
    assert.equal(expanded.filter(({ props }) => props?.className === "mi-order-book__marker").length, 6);
    const closeButton = expanded.find(({ props }) => props?.className === "mi-marker-stack__more");
    assert.equal(closeButton.props["aria-expanded"], true);
    assert.equal(textOf(closeButton), "CLOSE");
    closeButton.props.onClick();
    assert.deepEqual(toggled, ["dom:0.6123", "dom:0.6123"]);
});

test("marker inspector resolves current model data and reuses market formatters", async () => {
    const { MarkerInspector } = await loadModule();
    const marker = { id: "selected", label: "BUY ENTRY", timestamp: "2026-01-01T12:30:05.321Z",
        numericPrice: 1.2, side: "BUY", numericQuantity: 8, source: "STRATEGY", dataQuality: "VALID",
        reason: "A".repeat(200), orderId: "order-" + "x".repeat(100), eventId: "event-1",
        tradeId: "trade-1", decisionId: "decision-1", positionId: "position-1", sequence: 42,
        reduceOnly: false, flatten: false, blocked: false, failed: false };
    const nodes = descendants(MarkerInspector({ marker, marketContext: {
        pricePrecision: 4, tickSize: 0.0001, quantityPrecision: 2, lotSize: 0.01,
    } }));
    const text = nodes.map(textOf).join(" ");
    for (const expected of ["MARKER INSPECTOR", "BUY ENTRY", "Timestamp", "2026-01-01T12:30:05.321Z",
        "Price", "1.2000", "Side", "BUY", "Quantity", "8.00", "Source", "STRATEGY",
        "Data Quality", "VALID", "Reason", "Order ID", "Event ID", "Trade ID", "Decision ID",
        "Position ID", "Sequence", "42", "Reduce Only", "NO", "Flatten", "Blocked", "Failed"])
        assert.match(text, new RegExp(expected));
    assert.equal(nodes.some(({ props }) => props?.title === marker.reason), true);
    assert.equal(nodes.some(({ props }) => props?.title === marker.orderId), true);
});

test("empty and UNKNOWN marker inspectors remain explicit without inferred optional fields", async () => {
    const { MarkerInspector } = await loadModule();
    const emptyText = descendants(MarkerInspector({ marker: null, marketContext: {} })).map(textOf).join(" ");
    assert.match(emptyText, /SELECT A MARKER/);
    const marker = { id: "unknown", label: "UNKNOWN", timestamp: "—", numericPrice: null,
        side: "—", numericQuantity: null, source: "SYSTEM", dataQuality: "UNKNOWN" };
    const nodes = descendants(MarkerInspector({ marker, marketContext: {} }));
    const text = nodes.map(textOf).join(" ");
    assert.match(text, /UNKNOWN/);
    for (const required of ["Timestamp", "Price", "Side", "Quantity", "Source", "Data Quality"])
        assert.match(text, new RegExp(required));
    assert.doesNotMatch(text, /Reason|Order ID|Reduce Only/);
});

test("selection reconciliation clears context changes and missing markers but keeps live updates by id", async () => {
    await loadModule();
    const old = { id: "same", label: "BUY", markers: undefined };
    const updated = { id: "same", label: "SELL" };
    const markerModel = { markers: [updated], domMarkerGroups: [{ price: 1 }] };
    assert.equal(resolveSelectedMarker(markerModel, "same"), updated);
    assert.deepEqual(reconcileMarkerUiSelection({ currentContextKey: "btc", expandedMarkerGroupKey: "dom:1",
        markerModel, previousContextKey: "xrp", selectedMarkerId: "same" }), {
        expandedMarkerGroupKey: null, selectedMarkerId: null,
    });
    assert.deepEqual(reconcileMarkerUiSelection({ currentContextKey: "btc", expandedMarkerGroupKey: "dom:1",
        markerModel, previousContextKey: "btc", selectedMarkerId: "same" }), {
        expandedMarkerGroupKey: "dom:1", selectedMarkerId: "same",
    });
    assert.deepEqual(reconcileMarkerUiSelection({ currentContextKey: "btc", expandedMarkerGroupKey: "dom:2",
        markerModel, previousContextKey: "btc", selectedMarkerId: "missing" }), {
        expandedMarkerGroupKey: null, selectedMarkerId: null,
    });
    assert.equal(old.label, "BUY");
});
