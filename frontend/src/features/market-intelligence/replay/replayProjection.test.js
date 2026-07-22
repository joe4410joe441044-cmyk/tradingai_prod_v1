import assert from "node:assert/strict";
import test from "node:test";

import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { projectReplayMarkers, projectReplayState } from "./replayProjection.js";

const clone = (value) => structuredClone(value);
const at = (timestamp, dataset = XRP_REPLAY_FIXTURE) => projectReplayState(dataset, timestamp);

test("projects before, at, during, at end, and after the fixture range", () => {
    const before = at("2026-07-20T11:59:59.000Z");
    assert.equal(before.currentEvent, null);
    assert.equal(before.nextEvent.id, "replay-event-001");
    assert.equal(before.progress, 0);
    assert.equal(before.isAtStart, true);

    const start = at(XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(start.currentEvent.id, "replay-event-001");
    assert.equal(start.progress, 0);

    const middle = at("2026-07-20T12:00:45.000Z");
    assert.equal(middle.currentEvent.id, "replay-event-008");
    assert.ok(middle.progress > 0 && middle.progress < 1);

    const end = at(XRP_REPLAY_FIXTURE.endedAt);
    assert.equal(end.currentEvent.id, "replay-event-010");
    assert.equal(end.progress, 1);
    assert.equal(end.isAtEnd, true);
    assert.equal(at("2026-07-20T12:02:00.000Z").progress, 1);
});

test("null cursors and invalid or empty datasets return safe projections", () => {
    for (const dataset of [null, undefined, "invalid", {}, { events: null }, { events: [] }]) {
        const projection = projectReplayState(dataset, null);
        assert.equal(projection.currentEvent, null);
        assert.deepEqual(projection.visibleEvents, []);
        assert.equal(projection.progress, 0);
        assert.equal(projection.dataQuality, "UNKNOWN");
    }
    const invalidCursor = projectReplayState(XRP_REPLAY_FIXTURE, "not-a-date");
    assert.equal(invalidCursor.currentEvent, null);
    assert.equal(invalidCursor.timeline.every((item) => item.isFuture), true);
});

test("current, previous, next, and visible events respect cursor boundaries", () => {
    const projection = at("2026-07-20T12:00:15.000Z");
    assert.equal(projection.currentEvent.id, "replay-event-004");
    assert.equal(projection.previousEvent.id, "replay-event-003");
    assert.equal(projection.nextEvent.id, "replay-event-005");
    assert.deepEqual(projection.visibleEvents.map(({ id }) => id), [
        "replay-event-001", "replay-event-002", "replay-event-003", "replay-event-004",
    ]);
});

test("all events at the cursor timestamp are reached in sequence order", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events = [
        { ...dataset.events[0], id: "sequence-3", sequence: 3 },
        { ...dataset.events[0], id: "sequence-1", sequence: 1 },
        { ...dataset.events[0], id: "sequence-2", sequence: 2 },
    ];
    const projection = at(dataset.events[0].timestamp, dataset);
    assert.deepEqual(projection.visibleEvents.map(({ id }) => id), [
        "sequence-1", "sequence-2", "sequence-3",
    ]);
    assert.equal(projection.currentEvent.id, "sequence-3");
});

test("position context follows opened, updated, and closed events", () => {
    assert.equal(at("2026-07-20T12:00:29.000Z").positionContext.positionId, null);
    const opened = at("2026-07-20T12:00:30.000Z").positionContext;
    assert.equal(opened.status, "OPEN");
    assert.equal(opened.openedEvent.eventType, "POSITION_OPENED");
    assert.equal(opened.isOpen, true);
    const updated = at("2026-07-20T12:01:00.000Z").positionContext;
    assert.equal(updated.latestUpdateEvent.eventType, "POSITION_UPDATED");
    const closed = at("2026-07-20T12:01:30.000Z").positionContext;
    assert.equal(closed.status, "CLOSED");
    assert.equal(closed.closedEvent.eventType, "POSITION_CLOSED");
    assert.equal(closed.isClosed, true);
});

test("decision context advances without mixing decision IDs", () => {
    assert.equal(at("2026-07-20T12:00:10.000Z").decisionContext.strategyDecision.eventType,
        "STRATEGY_DECISION");
    assert.equal(at("2026-07-20T12:00:15.000Z").decisionContext.aiDecision.eventType,
        "AI_DECISION");
    assert.equal(at("2026-07-20T12:00:20.000Z").decisionContext.governanceDecision.eventType,
        "GOVERNANCE_DECISION");
    assert.equal(at("2026-07-20T12:00:27.000Z").decisionContext.executionEvent.eventType,
        "ORDER_ACKNOWLEDGED");

    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events[4].decisionId = "decision-new";
    const context = at(dataset.events[4].timestamp, dataset).decisionContext;
    assert.equal(context.decisionId, "decision-new");
    assert.equal(context.strategyDecision, null);
    assert.equal(context.aiDecision, null);
});

test("marker and station contexts group only reached events", () => {
    const projection = at("2026-07-20T12:00:30.000Z");
    assert.deepEqual(projection.markerContext.markers.map(({ markerId }) => markerId), [
        "marker-market-001", "marker-position-opened",
    ]);
    assert.equal(projection.markerContext.selectedCandidate, null);
    assert.equal(projection.markerContext.latestMarker.markerId, "marker-position-opened");
    assert.equal(projection.markerContext.count, 2);
    assert.equal(projection.markerContext.summary.total, projection.markerContext.count);
    assert.equal(projection.markerContext.summary.byType.BUY, 1);
    assert.equal(projection.markerContext.summary.entry, 1);
    assert.equal(projection.stationContext.stations.some(
        ({ stationId }) => stationId === "execution",
    ), true);
    assert.equal(projection.markerContext.markers.some(
        ({ markerId }) => markerId === "marker-position-closed",
    ), false);
});

const markerEvent = (id, sequence, markerId, markerType, payload = {}, event = {}) => ({
    id, timestamp: "2026-07-20T12:00:00.000Z", sequence, eventType: "MARKET_SNAPSHOT",
    source: "SYSTEM", positionId: null, decisionId: null, markerId, stationId: null,
    payload: { markerType, ...payload }, dataQuality: "VALID", ...event,
});

test("formal marker projection supports every type and safe fallbacks", () => {
    const types = ["BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN",
        "ORDER_FAILED", "GOVERNANCE_BLOCK", "not-known"];
    const markers = projectReplayMarkers(types.map((type, index) => markerEvent(
        `event-${index}`, index, `marker-${index}`, type,
        index === 0 ? { price: 100, quantity: 2, side: "LONG", orderId: "order-1", reason: "signal" } : {},
    )));
    assert.deepEqual(markers.map(({ type }) => type), [
        "BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN",
        "ORDER_FAILED", "GOVERNANCE_BLOCK", "UNKNOWN",
    ]);
    assert.deepEqual(markers[0], {
        id: "marker-0", markerId: "marker-0", type: "BUY",
        timestamp: "2026-07-20T12:00:00.000Z", sequence: 0, price: 100, quantity: 2,
        side: "BUY", reason: "signal", orderId: "order-1", reduceOnly: false,
        flatten: false, blocked: false, failed: false, source: "SYSTEM",
        eventType: "MARKET_SNAPSHOT", dataQuality: "VALID", eventId: "event-0",
        tradeId: null, decisionId: null, positionId: null, stationId: null,
    });
    assert.equal(markers[4].reduceOnly, true);
    assert.equal(markers[5].flatten, true);
    assert.equal(markers[6].failed, true);
    assert.equal(markers[7].blocked, true);
    assert.equal(markers[8].price, null);
    assert.equal(markers[8].side, null);
});

test("same marker grouping is ordered, deterministic, quality-aware, and non-mutating", () => {
    const events = [
        markerEvent("latest", 3, "shared", "EXIT", { reason: "closed" }, {
            timestamp: "2026-07-20T12:00:02.000Z", dataQuality: "PARTIAL", eventType: "POSITION_CLOSED",
        }),
        markerEvent("first", 1, "shared", "ENTRY", { price: 100, quantity: 4, side: "BUY" }, {
            dataQuality: "STALE", eventType: "POSITION_OPENED",
        }),
        markerEvent("same-time", 2, "other", "SELL", {}, { dataQuality: "UNKNOWN" }),
    ];
    const original = clone(events);
    const markers = projectReplayMarkers(events);
    assert.deepEqual(events, original);
    assert.deepEqual(markers.map(({ markerId }) => markerId), ["shared", "other"]);
    assert.equal(markers[0].type, "EXIT");
    assert.equal(markers[0].timestamp, "2026-07-20T12:00:02.000Z");
    assert.equal(markers[0].price, 100);
    assert.equal(markers[0].quantity, 4);
    assert.equal(markers[0].reason, "closed");
    assert.equal(markers[0].dataQuality, "STALE");
});

test("latest marker follows the latest marker event rather than group insertion order", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events = [
        markerEvent("a-first", 1, "marker-a", "ENTRY"),
        markerEvent("b-only", 2, "marker-b", "BUY", {}, { timestamp: "2026-07-20T12:00:01.000Z" }),
        markerEvent("a-last", 3, "marker-a", "EXIT", {}, { timestamp: "2026-07-20T12:00:01.000Z" }),
    ];
    dataset.startedAt = dataset.events[0].timestamp;
    dataset.endedAt = dataset.events[2].timestamp;
    const context = projectReplayState(dataset, dataset.endedAt).markerContext;
    assert.deepEqual(context.markers.map(({ markerId }) => markerId), ["marker-a", "marker-b"]);
    assert.equal(context.latestMarker.markerId, "marker-a");
    assert.equal(context.latestMarker.type, "EXIT");
});

test("empty marker context has a complete zero summary", () => {
    const context = projectReplayState(null, null).markerContext;
    assert.deepEqual(context.markers, []);
    assert.equal(context.latestMarker, null);
    assert.equal(context.count, 0);
    assert.equal(context.summary.total, 0);
    assert.equal(Object.values(context.summary.byType).every((count) => count === 0), true);
    for (const field of ["buy", "sell", "entry", "exit", "reduceOnly", "flatten", "failed", "blocked", "unknown"])
        assert.equal(context.summary[field], 0);
});

test("timeline classification is exclusive and does not mutate input", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    const original = clone(dataset);
    const timeline = at("2026-07-20T12:00:15.000Z", dataset).timeline;
    assert.equal(timeline.filter(({ isCurrent }) => isCurrent).length, 1);
    assert.equal(timeline.find(({ isCurrent }) => isCurrent).id, "replay-event-004");
    for (const item of timeline) {
        assert.equal([item.isPast, item.isCurrent, item.isFuture].filter(Boolean).length, 1);
    }
    assert.deepEqual(dataset, original);
    assert.equal(Object.hasOwn(timeline[0], "payload"), false);
});

test("progress safely handles zero-duration ranges", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.endedAt = dataset.startedAt;
    assert.equal(at("2026-07-20T11:59:59.000Z", dataset).progress, 0);
    assert.equal(at(dataset.startedAt, dataset).progress, 0);
    assert.equal(at("2026-07-20T12:00:01.000Z", dataset).progress, 1);
    for (const cursor of [null, dataset.startedAt, "2026-07-20T12:00:01.000Z"]) {
        assert.equal(Number.isFinite(at(cursor, dataset).progress), true);
    }
});

test("data quality aggregates reached events by safety priority only", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events[0].dataQuality = "PARTIAL";
    dataset.events[1].dataQuality = "STALE";
    dataset.events[2].dataQuality = "INVALID";
    assert.equal(at("2026-07-20T11:59:59.000Z", dataset).dataQuality, "UNKNOWN");
    assert.equal(at(dataset.events[0].timestamp, dataset).dataQuality, "PARTIAL");
    assert.equal(at(dataset.events[1].timestamp, dataset).dataQuality, "STALE");
    assert.equal(at(dataset.events[2].timestamp, dataset).dataQuality, "INVALID");
});

test("invalid events are ignored without preventing valid event projection", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events.splice(1, 0, null, { timestamp: "invalid" });
    const projection = at(dataset.endedAt, dataset);
    assert.equal(projection.visibleEvents.length, XRP_REPLAY_FIXTURE.events.length);
    assert.equal(projection.currentEvent.id, "replay-event-010");
});
