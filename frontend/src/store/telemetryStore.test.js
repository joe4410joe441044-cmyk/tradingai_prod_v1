import assert from "node:assert/strict";
import test from "node:test";

import {
    getMarketTelemetrySnapshot,
    getRuntimeTelemetrySnapshot,
    subscribeTelemetry,
    updateMarketTelemetry,
    updateRuntimeTelemetry,
} from "./telemetryStore.js";

test("market and runtime authority updates synchronously notify subscribers", () => {
    let notifications = 0;
    const unsubscribe = subscribeTelemetry(() => {
        notifications += 1;
    });
    const previousMarket = getMarketTelemetrySnapshot();
    const previousRuntime = getRuntimeTelemetrySnapshot();
    updateMarketTelemetry({
        exchange: "KUCOIN",
        exchangeSymbol: "XRPUSDT",
        price: 0.6,
        bestBid: 0.59,
        bestAsk: 0.61,
        lastUpdate: 1,
    });
    assert.notEqual(getMarketTelemetrySnapshot(), previousMarket);
    assert.equal(getMarketTelemetrySnapshot().price, 0.6);
    updateRuntimeTelemetry({ websocketConnected: true, streamStale: false });
    assert.notEqual(getRuntimeTelemetrySnapshot(), previousRuntime);
    assert.equal(getRuntimeTelemetrySnapshot().websocketConnected, true);
    assert.equal(notifications, 2);
    unsubscribe();
    updateMarketTelemetry({ price: 0.7 });
    assert.equal(notifications, 2);
});
