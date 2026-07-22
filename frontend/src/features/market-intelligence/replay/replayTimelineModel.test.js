import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { buildReplayTimelineModel } from "./replayTimelineModel.js";

const item = (overrides = {}) => ({
    id: "event-1",
    timestamp: "2026-07-20T12:00:00.000Z",
    sequence: 1,
    eventType: "MARKET_SNAPSHOT",
    dataQuality: "VALID",
    isPast: false,
    isCurrent: true,
    isFuture: false,
    ...overrides,
});
const engineWith = (timeline, extras = {}) => ({
    replayCursor: "2026-07-20T12:00:00.000Z",
    projection: { timeline, dataQuality: "VALID" },
    ...extras,
});

test("null engine, projection, and timeline create a safe empty model", () => {
    for (const engine of [null, {}, { projection: null }, { projection: { timeline: null } }]) {
        const model = buildReplayTimelineModel(engine);
        assert.equal(model.isEmpty, true);
        assert.equal(model.summary.totalEvents, 0);
        assert.equal(model.summary.reachedCount, 0);
        assert.equal(model.summary.currentEvent, "—");
        assert.equal(model.currentItem, null);
    }
});

test("single current event is normalized without reclassifying projection status", () => {
    const model = buildReplayTimelineModel(engineWith([item()]));
    assert.equal(model.items[0].status, "current");
    assert.equal(model.items[0].statusLabel, "CURRENT");
    assert.equal(model.items[0].timestampLabel, "2026-07-20T12:00:00.000Z");
    assert.equal(model.items[0].sequenceLabel, "#1");
    assert.equal(model.currentItem.id, "event-1");
});

test("future statuses are excluded from the reached-only summary", () => {
    const timeline = [
        item({ id: "past", isPast: true, isCurrent: false }),
        item({ id: "current", sequence: 2 }),
        item({ id: "future", timestamp: "2026-07-20T12:00:01.000Z", sequence: 3,
            isCurrent: false, isFuture: true }),
    ];
    const model = buildReplayTimelineModel(engineWith(timeline));
    assert.deepEqual(model.summary, {
        totalEvents: 2,
        pastCount: 1,
        currentCount: 1,
        futureCount: 0,
        reachedCount: 2,
        groupCount: 1,
        currentEvent: "MARKET_SNAPSHOT",
        replayCursor: "2026-07-20T12:00:00.000Z",
    });
});

test("same timestamp items share one group in projection order", () => {
    const model = buildReplayTimelineModel(engineWith([
        item({ id: "first", sequence: 1, isPast: true, isCurrent: false }),
        item({ id: "second", sequence: 2 }),
    ]));
    assert.equal(model.groups.length, 1);
    assert.deepEqual(model.groups[0].items.map(({ eventId }) => eventId), ["first", "second"]);
    assert.equal(model.groups[0].groupStatus, "current");
    assert.equal(model.groups[0].containsCurrent, true);
    assert.equal(model.currentGroup, model.groups[0]);
});

test("future-only groups are excluded", () => {
    const model = buildReplayTimelineModel(engineWith([
        item({ id: "past", isPast: true, isCurrent: false }),
        item({ id: "future", timestamp: "2026-07-20T12:00:01.000Z",
            isCurrent: false, isFuture: true }),
    ]));
    assert.equal(model.groups[0].groupStatus, "past");
    assert.equal(model.groups.length, 1);
    assert.equal(model.summary.futureCount, 0);
});

test("invalid items, timestamps, unknown status, and duplicate IDs remain safe", () => {
    const duplicate = item({ id: "duplicate" });
    const model = buildReplayTimelineModel(engineWith([
        null,
        { id: "invalid-time", timestamp: "bad", eventType: "", sequence: null },
        duplicate,
        { ...duplicate },
    ]));
    assert.equal(model.items[0].status, "unknown");
    assert.equal(model.items[1].timestampLabel, "—");
    assert.equal(model.items[1].eventType, "UNKNOWN_EVENT");
    assert.equal(model.items[1].sequenceLabel, "—");
    assert.equal(new Set(model.items.map(({ id }) => id)).size, model.items.length);
    assert.equal(model.groups.length, 3);
});

test("engine cursor commands update current item and reset returns empty", () => {
    let engine = applyReplayCommand(createInitialReplayEngineState(), {
        type: C.LOAD_DATASET,
        payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    assert.equal(buildReplayTimelineModel(engine).currentItem.eventId, "replay-event-001");
    assert.equal(buildReplayTimelineModel(engine).summary.futureCount, 0);
    assert.equal(buildReplayTimelineModel(engine).items.length, 1);
    engine = applyReplayCommand(engine, { type: C.STEP_FORWARD });
    assert.equal(buildReplayTimelineModel(engine).currentItem.eventId, "replay-event-002");
    engine = applyReplayCommand(engine, { type: C.STEP_BACKWARD });
    assert.equal(buildReplayTimelineModel(engine).currentItem.eventId, "replay-event-001");
    assert.equal(buildReplayTimelineModel(engine).items.length, 1);
    engine = applyReplayCommand(engine, { type: C.SEEK,
        payload: { timestamp: "2026-07-20T12:00:45.000Z" } });
    assert.equal(buildReplayTimelineModel(engine).currentItem.eventId, "replay-event-008");
    assert.equal(buildReplayTimelineModel(engine).summary.futureCount, 0);
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_START });
    assert.equal(buildReplayTimelineModel(engine).currentItem.eventId, "replay-event-001");
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    assert.equal(buildReplayTimelineModel(engine).summary.futureCount, 0);
    engine = applyReplayCommand(engine, { type: C.RESTART });
    assert.equal(buildReplayTimelineModel(engine).currentItem.eventId, "replay-event-001");
    engine = applyReplayCommand(engine, { type: C.RESET });
    assert.equal(buildReplayTimelineModel(engine).isEmpty, true);
});
