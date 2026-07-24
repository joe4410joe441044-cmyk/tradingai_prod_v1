import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "../replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../replay/replayFixtures.js";
import { normalizeMarketContext } from "./normalizedMarketModel.js";
import { normalizeReplayMarketModel } from "./replayMarketAdapter.js";
import {
    createDashboardContextMarketModel,
    isReplayMarketContextActive,
    resolveMarketContext,
    runtimeMarketMatchesContext,
} from "./marketContextSelection.js";

const dashboard = (symbol) => normalizeMarketContext({
    exchange: "KUCOIN",
    marketType: "SPOT",
    exchangeSymbol: symbol,
});

test("Dashboard context is active only while Replay is inactive", () => {
    const idle = createInitialReplayEngineState();
    const live = resolveMarketContext({
        dashboardContext: dashboard("BTCUSDT"),
        replayEngine: idle,
        replayModel: normalizeReplayMarketModel({ replayEngine: idle }),
    });
    assert.equal(isReplayMarketContextActive(idle), false);
    assert.equal(live.mode, "LIVE");
    assert.equal(live.context.contextKey, "KUCOIN:SPOT:BTCUSDT");

    const replayEngine = applyReplayCommand(idle, {
        type: C.LOAD_DATASET,
        payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const replay = resolveMarketContext({
        dashboardContext: dashboard("BTCUSDT"),
        replayEngine,
        replayModel: normalizeReplayMarketModel({ replayEngine }),
    });
    assert.equal(isReplayMarketContextActive(replayEngine), true);
    assert.equal(replay.mode, "REPLAY");
    assert.equal(replay.context.contextKey, "KUCOIN:FUTURES:XRPUSDTM");
});

test("RESET returns to the latest Dashboard context without retaining Replay data", () => {
    const loaded = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET,
        payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const reset = applyReplayCommand(loaded, { type: C.RESET });
    const resolved = resolveMarketContext({
        dashboardContext: dashboard("ETHUSDT"),
        replayEngine: reset,
        replayModel: normalizeReplayMarketModel({ replayEngine: reset }),
    });
    const model = createDashboardContextMarketModel(resolved.context);
    assert.equal(resolved.mode, "LIVE");
    assert.equal(model.context.contextKey, "KUCOIN:SPOT:ETHUSDT");
    assert.equal(model.price.current, null);
    assert.deepEqual(model.orderBook, { asks: [], bids: [] });
    assert.deepEqual(model.recentTrades, []);
    assert.deepEqual(model.markers, []);
});

test("rapid Dashboard changes always resolve only the latest context", () => {
    const replayEngine = createInitialReplayEngineState();
    const keys = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "BTCUSDT"].map((symbol) => {
        const resolved = resolveMarketContext({
            dashboardContext: dashboard(symbol),
            replayEngine,
            replayModel: normalizeReplayMarketModel({ replayEngine }),
        });
        return resolved.context.contextKey;
    });
    assert.deepEqual(keys, [
        "KUCOIN:SPOT:BTCUSDT",
        "KUCOIN:SPOT:ETHUSDT",
        "KUCOIN:SPOT:XRPUSDT",
        "KUCOIN:SPOT:BTCUSDT",
    ]);
});

test("runtime quotes require the active exchange and symbol identity", () => {
    const context = dashboard("XRPUSDT");
    assert.equal(runtimeMarketMatchesContext({
        exchange: "KUCOIN", symbol: "XRPUSDT",
    }, context), true);
    assert.equal(runtimeMarketMatchesContext({
        exchange: "KUCOIN", symbol: "BTCUSDT",
    }, context), false);
    assert.equal(runtimeMarketMatchesContext({
        exchange: "BINANCE", symbol: "XRPUSDT",
    }, context), false);
    assert.equal(runtimeMarketMatchesContext({
        exchange: "KUCOIN", symbol: "XRPUSDT", marketType: "FUTURES",
    }, context), false);
    assert.equal(runtimeMarketMatchesContext({ price: 1 }, context), false);
});
