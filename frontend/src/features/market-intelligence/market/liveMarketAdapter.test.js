import assert from "node:assert/strict";
import test from "node:test";

import { normalizeLiveMarketModel } from "./liveMarketAdapter.js";

const context = (exchange, marketType, exchangeSymbol) => ({
    exchange, marketType, exchangeSymbol, normalizedSymbol: exchangeSymbol,
});

test("LIVE runtime payload adapts only fields that currently exist", () => {
    const model = normalizeLiveMarketModel({
        context: context("BINANCE", "SPOT", "BTCUSDT"),
        market: {
            price: 100,
            bestBid: 99,
            bestAsk: 101,
            timestamp: "2026-01-01T00:00:00Z",
            orderBook: { asks: [[101, 2], [102, 1]], bids: [[99, 3], [98, 1]] },
        },
        runtime: { websocketConnected: true, streamStale: false },
        connection: { connectionId: "ws-1" },
        receivedAt: "2026-01-01T00:00:00.100Z",
    });
    assert.equal(model.source.mode, "LIVE");
    assert.equal(model.source.provider, "RUNTIME_WEBSOCKET");
    assert.equal(model.context.contextKey, "BINANCE:SPOT:BTCUSDT");
    assert.deepEqual(model.price, { current: 100, bestBid: 99, bestAsk: 101, spread: 2, midpoint: 100 });
    assert.deepEqual(model.orderBook.asks.map(({ price }) => price), [101, 102]);
    assert.deepEqual(model.orderBook.bids.map(({ price }) => price), [99, 98]);
    assert.deepEqual(model.recentTrades, []);
    assert.deepEqual(model.markers, []);
    assert.ok(model.dataQuality.issues.includes("TRADES_UNAVAILABLE"));
    assert.ok(model.dataQuality.issues.includes("MARKERS_UNAVAILABLE"));
    assert.equal(model.status, "READY");
});

test("LIVE price authority is price, lastPrice, then valid top-of-book midpoint", () => {
    const base = { context: context("TEST", "SPOT", "AAAUSDT"), runtime: { websocketConnected: true } };
    assert.equal(normalizeLiveMarketModel({
        ...base, market: { price: 10, lastPrice: 9, timestamp: 1, bids: [[8, 1]], asks: [[12, 1]] },
    }).price.current, 10);
    assert.equal(normalizeLiveMarketModel({
        ...base, market: { lastPrice: 9, timestamp: 1, bids: [[8, 1]], asks: [[12, 1]] },
    }).price.current, 9);
    assert.equal(normalizeLiveMarketModel({
        ...base, market: { timestamp: 1, bids: [[8, 1]], asks: [[12, 1]] },
    }).price.current, 10);
});

test("LIVE stale, unavailable, invalid, and missing source data stay explicit", () => {
    const base = { context: context("TEST", "SPOT", "AAAUSDT") };
    const stale = normalizeLiveMarketModel({
        ...base,
        market: { timestamp: "2026-01-01T00:00:00Z", price: 1 },
        runtime: { websocketConnected: true },
        staleAfterMs: 1000,
        now: "2026-01-01T00:00:01.001Z",
    });
    assert.equal(stale.status, "STALE");
    assert.equal(stale.dataQuality.isStale, true);
    const unavailable = normalizeLiveMarketModel({
        ...base, market: { timestamp: "bad", price: NaN }, runtime: { websocketConnected: false },
    });
    assert.equal(unavailable.status, "UNAVAILABLE");
    assert.equal(unavailable.price.current, null);
    assert.ok(unavailable.dataQuality.issues.includes("SOURCE_TIMESTAMP_INVALID"));
    assert.ok(unavailable.dataQuality.issues.includes("SOURCE_UNAVAILABLE"));
});

test("separate LIVE models cannot retain the prior market context", () => {
    const xrp = normalizeLiveMarketModel({
        context: context("KUCOIN", "FUTURES", "XRPUSDTM"),
        market: { price: 0.6, timestamp: 1, bids: [[0.5, 1]], asks: [[0.7, 1]] },
        runtime: { websocketConnected: true },
    });
    const btc = normalizeLiveMarketModel({
        context: context("BINANCE", "SPOT", "BTCUSDT"),
        market: { price: 100, timestamp: 2, bids: [[99, 2]], asks: [[101, 2]] },
        runtime: { websocketConnected: true },
    });
    assert.equal(xrp.context.contextKey, "KUCOIN:FUTURES:XRPUSDTM");
    assert.equal(btc.context.contextKey, "BINANCE:SPOT:BTCUSDT");
    assert.equal(btc.price.current, 100);
    assert.deepEqual(btc.orderBook.bids.map(({ price }) => price), [99]);
    assert.equal(JSON.stringify(btc).includes("XRP"), false);
});

test("formal LIVE book preserves metadata and calculates cumulative size without mutation", () => {
    const orderBook = {
        timestamp: 1784844000.123,
        sequence: 12345,
        depth: 2,
        bids: [{ price: 10, size: 2 }, { price: 9, size: 3 }],
        asks: [{ price: 11, size: 4 }, { price: 12, size: 5 }],
        dataQuality: "VALID",
        syncState: "SYNCED",
    };
    const before = structuredClone(orderBook);
    const model = normalizeLiveMarketModel({
        context: context("kucoin", "FUTURES", "XRPUSDTM"),
        market: { timestamp: 1784844000.123, price: 10.5, bestBid: 10, bestAsk: 11, orderBook },
        runtime: { websocketConnected: true, streamStale: false },
    });
    assert.deepEqual(orderBook, before);
    assert.equal(model.orderBook.sequence, 12345);
    assert.equal(model.orderBook.syncState, "SYNCED");
    assert.deepEqual(model.orderBook.bids.map(({ size, cumulativeSize, level }) => (
        [size, cumulativeSize, level]
    )), [[2, 2, 1], [3, 5, 2]]);
});

test("UNSYNCED formal LIVE book is never presented as READY", () => {
    const model = normalizeLiveMarketModel({
        context: context("kucoin", "FUTURES", "XRPUSDTM"),
        market: {
            timestamp: 1784844000,
            orderBook: {
                timestamp: 1784844000, sequence: 1, depth: 1,
                bids: [{ price: 10, size: 1 }], asks: [{ price: 11, size: 1 }],
                dataQuality: "INVALID", syncState: "UNSYNCED",
            },
        },
        runtime: { websocketConnected: true },
    });
    assert.equal(model.status, "INVALID");
    assert.ok(model.dataQuality.issues.includes("BOOK_INVALID"));
});
