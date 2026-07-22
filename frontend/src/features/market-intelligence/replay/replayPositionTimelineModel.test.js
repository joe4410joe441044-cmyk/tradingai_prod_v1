import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { buildReplayPositionTimelineModel } from "./replayPositionTimelineModel.js";

const apply = (engine, type, payload) => applyReplayCommand(engine, { type, payload });
const load = () => apply(createInitialReplayEngineState(), C.LOAD_DATASET, { dataset: XRP_REPLAY_FIXTURE });

test("position timeline is empty before open and advances through open, update, and close", () => {
    let engine = load();
    assert.equal(buildReplayPositionTimelineModel(engine).isEmpty, true);
    engine = apply(engine, C.SEEK, { timestamp: "2026-07-20T12:00:30.000Z" });
    let model = buildReplayPositionTimelineModel(engine);
    assert.deepEqual(model.items.map(({ phase }) => phase), ["OPEN"]);
    assert.equal(model.status, "OPEN");
    engine = apply(engine, C.SEEK, { timestamp: "2026-07-20T12:01:00.000Z" });
    model = buildReplayPositionTimelineModel(engine);
    assert.deepEqual(model.items.map(({ phase }) => phase), ["OPEN", "UPDATE"]);
    assert.equal(model.items[1].unrealizedPnl, "0.21");
    engine = apply(engine, C.JUMP_TO_END);
    model = buildReplayPositionTimelineModel(engine);
    assert.deepEqual(model.items.map(({ phase }) => phase), ["OPEN", "UPDATE", "CLOSE"]);
    assert.equal(model.items[2].realizedPnl, "0.3");
    assert.equal(model.status, "CLOSED");
});

test("backward commands, restart, dataset replacement, and reset remove unreachable position events", () => {
    let engine = apply(load(), C.JUMP_TO_END);
    engine = apply(engine, C.STEP_BACKWARD);
    assert.deepEqual(buildReplayPositionTimelineModel(engine).items.map(({ phase }) => phase), ["OPEN", "UPDATE"]);
    engine = apply(engine, C.SEEK, { timestamp: XRP_REPLAY_FIXTURE.startedAt });
    assert.equal(buildReplayPositionTimelineModel(engine).isEmpty, true);
    engine = apply(apply(engine, C.JUMP_TO_END), C.RESTART);
    assert.equal(buildReplayPositionTimelineModel(engine).isEmpty, true);
    const replacement = structuredClone(XRP_REPLAY_FIXTURE);
    replacement.datasetId = "replacement";
    replacement.events = replacement.events.slice(0, 1);
    replacement.endedAt = replacement.startedAt;
    engine = apply(engine, C.LOAD_DATASET, { dataset: replacement });
    assert.equal(buildReplayPositionTimelineModel(engine).isEmpty, true);
    engine = apply(engine, C.RESET);
    assert.equal(buildReplayPositionTimelineModel(engine).isEmpty, true);
    assert.equal(buildReplayPositionTimelineModel(engine).replayCursor, "—");
});

test("position timeline safely formats nullable projected fields", () => {
    const model = buildReplayPositionTimelineModel({ replayCursor: "bad", projection: { positionContext: {
        positionId: "position-1", status: "OPEN", openedEvent: {
            id: "open", eventType: "POSITION_OPENED", timestamp: "bad", sequence: null,
            payload: {}, dataQuality: "UNKNOWN",
        }, latestUpdateEvent: null, closedEvent: null,
    } } });
    assert.equal(model.items[0].timestamp, "—");
    assert.equal(model.items[0].price, "—");
    assert.equal(model.items[0].quantity, "—");
    assert.equal(model.items[0].dataQuality, "UNKNOWN");
});
