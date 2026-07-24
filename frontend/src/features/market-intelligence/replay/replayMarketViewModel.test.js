import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { buildOrderBookDomDisplay, buildRecentTradesDisplay, buildReplayMarketViewModel, marketContextKey, marketDisplayValue, marketTimestamp, normalizedTradeTime, normalizeMarketSide } from "./replayMarketViewModel.js";

const load = () => applyReplayCommand(createInitialReplayEngineState(), {
    type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
});

const liveModel = (overrides = {}) => ({
    context: {
        exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM",
        normalizedSymbol: "XRPUSDT", displaySymbol: "XRPUSDTM",
        contextKey: "KUCOIN:FUTURES:XRPUSDTM",
    },
    source: { mode: "LIVE", provider: "RUNTIME_WEBSOCKET" },
    status: "READY",
    price: { current: 100, bestBid: 99, bestAsk: 101, spread: 2 },
    orderBook: {
        timestamp: "2026-07-24T00:00:00.000Z", sequence: 42, depth: 2,
        bids: [
            { price: 99, quantity: 3, cumulativeSize: 3 },
            { price: 98, quantity: 4, cumulativeSize: 7 },
        ],
        asks: [
            { price: 101, quantity: 2, cumulativeSize: 2 },
            { price: 102, quantity: 5, cumulativeSize: 7 },
        ],
        dataQuality: "VALID", syncState: "SYNCED",
    },
    recentTrades: [],
    markers: [],
    dataQuality: { issues: [], isStale: false },
    ...overrides,
});

test("LIVE normalized order book is the final DOM authority with formal cumulative values", () => {
    const model = buildReplayMarketViewModel(null, liveModel());

    assert.equal(model.orderBook.state, "AVAILABLE");
    assert.deepEqual(model.orderBook.asks.map(({ numericPrice }) => numericPrice), [101, 102]);
    assert.deepEqual(model.orderBook.bids.map(({ numericPrice }) => numericPrice), [99, 98]);
    assert.deepEqual(model.orderBook.asks.map(({ size, cumulativeSize }) => [size, cumulativeSize]),
        [["2", "2"], ["5", "7"]]);
    assert.deepEqual(model.orderBook.bids.map(({ size, cumulativeSize }) => [size, cumulativeSize]),
        [["3", "3"], ["4", "7"]]);
    assert.equal(model.orderBook.bestAsk, "101");
    assert.equal(model.orderBook.bestBid, "99");
    assert.equal(model.orderBook.timestamp, "2026-07-24T00:00:00.000Z");
    assert.equal(model.orderBook.sequence, 42);
    assert.equal(model.orderBook.sourceDepth, 2);
    assert.equal(model.orderBook.dataQuality, "VALID");
    assert.equal(model.orderBook.syncState, "SYNCED");
});

test("Replay Projection book stays authoritative while a LIVE book exists", () => {
    const model = buildReplayMarketViewModel(load(), liveModel());

    assert.equal(model.orderBook.bestAsk, "0.6125");
    assert.equal(model.orderBook.bestBid, "0.6123");
    assert.equal(model.orderBook.asks.length, 12);
    assert.equal(model.orderBook.bids.length, 12);
    assert.equal(model.orderBook.asks.some(({ numericPrice }) => numericPrice === 101), false);
});

test("LIVE book quality and context transitions never expose an unsafe prior DOM", () => {
    const stale = liveModel({
        status: "STALE",
        orderBook: { ...liveModel().orderBook, dataQuality: "STALE" },
        dataQuality: { issues: ["SOURCE_STALE"], isStale: true },
    });
    assert.equal(buildReplayMarketViewModel(null, stale).orderBook.state, "AVAILABLE");
    assert.equal(buildReplayMarketViewModel(null, stale).orderBook.bids.length, 2);

    for (const unsafe of [
        liveModel({ status: "UNAVAILABLE", orderBook: {
            ...liveModel().orderBook, bids: [], asks: [], depth: 0,
            dataQuality: "UNAVAILABLE", syncState: "UNAVAILABLE",
        } }),
        liveModel({ status: "INVALID", orderBook: {
            ...liveModel().orderBook, dataQuality: "INVALID", syncState: "UNSYNCED",
        } }),
    ]) {
        const model = buildReplayMarketViewModel(null, unsafe);
        assert.equal(model.orderBook.state, "UNAVAILABLE");
    }

    const changedContext = liveModel({
        context: {
            exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "BTCUSDTM",
            normalizedSymbol: "BTCUSDT", displaySymbol: "BTCUSDTM",
            contextKey: "KUCOIN:FUTURES:BTCUSDTM",
        },
        status: "WAITING",
        price: { current: null, bestBid: null, bestAsk: null, spread: null },
        orderBook: { asks: [], bids: [] },
    });
    const waiting = buildReplayMarketViewModel(null, changedContext);
    assert.equal(waiting.marketContext.exchangeSymbol, "BTCUSDTM");
    assert.equal(waiting.orderBook.state, "WAITING");
    assert.equal(waiting.orderBook.hasData, false);
});

test("empty and malformed engines produce a safe market model", () => {
    for (const engine of [null, {}, { projection: null }, { projection: { visibleEvents: null } }]) {
        const model = buildReplayMarketViewModel(engine);
        assert.equal(model.isEmpty, true);
        assert.equal(model.orderBook.asks.length, 0);
        assert.equal(model.recentTrades.rows.length, 0);
        assert.equal(model.header.markPrice, "—");
        assert.equal(model.quality.market, "UNKNOWN");
    }
});

test("fixture market snapshot builds header, book, trades, metrics, and quality", () => {
    const model = buildReplayMarketViewModel(load());
    assert.equal(model.header.symbol, "XRPUSDTM");
    assert.equal(model.header.exchange, "KUCOIN");
    assert.deepEqual(model.source, { exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM",
        canonicalSymbol: "XRPUSDT", displaySymbol: "UNKNOWN", sourceMode: "REPLAY",
        pricePrecision: null, tickSize: null, quantityPrecision: null, lotSize: null, isSample: true });
    assert.equal(model.header.timestamp, XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(model.header.markPrice, "0.6124");
    assert.equal(model.orderBook.asks.length, 12);
    assert.equal(model.orderBook.bids.length, 12);
    assert.equal(model.orderBook.bestAsk, "0.6125");
    assert.equal(model.orderBook.bestBid, "0.6123");
    assert.equal(model.orderBook.asks.at(-2).optionalTotal, "340");
    assert.equal(model.orderBook.asks.at(-1).price, "0.6125");
    assert.equal(model.orderBook.bids[0].price, "0.6123");
    assert.equal(model.recentTrades.rows.length, 21);
    assert.equal(model.recentTrades.rows[0].tradeId, "trade-current");
    assert.equal(model.recentTrades.rows[1].tradeId, "trade-same-time-low");
    assert.equal(model.metrics.buyPressure, "0.58");
    assert.equal(model.quality.orderBook, "VALID");
    assert.deepEqual(model.marketContext, {
        exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM", displaySymbol: "XRPUSDTM",
        normalizedSymbol: "XRPUSDT", pricePrecision: null, tickSize: null,
        quantityPrecision: null, lotSize: null, key: marketContextKey(model.source),
    });
    assert.deepEqual(model.currentPriceSummary, {
        exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM",
        normalizedSymbol: "XRPUSDT", displaySymbol: "XRPUSDTM", currentPrice: "0.6124",
        bestBid: "0.6123", bestAsk: "0.6125", spread: "0.0002", state: "REPLAY",
    });
});

test("spot context drives header, price, book, and trades without fixed venue or symbol", () => {
    const snapshot = { id: "binance-btc", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z",
        dataQuality: "VALID", payload: { marketSource: {
            exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT",
            canonicalSymbol: "BTCUSDT", sourceMode: "REPLAY",
        }, lastTradePrice: 100, orderBook: { asks: [[101, 2]], bids: [[99, 3]] },
        trades: [{ tradeId: "btc-trade", timestamp: "2026-01-01T00:00:00Z", side: "BUY", price: 100, quantity: 1 }] } };
    const model = buildReplayMarketViewModel({ projection: {
        currentEvent: snapshot, visibleEvents: [snapshot], dataQuality: "VALID",
    } });
    assert.deepEqual(model.marketContext, { exchange: "BINANCE", marketType: "SPOT",
        exchangeSymbol: "BTCUSDT", displaySymbol: "BTCUSDT", normalizedSymbol: "BTCUSDT",
        pricePrecision: null, tickSize: null, quantityPrecision: null, lotSize: null,
        key: "BINANCE\u0000SPOT\u0000BTCUSDT" });
    assert.equal(model.header.currentPrice, "100");
    assert.equal(model.orderBook.bestAsk, "101");
    assert.equal(model.orderBook.bestBid, "99");
    assert.equal(model.recentTrades.rows[0].tradeId, "btc-trade");
});

test("current price summary uses formal display identity, precision, and LIVE mode", () => {
    const snapshot = { id: "live", eventType: "MARKET_SNAPSHOT", dataQuality: "VALID", payload: {
        marketSource: { exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT",
            canonicalSymbol: "BTCUSDT", displaySymbol: "BTC / USDT", sourceMode: "LIVE", pricePrecision: 2 },
        lastTradePrice: 100, orderBook: { bids: [[99.5, 1]], asks: [[100.5, 1]] },
    } };
    const model = buildReplayMarketViewModel({ projection: { currentEvent: snapshot,
        visibleEvents: [snapshot], dataQuality: "VALID" } });
    assert.equal(model.marketContext.exchangeSymbol, "BTCUSDT");
    assert.equal(model.marketContext.normalizedSymbol, "BTCUSDT");
    assert.equal(model.currentPriceSummary.displaySymbol, "BTC / USDT");
    assert.equal(model.currentPriceSummary.currentPrice, "100.00");
    assert.equal(model.currentPriceSummary.bestBid, "99.50");
    assert.equal(model.currentPriceSummary.spread, "1.00");
    assert.equal(model.header.currentPrice, "100.00");
    assert.equal(model.orderBook.bestBid, "99.50");
    assert.equal(model.orderBook.bestAsk, "100.50");
    assert.equal(model.orderBook.spread, "1.00");
    assert.equal(model.orderBook.midpoint, "100.00");
    assert.equal(model.orderBook.bids[0].price, model.orderBook.bestBid);
    assert.equal(model.orderBook.asks.at(-1).price, model.orderBook.bestAsk);
    assert.equal(model.currentPriceSummary.state, "LIVE");
});

test("summary states distinguish no context, waiting, loading, stale, and unavailable", () => {
    assert.equal(buildReplayMarketViewModel(null).currentPriceSummary.state, "NO MARKET SELECTED");
    const contextOnly = { id: "context", eventType: "MARKET_SNAPSHOT", payload: { marketSource: {
        exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT", canonicalSymbol: "BTCUSDT",
        displaySymbol: "BTC / USDT", sourceMode: "LIVE",
    } } };
    const waiting = buildReplayMarketViewModel({ projection: { currentEvent: contextOnly, visibleEvents: [contextOnly] } });
    assert.equal(waiting.currentPriceSummary.state, "WAITING");
    assert.equal(waiting.isEmpty, true);
    assert.equal(waiting.currentPriceSummary.displaySymbol, "BTC / USDT");
    assert.equal(waiting.currentPriceSummary.currentPrice, "—");
    const loading = buildReplayMarketViewModel({ machine: { state: "REPLAY_LOADING" }, projection: {
        currentEvent: contextOnly, visibleEvents: [contextOnly],
    } });
    assert.equal(loading.currentPriceSummary.state, "LOADING");
    const stale = { ...contextOnly, payload: { ...contextOnly.payload, lastTradePrice: 10 } };
    assert.equal(buildReplayMarketViewModel({ projection: { currentEvent: stale, visibleEvents: [stale],
        dataQuality: "STALE" } }).currentPriceSummary.state, "STALE");
    const invalid = { ...contextOnly, payload: { ...contextOnly.payload, lastTradePrice: Number.NaN } };
    assert.equal(buildReplayMarketViewModel({ machine: { state: "REPLAY_ERROR" }, projection: {
        currentEvent: invalid, visibleEvents: [invalid], dataQuality: "INVALID",
    } }).currentPriceSummary.state, "UNAVAILABLE");
});

test("partial and invalid books expose only formal finite same-context summary values", () => {
    const priceOnly = { id: "price", eventType: "MARKET_SNAPSHOT", payload: { marketSource: {
        exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM", canonicalSymbol: "XRPUSDT",
        sourceMode: "REPLAY", tickSize: 0.0001,
    }, lastTradePrice: 0.6 } };
    const partial = buildReplayMarketViewModel({ projection: { currentEvent: priceOnly, visibleEvents: [priceOnly] } });
    assert.equal(partial.currentPriceSummary.currentPrice, "0.6000");
    assert.equal(partial.currentPriceSummary.bestBid, "—");
    assert.equal(partial.currentPriceSummary.spread, "—");
    const crossed = { ...priceOnly, id: "crossed", payload: { ...priceOnly.payload,
        orderBook: { bids: [[2, 1], [Number.NaN, 2]], asks: [[1, 1], [3, Number.POSITIVE_INFINITY]] } } };
    const crossedModel = buildReplayMarketViewModel({ projection: { currentEvent: crossed, visibleEvents: [crossed] } });
    assert.equal(crossedModel.currentPriceSummary.bestBid, "2.0000");
    assert.equal(crossedModel.currentPriceSummary.bestAsk, "1.0000");
    assert.equal(crossedModel.currentPriceSummary.spread, "—");
});

test("market context transition discards old price, DOM, and trades before exposing the new snapshot", () => {
    const context = (exchange, marketType, exchangeSymbol, canonicalSymbol) => ({
        exchange, marketType, exchangeSymbol, canonicalSymbol, sourceMode: "REPLAY",
    });
    const oldSnapshot = { id: "old-xrp", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z",
        dataQuality: "VALID", payload: { marketSource: context("KUCOIN", "FUTURES", "XRPUSDTM", "XRPUSDT"),
            lastTradePrice: 1, orderBook: { asks: [[1.1, 1]], bids: [[0.9, 1]] },
            trades: [{ tradeId: "old-trade", price: 1, quantity: 1, side: "BUY" }] } };
    const oldContextlessTrade = { id: "old-trade-event", eventType: "TRADE", timestamp: "2026-01-01T00:00:01Z",
        dataQuality: "VALID", payload: { tradeId: "old-contextless", price: 2, quantity: 1, side: "SELL" } };
    const newSnapshot = { id: "new-btc", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:01:00Z",
        dataQuality: "VALID", payload: { marketSource: context("BINANCE", "SPOT", "BTCUSDT", "BTCUSDT"),
            lastTradePrice: 200, orderBook: { asks: [[201, 4]], bids: [[199, 5]] },
            trades: [{ tradeId: "new-trade", price: 200, quantity: 2, side: "BUY" }] } };
    const model = buildReplayMarketViewModel({ projection: { currentEvent: newSnapshot,
        visibleEvents: [oldSnapshot, oldContextlessTrade, newSnapshot], dataQuality: "VALID" } });
    assert.equal(model.marketContext.key, "BINANCE\u0000SPOT\u0000BTCUSDT");
    assert.equal(model.header.currentPrice, "200");
    assert.deepEqual(model.orderBook.asks.map(({ price }) => price), ["201"]);
    assert.deepEqual(model.orderBook.bids.map(({ price }) => price), ["199"]);
    assert.deepEqual(model.recentTrades.rows.map(({ tradeId }) => tradeId), ["new-trade"]);
    assert.deepEqual(model.contextEventIds, ["new-btc"]);
    assert.equal(model.diagnostics.contextChanged, true);
    assert.equal(model.diagnostics.excludedContextEventCount, 2);
});

test("context transition immediately exposes the new identity with cleared values while loading", () => {
    const oldSnapshot = { id: "old-xrp", eventType: "MARKET_SNAPSHOT", payload: { marketSource: {
        exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM", canonicalSymbol: "XRPUSDT",
        displaySymbol: "XRP / USDT", sourceMode: "REPLAY",
    }, lastTradePrice: 0.6, orderBook: { bids: [[0.5, 1]], asks: [[0.7, 1]] } } };
    const newContext = { id: "new-btc-context", eventType: "MARKET_SNAPSHOT", payload: { marketSource: {
        exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT", canonicalSymbol: "BTCUSDT",
        displaySymbol: "BTC / USDT", sourceMode: "LIVE",
    } } };
    const model = buildReplayMarketViewModel({ machine: { state: "REPLAY_LOADING" }, projection: {
        currentEvent: newContext, visibleEvents: [oldSnapshot, newContext],
    } });
    assert.deepEqual(model.currentPriceSummary, {
        exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT",
        normalizedSymbol: "BTCUSDT", displaySymbol: "BTC / USDT", currentPrice: "—",
        bestBid: "—", bestAsk: "—", spread: "—", state: "LOADING",
    });
    assert.deepEqual(model.contextEventIds, ["new-btc-context"]);
});

test("context change sequence exposes no stale market data while the new snapshot is loading", () => {
    const oldSnapshot = { id: "old", eventType: "MARKET_SNAPSHOT", payload: {
        exchange: "KUCOIN", marketType: "FUTURES", exchangeSymbol: "XRPUSDTM", canonicalSymbol: "XRPUSDT",
        lastTradePrice: 1, orderBook: { bids: [[1, 1]] }, trades: [{ price: 1, quantity: 1, side: "BUY" }],
    } };
    const newSnapshot = { id: "new", eventType: "MARKET_SNAPSHOT", payload: {
        exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT", canonicalSymbol: "BTCUSDT",
        lastTradePrice: 2, orderBook: { bids: [[2, 2]] }, trades: [{ price: 2, quantity: 2, side: "SELL" }],
    } };
    const oldModel = buildReplayMarketViewModel({ projection: { currentEvent: oldSnapshot, visibleEvents: [oldSnapshot] } });
    const loadingModel = buildReplayMarketViewModel({ machine: { state: "LOADING" }, projection: {
        currentEvent: null, visibleEvents: [],
    } });
    const newModel = buildReplayMarketViewModel({ projection: { currentEvent: newSnapshot, visibleEvents: [newSnapshot] } });
    assert.equal(oldModel.marketContext.displaySymbol, "XRPUSDTM");
    assert.equal(loadingModel.isEmpty, true);
    assert.equal(loadingModel.orderBook.depth, 0);
    assert.equal(loadingModel.recentTrades.count, 0);
    assert.equal(newModel.marketContext.displaySymbol, "BTCUSDT");
    assert.equal(newModel.header.currentPrice, "2");
});

test("book validation, summaries, and truncation remain finite and bounded", () => {
    const asks = Array.from({ length: 63 }, (_, index) => [101 + index, index]);
    asks.push([Number.NaN, 1], [{ bad: true }, 1], [120, -1]);
    const model = buildReplayMarketViewModel({ projection: { visibleEvents: [{
        id: "book", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z", dataQuality: "PARTIAL",
        payload: { orderBook: { asks, bids: [[100, 2], [99, 3], [98, Number.POSITIVE_INFINITY]] } },
    }] } });
    assert.equal(model.orderBook.asks.length, 50);
    assert.equal(model.orderBook.bids.length, 2);
    assert.equal(model.orderBook.bestAsk, "102");
    assert.equal(model.orderBook.bestBid, "100");
    assert.equal(model.orderBook.spread, "2");
    assert.equal(model.orderBook.midpoint, "101");
    assert.equal(model.diagnostics.invalidOrderBookRows, 5);
    assert.equal(model.diagnostics.truncatedAsks, 12);
});

test("DOM display modes, row limits, depth bars, and visible ratios are display-only", () => {
    const orderBook = buildReplayMarketViewModel(load()).orderBook;
    const both = buildOrderBookDomDisplay(orderBook, "BOTH", 10);
    assert.equal(both.asks.length, 10);
    assert.equal(both.bids.length, 10);
    assert.equal(Math.round(both.buyRatio + both.sellRatio), 100);
    assert.equal(Math.max(...[...both.asks, ...both.bids].map(({ depthPercent }) => depthPercent)), 100);
    assert.equal([...both.asks, ...both.bids].every(({ depthPercent }) => depthPercent >= 0 && depthPercent <= 100), true);
    assert.equal(buildOrderBookDomDisplay(orderBook, "BIDS", 20).asks.length, 0);
    assert.equal(buildOrderBookDomDisplay(orderBook, "ASKS", 50).bids.length, 0);
    const zero = buildOrderBookDomDisplay({ asks: [{ numericSize: 0 }], bids: [{ numericSize: 0 }] });
    assert.equal(zero.buyRatio, null);
    assert.equal(zero.sellRatio, null);
});

test("DOM sorting and cumulative size run from best level outward without merging duplicates", () => {
    const snapshot = { id: "dom", eventType: "MARKET_SNAPSHOT", payload: { marketSource: {
        exchange: "TEST", marketType: "SPOT", exchangeSymbol: "AAAUSDT", canonicalSymbol: "AAAUSDT",
        sourceMode: "LIVE", quantityPrecision: 2,
    }, orderBook: {
        asks: [{ price: 12, quantity: 3 }, { price: 10, quantity: 1 },
            { price: 11, quantity: 2, cumulativeSize: 9 }, { price: 10, quantity: 4 }],
        bids: [[8, 2], [9, 1], [7, 3]],
    } } };
    const model = buildReplayMarketViewModel({ projection: { currentEvent: snapshot, visibleEvents: [snapshot] } });
    assert.deepEqual(model.orderBook.asks.map(({ numericPrice }) => numericPrice), [12, 11, 10, 10]);
    assert.deepEqual(model.orderBook.bids.map(({ numericPrice }) => numericPrice), [9, 8, 7]);
    const asksByNearOrder = [...model.orderBook.asks].reverse();
    assert.deepEqual(asksByNearOrder.map(({ cumulativeSize }) => cumulativeSize), ["1.00", "5.00", "9.00", "10.00"]);
    assert.equal(model.orderBook.asks.find(({ numericPrice }) => numericPrice === 11).cumulativeSource, "FORMAL");
    assert.deepEqual(model.orderBook.bids.map(({ cumulativeSize }) => cumulativeSize), ["1.00", "3.00", "6.00"]);
    assert.equal(model.diagnostics.duplicateOrderBookPrices, 1);
});

test("DOM states handle invalid, partial, crossed, and locked books explicitly", () => {
    const source = { exchange: "TEST", marketType: "SPOT", exchangeSymbol: "AAAUSDT",
        canonicalSymbol: "AAAUSDT", sourceMode: "LIVE" };
    const modelFor = (orderBook, extras = {}) => {
        const event = { id: "book", eventType: "MARKET_SNAPSHOT", payload: { marketSource: source, orderBook } };
        return buildReplayMarketViewModel({ ...extras, projection: { currentEvent: event, visibleEvents: [event] } });
    };
    const invalid = modelFor({ asks: [[0, 1], [-1, 1], [Number.NaN, 1]],
        bids: [[1, -1], [1, 0], [1, Number.POSITIVE_INFINITY]] });
    assert.equal(invalid.orderBook.state, "UNAVAILABLE");
    assert.equal(invalid.orderBook.depth, 0);
    assert.equal(invalid.diagnostics.invalidOrderBookRows, 6);
    const askOnly = modelFor({ asks: [[2, 1]], bids: [] });
    assert.equal(askOnly.orderBook.state, "PARTIAL");
    assert.equal(askOnly.orderBook.bestAsk, "2");
    assert.equal(askOnly.orderBook.bestBid, "—");
    const bidOnly = modelFor({ asks: [], bids: [[1, 1]] });
    assert.equal(bidOnly.orderBook.state, "PARTIAL");
    const crossed = modelFor({ asks: [[1, 1]], bids: [[2, 1]] });
    assert.equal(crossed.orderBook.crossed, true);
    assert.equal(crossed.orderBook.state, "UNAVAILABLE");
    assert.equal(crossed.orderBook.spread, "—");
    assert.equal(crossed.currentPriceSummary.state, "UNAVAILABLE");
    const locked = modelFor({ asks: [[1, 1]], bids: [[1, 1]] });
    assert.equal(locked.orderBook.locked, true);
    assert.equal(locked.orderBook.state, "AVAILABLE");
    assert.equal(locked.orderBook.spread, "0");
    assert.equal(modelFor({}, { machine: { state: "REPLAY_LOADING" } }).orderBook.state, "LOADING");
});

test("current price source and duplicate levels remain explicit without merging", () => {
    const model = buildReplayMarketViewModel({ projection: {
        currentEvent: { id: "book", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z",
            payload: { orderBook: { asks: [[101, 1], [101, 2]], bids: [[99, 3]] } } },
        visibleEvents: [],
    } });
    assert.equal(model.header.currentPrice, "100");
    assert.equal(model.header.currentPriceSource, "MID");
    assert.equal(model.orderBook.spread, "2");
    assert.equal(model.orderBook.asks.length, 2);
    assert.deepEqual(model.orderBook.asks.map(({ size }) => size), ["2", "1"]);
    assert.equal(model.diagnostics.duplicateOrderBookPrices, 1);
    assert.equal(buildReplayMarketViewModel(null).header.currentPriceSource, "UNKNOWN");
});

test("trade normalization, VWAP, invalid rows, and maximum rows are deterministic", () => {
    const trades = Array.from({ length: 23 }, (_, index) => ({
        timestamp: "2026-01-01T00:00:00Z", side: index % 2 ? "SHORT" : "LONG", price: 10 + index, quantity: 1,
    }));
    trades.push({ side: "BUY", price: {}, quantity: 1 }, { side: "SELL", price: 2, quantity: [] });
    const model = buildReplayMarketViewModel({ projection: { visibleEvents: [{
        id: "trades", eventType: "MARKET_SNAPSHOT", dataQuality: "VALID", payload: { trades },
    }] } });
    assert.equal(model.recentTrades.rows.length, 23);
    assert.equal(model.recentTrades.rows[0].side, "BUY");
    assert.equal(model.recentTrades.rows[1].side, "SELL");
    assert.equal(model.recentTrades.totalQuantity, "23");
    assert.equal(model.recentTrades.vwap, "21");
    assert.equal(model.diagnostics.invalidTradeRows, 2);
    assert.equal(model.diagnostics.truncatedTrades, 0);
    assert.equal(normalizeMarketSide("BID"), "BUY");
    assert.equal(normalizeMarketSide("ASK"), "SELL");
    assert.equal(normalizeMarketSide("other"), "UNKNOWN");
});

test("trade display uses formal identities, visible intensity, summary, and exact timestamp precision", () => {
    const model = buildReplayMarketViewModel(load());
    const display = buildRecentTradesDisplay(model.recentTrades, model.currentTradeIdentity,
        [{ displayKey: "marker", label: "BUY", tradeId: "trade-current" }], 20);
    assert.equal(display.rows.length, 20);
    assert.equal(display.rows[0].isCurrent, true);
    assert.equal(display.rows[0].markers.length, 1);
    assert.equal(display.rows[1].isCurrent, false);
    assert.equal(Math.max(...display.rows.map(({ intensity }) => intensity)), 100);
    assert.equal(display.rows.every(({ intensity }) => intensity >= 0 && intensity <= 100), true);
    assert.equal(display.count, display.buyCount + display.sellCount + display.unknownCount);
    assert.equal(Math.round(display.buyRatio + display.sellRatio), 100);
    assert.equal(normalizedTradeTime("2026-01-01T01:02:03Z"), "01:02:03");
    assert.equal(normalizedTradeTime("bad"), "TIME UNKNOWN");
});

test("recent trades use formal time order and shared price and quantity precision", () => {
    const snapshot = { id: "trades", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z", payload: {
        marketSource: { exchange: "BINANCE", marketType: "SPOT", exchangeSymbol: "BTCUSDT",
            canonicalSymbol: "BTCUSDT", sourceMode: "LIVE", pricePrecision: 2, quantityPrecision: 3 },
        trades: [
            { tradeId: "old", timestamp: "2026-01-01T00:00:01Z", sequence: 1, price: 10, quantity: 1, side: "BUY" },
            { tradeId: "same-low", timestamp: "2026-01-01T00:00:02Z", sequence: 2, price: 11, quantity: 2, side: "SELL" },
            { tradeId: "same-high", timestamp: "2026-01-01T00:00:02Z", sequence: 3, price: 12, quantity: 3, side: "BUY" },
        ],
    } };
    const model = buildReplayMarketViewModel({ projection: { currentEvent: snapshot, visibleEvents: [snapshot] } });
    assert.deepEqual(model.recentTrades.rows.map(({ tradeId }) => tradeId), ["same-high", "same-low", "old"]);
    assert.deepEqual(model.recentTrades.rows.map(({ price }) => price), ["12.00", "11.00", "10.00"]);
    assert.deepEqual(model.recentTrades.rows.map(({ size }) => size), ["3.000", "2.000", "1.000"]);
    assert.deepEqual(model.recentTrades.rows.map(({ side }) => side), ["BUY", "SELL", "BUY"]);
    assert.equal(model.recentTrades.rows[0].time, "00:00:02");
    assert.equal(model.recentTrades.state, "AVAILABLE");
});

test("recent trade validation and empty states never infer malformed trades", () => {
    const marketSource = { exchange: "TEST", marketType: "SPOT", exchangeSymbol: "AAAUSDT",
        canonicalSymbol: "AAAUSDT", sourceMode: "LIVE" };
    const modelFor = (payload, machine) => {
        const event = { id: "market", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z",
            payload: { marketSource, ...payload } };
        return buildReplayMarketViewModel({ machine, projection: { currentEvent: event, visibleEvents: [event] } });
    };
    assert.equal(buildReplayMarketViewModel(null).recentTrades.state, "NO MARKET SELECTED");
    assert.equal(modelFor({}).recentTrades.state, "WAITING");
    assert.equal(modelFor({ trades: [] }).recentTrades.state, "NO TRADES");
    assert.equal(modelFor({}, { state: "REPLAY_LOADING" }).recentTrades.state, "LOADING");
    const invalid = modelFor({ trades: [
        { timestamp: "2026-01-01T00:00:00Z", price: 0, quantity: 1, side: "BUY" },
        { timestamp: "2026-01-01T00:00:00Z", price: Number.NaN, quantity: 1, side: "BUY" },
        { timestamp: "2026-01-01T00:00:00Z", price: 1, quantity: 0, side: "SELL" },
        { timestamp: "2026-01-01T00:00:00Z", price: 1, quantity: Number.NaN, side: "SELL" },
        { timestamp: "bad", price: 1, quantity: 1, side: "BUY" },
        { timestamp: "2026-01-01T00:00:00Z", price: 1, quantity: 1, side: "UNKNOWN" },
    ] });
    assert.equal(invalid.recentTrades.state, "UNAVAILABLE");
    assert.equal(invalid.recentTrades.count, 0);
    assert.equal(invalid.diagnostics.invalidTradeRows, 6);
    assert.equal(normalizedTradeTime(Date.parse("2026-01-01T12:30:05Z")), "12:30:05.000");
});

test("recent trade row limits are display-only and capped at fifty", () => {
    const recentTrades = { rows: Array.from({ length: 60 }, (_, index) => ({
        id: String(index), numericSize: index + 1, side: index % 2 ? "SELL" : "BUY",
    })) };
    assert.equal(buildRecentTradesDisplay(recentTrades, null, [], 10).count, 10);
    assert.equal(buildRecentTradesDisplay(recentTrades, null, [], 20).count, 20);
    assert.equal(buildRecentTradesDisplay(recentTrades, null, [], 50).count, 50);
    assert.equal(buildRecentTradesDisplay(recentTrades, null, [], 100).count, 20);
    assert.equal(recentTrades.rows.length, 60);
});

test("only projection-visible events can contribute market data", () => {
    const past = { id: "past", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z",
        payload: { markPrice: 10, trades: [{ side: "BUY", price: 10, quantity: 1 }] }, dataQuality: "VALID" };
    const future = { id: "future", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T01:00:00Z",
        payload: { markPrice: 999, trades: [{ side: "SELL", price: 999, quantity: 9 }] }, dataQuality: "VALID" };
    const model = buildReplayMarketViewModel({ dataset: { events: [past, future] }, projection: {
        currentEvent: past, visibleEvents: [past], dataQuality: "VALID",
    } });
    assert.equal(model.header.markPrice, "10");
    assert.equal(model.recentTrades.count, 1);
    assert.equal(model.recentTrades.lastTrade, "10");
});

test("an authoritative current event supports partial projections without a visible list", () => {
    const currentEvent = { id: "current", eventType: "MARKET_SNAPSHOT", timestamp: "2026-01-01T00:00:00Z",
        payload: { symbol: "CURRENT", markPrice: 7, buyPressure: 0.6 }, dataQuality: "DEGRADED" };
    const model = buildReplayMarketViewModel({ projection: { currentEvent, visibleEvents: null } });
    assert.equal(model.header.symbol, "CURRENT");
    assert.equal(model.header.markPrice, "7");
    assert.equal(model.metrics.buyPressure, "0.6");
});

test("display normalization is React-safe for invalid values", () => {
    for (const value of [null, undefined, "", Number.NaN, Number.POSITIVE_INFINITY,
        Number.NEGATIVE_INFINITY, {}, []]) assert.equal(marketDisplayValue(value), "—");
    assert.equal(marketDisplayValue(false), "FALSE");
    assert.equal(marketTimestamp("invalid"), "—");
    assert.equal(marketTimestamp(1e100), "—");
});

test("real replay commands keep the market model synchronized and reset it", () => {
    let engine = load();
    const timestamp = () => buildReplayMarketViewModel(engine).header.timestamp;
    assert.equal(timestamp(), XRP_REPLAY_FIXTURE.startedAt);
    engine = applyReplayCommand(engine, { type: C.STEP_FORWARD });
    assert.equal(timestamp(), "2026-07-20T12:00:05.000Z");
    engine = applyReplayCommand(engine, { type: C.STEP_BACKWARD });
    assert.equal(timestamp(), XRP_REPLAY_FIXTURE.startedAt);
    engine = applyReplayCommand(engine, { type: C.SEEK, payload: { timestamp: "2026-07-20T12:00:30.000Z" } });
    assert.equal(timestamp(), "2026-07-20T12:00:30.000Z");
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_START });
    assert.equal(timestamp(), XRP_REPLAY_FIXTURE.startedAt);
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    assert.equal(timestamp(), XRP_REPLAY_FIXTURE.endedAt);
    engine = applyReplayCommand(engine, { type: C.RESTART });
    assert.equal(timestamp(), XRP_REPLAY_FIXTURE.startedAt);
    engine = applyReplayCommand(engine, { type: C.RESET });
    assert.equal(buildReplayMarketViewModel(engine).isEmpty, true);
});
