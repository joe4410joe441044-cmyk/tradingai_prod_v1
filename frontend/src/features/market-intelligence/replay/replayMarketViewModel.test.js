import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { buildOrderBookDomDisplay, buildRecentTradesDisplay, buildReplayMarketViewModel, marketDisplayValue, marketTimestamp, normalizedTradeTime, normalizeMarketSide } from "./replayMarketViewModel.js";

const load = () => applyReplayCommand(createInitialReplayEngineState(), {
    type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
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
        canonicalSymbol: "XRPUSDT", sourceMode: "REPLAY", isSample: true });
    assert.equal(model.header.timestamp, XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(model.header.markPrice, "0.6124");
    assert.equal(model.orderBook.asks.length, 12);
    assert.equal(model.orderBook.bids.length, 12);
    assert.equal(model.orderBook.bestAsk, "0.6125");
    assert.equal(model.orderBook.bestBid, "0.6123");
    assert.equal(model.orderBook.asks.at(-2).optionalTotal, "340");
    assert.equal(model.orderBook.asks.at(-1).price, "0.6125");
    assert.equal(model.orderBook.bids[0].price, "0.6123");
    assert.equal(model.recentTrades.rows.length, 24);
    assert.equal(model.recentTrades.rows[0].tradeId, "trade-current");
    assert.equal(model.recentTrades.rows[1].tradeId, "trade-same-time-low");
    assert.equal(model.metrics.buyPressure, "0.58");
    assert.equal(model.quality.orderBook, "VALID");
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
    assert.equal(model.orderBook.bestAsk, "101");
    assert.equal(model.orderBook.bestBid, "100");
    assert.equal(model.orderBook.spread, "1");
    assert.equal(model.orderBook.midpoint, "100.5");
    assert.equal(model.diagnostics.invalidOrderBookRows, 4);
    assert.equal(model.diagnostics.truncatedAsks, 13);
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
