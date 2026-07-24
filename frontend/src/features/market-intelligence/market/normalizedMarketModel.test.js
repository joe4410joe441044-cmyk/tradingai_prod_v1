import assert from "node:assert/strict";
import test from "node:test";

import {
    createEmptyNormalizedMarketModel,
    createNormalizedMarketModel,
    isNormalizedMarketModelStale,
    normalizeMarketTimestamp,
    normalizedMarketContextKey,
    validateNormalizedMarketModel,
} from "./normalizedMarketModel.js";

const CONTEXT = {
    exchange: "KUCOIN",
    marketType: "FUTURES",
    exchangeSymbol: "XRPUSDTM",
    normalizedSymbol: "XRPUSDT",
};

test("empty model is the single canonical no-market contract", () => {
    const model = createEmptyNormalizedMarketModel();
    assert.equal(model.context.contextKey, null);
    assert.deepEqual(model.source, { mode: "NONE", provider: "NONE", datasetId: null, connectionId: null });
    assert.equal(model.status, "NO_MARKET");
    assert.deepEqual(model.price, { current: null, bestBid: null, bestAsk: null, spread: null, midpoint: null });
    assert.deepEqual(model.orderBook, { asks: [], bids: [] });
    assert.deepEqual(model.recentTrades, []);
    assert.deepEqual(model.markers, []);
    assert.equal(model.dataQuality.contextValid, false);
    assert.equal(model.dataQuality.isStale, false);
});

test("context identity and key are deterministic and invalid identities remain no-market", () => {
    assert.equal(normalizedMarketContextKey(CONTEXT), "KUCOIN:FUTURES:XRPUSDTM");
    for (const context of [
        null,
        { ...CONTEXT, exchange: "" },
        { ...CONTEXT, marketType: null },
        { ...CONTEXT, exchangeSymbol: 42 },
    ]) {
        const model = createNormalizedMarketModel({ context });
        assert.equal(model.context.contextKey, null);
        assert.equal(model.status, "NO_MARKET");
        assert.equal(model.dataQuality.contextValid, false);
    }
});

test("numeric price and normalized book obey locked, crossed, partial, and validation rules", () => {
    const locked = createNormalizedMarketModel({
        context: CONTEXT,
        source: { mode: "LIVE", provider: "RUNTIME_WEBSOCKET" },
        currentPrice: 10,
        orderBook: { asks: [[10, 2]], bids: [[10, 3]] },
    });
    assert.deepEqual(locked.price, { current: 10, bestBid: 10, bestAsk: 10, spread: 0, midpoint: 10 });
    const crossed = createNormalizedMarketModel({
        context: CONTEXT,
        currentPrice: 2,
        orderBook: { asks: [[1, 1]], bids: [[2, 1]] },
    });
    assert.equal(crossed.price.spread, null);
    assert.equal(crossed.price.midpoint, null);
    assert.equal(crossed.status, "INVALID");
    assert.ok(crossed.dataQuality.issues.includes("BOOK_CROSSED"));
    const invalid = createNormalizedMarketModel({
        context: CONTEXT,
        currentPrice: Number.NaN,
        orderBook: {
            asks: [[3, 1], [Number.NaN, 1], [0, 1], [-1, 1], [4, 0]],
            bids: [[2, 1], [1, Number.POSITIVE_INFINITY]],
        },
    });
    assert.equal(invalid.price.current, 2.5);
    assert.deepEqual(invalid.orderBook.asks.map(({ price }) => price), [3, 4]);
    assert.deepEqual(invalid.orderBook.bids.map(({ price }) => price), [2]);
    assert.ok(invalid.dataQuality.issues.includes("PRICE_INVALID"));
    assert.ok(invalid.dataQuality.issues.includes("BOOK_INVALID"));
});

test("trades validate values without inferring side and preserve valid UNKNOWN", () => {
    const trades = [
        { id: "good", timestamp: "2026-01-01T00:00:00Z", price: 1, quantity: 2, side: "UNKNOWN" },
        { id: "zero", timestamp: "2026-01-01T00:00:00Z", price: 0, quantity: 2, side: "BUY" },
        { id: "bad-time", timestamp: "bad", price: 1, quantity: 2, side: "SELL" },
        null,
    ];
    const model = createNormalizedMarketModel({ context: CONTEXT, recentTrades: trades });
    assert.equal(model.recentTrades.length, 1);
    assert.equal(model.recentTrades[0].side, "UNKNOWN");
    assert.ok(model.dataQuality.issues.includes("TRADES_INVALID"));
});

test("normalization does not mutate book, trade, or marker inputs", () => {
    const asks = Object.freeze([[2, 1], [1, 2]].map(Object.freeze));
    const bids = Object.freeze([[0.5, 3]].map(Object.freeze));
    const trades = Object.freeze([Object.freeze({
        id: "t", timestamp: "2026-01-01T00:00:00Z", price: 1, quantity: 1, side: "BUY",
    })]);
    const markers = Object.freeze([Object.freeze({ id: "m", type: "BUY" })]);
    const before = JSON.stringify({ asks, bids, trades, markers });
    const model = createNormalizedMarketModel({
        context: CONTEXT, orderBook: { asks, bids }, recentTrades: trades, markers,
    });
    assert.equal(JSON.stringify({ asks, bids, trades, markers }), before);
    assert.deepEqual(model.orderBook.asks.map(({ price }) => price), [1, 2]);
    assert.equal(model.markers[0], markers[0]);
});

test("stale decision is deterministic at fresh, boundary, and over-boundary times", () => {
    const sourceUpdatedAt = "2026-01-01T00:00:00.000Z";
    assert.deepEqual(isNormalizedMarketModelStale({
        sourceUpdatedAt, staleAfterMs: 1000, now: "2026-01-01T00:00:00.999Z",
    }), { stale: false, issue: null });
    assert.deepEqual(isNormalizedMarketModelStale({
        sourceUpdatedAt, staleAfterMs: 1000, now: "2026-01-01T00:00:01.000Z",
    }), { stale: false, issue: null });
    assert.deepEqual(isNormalizedMarketModelStale({
        sourceUpdatedAt, staleAfterMs: 1000, now: "2026-01-01T00:00:01.001Z",
    }), { stale: true, issue: null });
    assert.equal(isNormalizedMarketModelStale({ staleAfterMs: 1, now: sourceUpdatedAt }).stale, null);
    assert.equal(isNormalizedMarketModelStale({
        sourceUpdatedAt: "bad", staleAfterMs: 1, now: sourceUpdatedAt,
    }).stale, null);
    assert.equal(isNormalizedMarketModelStale({
        sourceUpdatedAt, staleAfterMs: -1, now: sourceUpdatedAt,
    }).stale, null);
    assert.equal(isNormalizedMarketModelStale({
        sourceUpdatedAt, staleAfterMs: 1, now: "bad",
    }).stale, null);
});

test("validation detects context, source, price, ordering, arrays, and timestamps without mutation", () => {
    const valid = createNormalizedMarketModel({
        context: CONTEXT,
        source: { mode: "REPLAY", provider: "REPLAY_PROJECTION" },
        timestamps: { sourceUpdatedAt: "2026-01-01T00:00:00Z" },
        currentPrice: 1,
        orderBook: { asks: [[2, 1]], bids: [[1, 1]] },
        recentTrades: [],
        markers: [],
    });
    assert.deepEqual(validateNormalizedMarketModel(valid), { valid: true, issues: [] });
    const malformed = {
        ...valid,
        context: { ...valid.context, contextKey: "wrong" },
        source: { mode: "BAD", provider: "BAD" },
        status: "BAD",
        price: { current: Infinity },
        orderBook: { asks: [{ price: 2, quantity: 1 }, { price: 1, quantity: 1 }], bids: "bad" },
        recentTrades: "bad",
        markers: {},
        timestamps: null,
    };
    const before = JSON.stringify(malformed);
    const result = validateNormalizedMarketModel(malformed);
    assert.equal(result.valid, false);
    assert.equal(JSON.stringify(malformed), before);
    for (const issue of ["CONTEXT_MISMATCH", "SOURCE_UNAVAILABLE", "PRICE_INVALID",
        "BOOK_INVALID", "TRADES_INVALID", "MARKERS_INVALID", "SOURCE_TIMESTAMP_INVALID"])
        assert.ok(result.issues.includes(issue), issue);
    assert.equal(normalizeMarketTimestamp("bad"), null);
});
