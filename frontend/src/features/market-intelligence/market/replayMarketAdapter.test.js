import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../replay/replayFixtures.js";
import { buildReplayMarketViewModel } from "../replay/replayMarketViewModel.js";
import { normalizeReplayMarketModel } from "./replayMarketAdapter.js";

const load = () => applyReplayCommand(createInitialReplayEngineState(), {
    type: C.LOAD_DATASET,
    payload: { dataset: XRP_REPLAY_FIXTURE },
});

test("sample Replay Projection adapts to the shared numeric contract", () => {
    const engine = load();
    const model = normalizeReplayMarketModel({ replayEngine: engine });
    assert.equal(model.context.exchange, "KUCOIN");
    assert.equal(model.context.marketType, "FUTURES");
    assert.equal(model.context.exchangeSymbol, "XRPUSDTM");
    assert.equal(model.context.contextKey, "KUCOIN:FUTURES:XRPUSDTM");
    assert.equal(model.price.current, 0.6124);
    assert.equal(model.orderBook.asks.length, 12);
    assert.equal(model.orderBook.bids.length, 12);
    assert.ok(model.recentTrades.length > 0);
    assert.ok(model.markers.length > 0);
    assert.equal(model.source.mode, "REPLAY");
    assert.equal(model.source.provider, "REPLAY_PROJECTION");
    assert.equal(model.source.datasetId, XRP_REPLAY_FIXTURE.datasetId);
    assert.equal(model.status, "READY");
});

test("empty Replay remains a canonical no-market model without fabricated timestamps", () => {
    const model = normalizeReplayMarketModel({ replayEngine: createInitialReplayEngineState() });
    assert.equal(model.status, "NO_MARKET");
    assert.equal(model.context.contextKey, null);
    assert.equal(model.price.current, null);
    assert.deepEqual(model.orderBook, { asks: [], bids: [] });
    assert.deepEqual(model.recentTrades, []);
    assert.deepEqual(model.markers, []);
    assert.equal(model.timestamps.sourceUpdatedAt, null);
});

test("existing Replay presentation explicitly consumes the normalized adapter result", () => {
    const engine = load();
    const normalized = normalizeReplayMarketModel({ replayEngine: engine });
    const presentation = buildReplayMarketViewModel(engine, normalized);
    assert.equal(presentation.normalizedMarketModel, normalized);
    assert.equal(presentation.currentPriceSummary.currentPrice, "0.6124");
    assert.equal(presentation.currentPriceSummary.bestBid, "0.6123");
    assert.equal(presentation.currentPriceSummary.bestAsk, "0.6125");
    assert.equal(presentation.currentPriceSummary.state, "REPLAY");
    assert.equal(presentation.orderBook.asks.length, 12);
    assert.equal(presentation.recentTrades.rows.length, 21);
});

test("Replay adapter inputs remain immutable", () => {
    const engine = load();
    const projectionBefore = JSON.stringify(engine.projection);
    const datasetBefore = JSON.stringify(engine.dataset);
    normalizeReplayMarketModel({ replayEngine: engine });
    assert.equal(JSON.stringify(engine.projection), projectionBefore);
    assert.equal(JSON.stringify(engine.dataset), datasetBefore);
});
