import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { buildReplayMarketViewModel } from "./replayMarketViewModel.js";
import { buildReplayMarkerOverlayModel } from "./replayMarkerOverlayModel.js";

const marker = (id, type, values = {}) => ({
    id, markerId: id, type, timestamp: "2026-01-01T00:00:00.000Z", sequence: 1,
    price: null, quantity: null, side: null, reason: null, orderId: null,
    reduceOnly: false, flatten: false, blocked: false, failed: false,
    source: "SYSTEM", eventType: "MARKET_SNAPSHOT", dataQuality: "VALID",
    eventId: null, tradeId: null, decisionId: null, positionId: null, stationId: null,
    ...values,
});
const engineWith = (markers, latestMarker = null) => {
    const valid = markers.filter((item) => item && typeof item === "object" && typeof item.type === "string");
    const types = ["BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN", "ORDER_FAILED", "GOVERNANCE_BLOCK", "UNKNOWN"];
    const byType = Object.fromEntries(types.map((type) => [type, valid.filter((item) => item.type === type).length]));
    return { projection: { markerContext: { markers, latestMarker, count: valid.length, summary: {
        total: valid.length, byType, buy: byType.BUY, sell: byType.SELL, entry: byType.ENTRY,
        exit: byType.EXIT, reduceOnly: valid.filter(({ reduceOnly }) => reduceOnly).length,
        flatten: valid.filter(({ flatten }) => flatten).length, failed: valid.filter(({ failed }) => failed).length,
        blocked: valid.filter(({ blocked }) => blocked).length, unknown: byType.UNKNOWN,
    } }, dataQuality: "VALID" } };
};
const market = {
    orderBook: { asks: [{ price: "101" }], bids: [{ price: "100" }] },
    recentTrades: { rows: [{ id: "trade-1", tradeId: "trade-1", timestamp: "2026-01-01T00:00:00.000Z", sourceSequence: 1 }] },
};

test("null engines and marker contexts create an empty safe overlay", () => {
    for (const engine of [null, {}, { projection: null }, { projection: { markerContext: null } }]) {
        const model = buildReplayMarkerOverlayModel(engine, {});
        assert.equal(model.markers.length, 0);
        assert.equal(model.priceMarkers.length, 0);
        assert.equal(model.timeMarkers.length, 0);
        assert.equal(model.latestMarker, null);
        assert.equal(model.isEmpty, true);
    }
});

test("price and time markers require exact formal matches", () => {
    const markers = [
        marker("matched", "BUY", { price: 100 }),
        marker("unmatched", "SELL", { price: 100.00001, timestamp: "2026-01-01T00:00:01.000Z", sequence: 2 }),
        marker("zero", "ENTRY", { price: 0 }), marker("same", "EXIT", { price: 100 }),
        marker("trade-id", "BUY", { tradeId: "trade-1", sequence: 3 }),
    ];
    const model = buildReplayMarkerOverlayModel(engineWith(markers), market);
    assert.equal(model.markers[0].priceMatch, true);
    assert.equal(model.markers[0].timeMatch, true);
    assert.equal(model.markers[1].priceMatch, false);
    assert.equal(model.markers[1].timeMatch, false);
    assert.equal(model.markers[2].price, "0");
    assert.equal(model.markers[3].priceMatch, true);
    assert.equal(model.markers[4].timeMatch, true);
    assert.equal(model.counts.priceMatched, 2);
});

test("all marker types, formal latest marker, flags, and summary counts are preserved", () => {
    const types = ["BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN", "ORDER_FAILED", "GOVERNANCE_BLOCK", "mystery"];
    const markers = types.map((type, index) => marker(`m-${index}`, type === "mystery" ? "UNKNOWN" : type, {
        price: 100 + index, quantity: index, orderId: `order-${index}`, reason: `reason-${index}`,
        reduceOnly: type === "REDUCE_ONLY", flatten: type === "FLATTEN",
        failed: type === "ORDER_FAILED", blocked: type === "GOVERNANCE_BLOCK",
    }));
    const model = buildReplayMarkerOverlayModel(engineWith(markers, markers[6]), market);
    assert.equal(model.counts.visible, 9);
    for (const type of ["BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN", "ORDER_FAILED", "GOVERNANCE_BLOCK", "UNKNOWN"])
        assert.equal(model.counts.byType[type], 1);
    assert.equal(model.latestMarker.type, "ORDER_FAILED");
    assert.equal(model.latestMarker.failed, true);
    assert.equal(model.markers[5].flatten, true);
    assert.equal(model.markers[7].blocked, true);
    assert.equal(model.markers.some(({ type }) => type === "ENTRY" && type === "ORDER_FAILED"), false);
});

test("invalid and huge marker arrays are safe and capped for display", () => {
    const markers = [null, undefined, {}, marker("duplicate", "BUY", { price: 100 }),
        marker("duplicate", "SELL", { price: 100 }), marker("bad-price", "BUY", { price: {}, quantity: [] }),
        marker("bad-time", "SELL", { price: Number.NaN, timestamp: "bad" }),
        ...Array.from({ length: 30 }, (_, index) => marker(`large-${index}`, "BUY", { price: 100 }))];
    const model = buildReplayMarkerOverlayModel(engineWith(markers), market);
    assert.equal(model.priceMarkers.length, 20);
    assert.equal(model.timeMarkers.length, 20);
    assert.equal(model.unmatchedMarkers.length <= 10, true);
    assert.equal(model.diagnostics.invalidMarkerCount >= 5, true);
    assert.equal(model.diagnostics.truncatedMarkerCount > 0, true);
    assert.notEqual(model.markers[1].displayKey, model.markers[2].displayKey);
    assert.equal(model.markers.every(({ reason, orderId }) => typeof reason === "string" && typeof orderId === "string"), true);
});

test("governance block and order failure retain formal reasons without invented success", () => {
    const model = buildReplayMarkerOverlayModel(engineWith([
        marker("block", "GOVERNANCE_BLOCK", { reason: "RISK_LIMIT", blocked: true }),
        marker("failed", "ORDER_FAILED", { reason: "VENUE_REJECTED", orderId: "order-failed", failed: true }),
    ]), market);
    assert.equal(model.markers[0].type, "GOVERNANCE_BLOCK");
    assert.equal(model.markers[0].reason, "RISK_LIMIT");
    assert.equal(model.markers[0].blocked, true);
    assert.equal(model.markers[1].type, "ORDER_FAILED");
    assert.equal(model.markers[1].reason, "VENUE_REJECTED");
    assert.equal(model.markers[1].orderId, "order-failed");
    assert.equal(model.counts.byType.ENTRY, 0);
});

test("formal projection summary is authoritative and marker qualities remain distinct", () => {
    const markers = ["VALID", "UNKNOWN", "PARTIAL", "STALE", "INVALID"].map((dataQuality, index) => (
        marker(`quality-${index}`, index === 0 ? "BUY" : "UNKNOWN", { dataQuality })
    ));
    const engine = engineWith(markers, markers.at(-1));
    engine.projection.markerContext.count = 42;
    engine.projection.markerContext.summary.total = 42;
    engine.projection.markerContext.summary.byType.BUY = 12;
    engine.projection.markerContext.summary.buy = 12;
    engine.projection.markerContext.summary.unknown = 30;
    const model = buildReplayMarkerOverlayModel(engine, market);
    assert.equal(model.counts.visible, 42);
    assert.equal(model.summary.total, 42);
    assert.equal(model.counts.byType.BUY, 12);
    assert.equal(model.summary.buy, 12);
    assert.equal(model.diagnostics.unknownTypeCount, 30);
    assert.deepEqual(model.markers.map(({ dataQuality }) => dataQuality), [
        "VALID", "UNKNOWN", "PARTIAL", "STALE", "INVALID",
    ]);
    assert.deepEqual(model.diagnostics.byQuality, {
        UNKNOWN: 1, VALID: 1, PARTIAL: 1, STALE: 1, INVALID: 1,
    });
});

test("real replay commands expose only projection-reached markers", () => {
    let engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    const model = () => buildReplayMarkerOverlayModel(engine, buildReplayMarketViewModel(engine));
    assert.deepEqual(model().markers.map(({ type }) => type), ["BUY"]);
    engine = applyReplayCommand(engine, { type: C.SEEK, payload: { timestamp: "2026-07-20T12:00:27.000Z" } });
    assert.equal(model().counts.byType.ENTRY, 0);
    engine = applyReplayCommand(engine, { type: C.STEP_FORWARD });
    assert.equal(model().counts.byType.ENTRY, 1);
    engine = applyReplayCommand(engine, { type: C.STEP_BACKWARD });
    assert.equal(model().counts.byType.ENTRY, 0);
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_START });
    assert.equal(model().counts.visible, 1);
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    assert.equal(model().counts.byType.EXIT, 1);
    engine = applyReplayCommand(engine, { type: C.SEEK, payload: { timestamp: "2026-07-20T12:00:27.000Z" } });
    assert.equal(model().counts.byType.ENTRY, 0);
    assert.equal(model().counts.byType.EXIT, 0);
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    engine = applyReplayCommand(engine, { type: C.RESTART });
    assert.equal(model().counts.visible, 1);
    engine = applyReplayCommand(engine, { type: C.RESET });
    assert.equal(model().counts.visible, 0);
});
