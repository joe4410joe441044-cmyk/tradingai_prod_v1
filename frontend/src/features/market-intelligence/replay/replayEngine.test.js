import assert from "node:assert/strict";
import test from "node:test";

import {
    REPLAY_ENGINE_COMMANDS as C,
    applyReplayCommand,
    canApplyReplayCommand,
    createInitialReplayEngineState,
} from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { REPLAY_STATES as S } from "./replayStateMachine.js";

const clone = (value) => structuredClone(value);
const command = (type, payload) => ({ type, payload });
const load = (dataset = XRP_REPLAY_FIXTURE) => applyReplayCommand(
    createInitialReplayEngineState(),
    command(C.LOAD_DATASET, { dataset }),
);
const apply = (engine, type, payload) => applyReplayCommand(engine, command(type, payload));

test("exports every immutable engine command", () => {
    assert.deepEqual(Object.values(C), [
        "LOAD_DATASET", "LOAD_FAILURE", "PLAY", "PAUSE", "STEP_FORWARD",
        "STEP_BACKWARD", "SEEK", "JUMP_TO_START", "JUMP_TO_END", "REACH_END",
        "RESTART", "RESET", "RETRY",
    ]);
    assert.equal(Object.isFrozen(C), true);
});

test("creates fresh initial engine and empty projection state", () => {
    const first = createInitialReplayEngineState();
    const second = createInitialReplayEngineState();
    assert.equal(first.dataset, null);
    assert.equal(first.replayCursor, null);
    assert.equal(first.machine.state, S.IDLE);
    assert.equal(first.projection.currentEvent, null);
    assert.equal(first.accepted, true);
    assert.notEqual(first, second);
    assert.notEqual(first.machine, second.machine);
    assert.notEqual(first.projection, second.projection);
});

test("loads, validates, initializes cursor, and projects a valid dataset", () => {
    const original = clone(XRP_REPLAY_FIXTURE);
    const engine = load();
    assert.equal(engine.accepted, true);
    assert.equal(engine.machine.state, S.REPLAY_READY);
    assert.equal(engine.dataset, XRP_REPLAY_FIXTURE);
    assert.equal(engine.replayCursor, XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(engine.projection.currentEvent.id, "replay-event-001");
    assert.equal(engine.projection.replayCursor, engine.replayCursor);
    assert.deepEqual(XRP_REPLAY_FIXTURE, original);
});

test("falls back to event boundaries for invalid declared timestamps", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.startedAt = "invalid";
    dataset.endedAt = "invalid";
    const engine = load(dataset);
    assert.equal(engine.machine.state, S.REPLAY_READY);
    assert.equal(engine.replayCursor, dataset.events[0].timestamp);
    const ended = apply(engine, C.JUMP_TO_END);
    assert.equal(ended.replayCursor, dataset.events.at(-1).timestamp);
});

test("loads a valid empty dataset into ready state with null cursor", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events = [];
    const engine = load(dataset);
    assert.equal(engine.machine.state, S.REPLAY_READY);
    assert.equal(engine.replayCursor, null);
    assert.equal(engine.projection.currentEvent, null);
});

test("load validation failures are accepted commands with error results", () => {
    for (const dataset of [null, "invalid", {}, { events: null }]) {
        const engine = load(dataset);
        assert.equal(engine.accepted, true);
        assert.equal(engine.machine.state, S.REPLAY_ERROR);
        assert.equal(engine.dataset, null);
        assert.equal(engine.replayCursor, null);
        assert.equal(engine.engineError.code, "INVALID_REPLAY_DATASET");
        assert.equal(engine.validation.valid, false);
    }
});

test("play and pause only change machine state", () => {
    const ready = load();
    const playing = apply(ready, C.PLAY);
    assert.equal(playing.machine.state, S.PLAYING);
    assert.equal(playing.replayCursor, ready.replayCursor);
    assert.deepEqual(playing.projection, ready.projection);
    const paused = apply(playing, C.PAUSE);
    assert.equal(paused.machine.state, S.PAUSED);
    assert.equal(paused.replayCursor, playing.replayCursor);
});

test("step forward moves by distinct timestamp and completes at the end", () => {
    const dataset = clone(XRP_REPLAY_FIXTURE);
    dataset.events[1].timestamp = dataset.events[0].timestamp;
    let engine = load(dataset);
    engine = apply(engine, C.STEP_FORWARD);
    assert.equal(engine.replayCursor, dataset.events[2].timestamp);
    assert.equal(engine.projection.currentEvent.id, "replay-event-003");
    engine = apply(engine, C.JUMP_TO_END);
    const atEnd = engine;
    engine = apply(apply(atEnd, C.RESTART), C.JUMP_TO_END);
    assert.equal(engine.machine.state, S.COMPLETED);
    const noNext = apply(apply(engine, C.RESTART), C.JUMP_TO_END);
    assert.equal(noNext.machine.state, S.COMPLETED);
});

test("step forward at the last timestamp completes and playing step is rejected", () => {
    let engine = apply(load(), C.JUMP_TO_END);
    engine = apply(engine, C.RESTART);
    engine = apply(engine, C.JUMP_TO_END);
    const restarted = apply(engine, C.RESTART);
    const lastReady = apply(restarted, C.SEEK, { timestamp: XRP_REPLAY_FIXTURE.endedAt });
    const completed = apply(lastReady, C.STEP_FORWARD);
    assert.equal(completed.machine.state, S.COMPLETED);
    assert.equal(completed.replayCursor, XRP_REPLAY_FIXTURE.endedAt);
    const playing = apply(load(), C.PLAY);
    assert.equal(apply(playing, C.STEP_FORWARD).accepted, false);
});

test("step backward moves by timestamp, rejects at start, and leaves completed", () => {
    const ended = apply(load(), C.JUMP_TO_END);
    const backward = apply(ended, C.STEP_BACKWARD);
    assert.equal(backward.machine.state, S.REPLAY_READY);
    assert.equal(backward.replayCursor, XRP_REPLAY_FIXTURE.events.at(-2).timestamp);
    assert.equal(backward.projection.replayCursor, backward.replayCursor);
    assert.equal(apply(load(), C.STEP_BACKWARD).rejectionReason, "ALREADY_AT_START");
});

test("seek clamps range and pauses when initiated while playing", () => {
    const ready = load();
    const middle = apply(ready, C.SEEK, { timestamp: "2026-07-20T12:00:16.000Z" });
    assert.equal(middle.replayCursor, "2026-07-20T12:00:16.000Z");
    assert.equal(middle.projection.currentEvent.id, "replay-event-004");
    assert.equal(apply(ready, C.SEEK, { timestamp: "2020-01-01T00:00:00Z" }).replayCursor,
        XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(apply(ready, C.SEEK, { timestamp: "2030-01-01T00:00:00Z" }).replayCursor,
        XRP_REPLAY_FIXTURE.endedAt);
    const playing = apply(ready, C.PLAY);
    assert.equal(apply(playing, C.SEEK, { timestamp: ready.replayCursor }).machine.state, S.PAUSED);
    assert.equal(apply(ready, C.SEEK, { timestamp: "invalid" }).accepted, false);
});

test("jump commands synchronize cursor, projection, and machine", () => {
    const playing = apply(load(), C.PLAY);
    const start = apply(playing, C.JUMP_TO_START);
    assert.equal(start.machine.state, S.PAUSED);
    assert.equal(start.replayCursor, XRP_REPLAY_FIXTURE.startedAt);
    const end = apply(start, C.JUMP_TO_END);
    assert.equal(end.machine.state, S.COMPLETED);
    assert.equal(end.replayCursor, XRP_REPLAY_FIXTURE.endedAt);
    assert.equal(end.projection.currentEvent.id, "replay-event-010");
});

test("reach end is explicit and restart restores the start", () => {
    const ready = load();
    assert.equal(apply(ready, C.REACH_END).accepted, false);
    const completed = apply(apply(ready, C.PLAY), C.REACH_END);
    assert.equal(completed.machine.state, S.COMPLETED);
    assert.equal(completed.replayCursor, XRP_REPLAY_FIXTURE.endedAt);
    const restarted = apply(completed, C.RESTART);
    assert.equal(restarted.machine.state, S.REPLAY_READY);
    assert.equal(restarted.replayCursor, XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(restarted.projection.currentEvent.id, "replay-event-001");
});

test("external load failure clears replay and retry only enters loading", () => {
    const failed = apply(load(), C.LOAD_FAILURE, {
        code: "REPLAY_UNAVAILABLE",
        message: "Unavailable.",
    });
    assert.equal(failed.machine.state, S.REPLAY_ERROR);
    assert.equal(failed.dataset, null);
    assert.equal(failed.projection.currentEvent, null);
    const retrying = apply(failed, C.RETRY);
    assert.equal(retrying.machine.state, S.REPLAY_LOADING);
    assert.equal(retrying.machine.error, null);
    assert.equal(retrying.engineError, null);
});

test("reset clears all replay data from any state", () => {
    const engine = apply(apply(load(), C.PLAY), C.RESET);
    assert.equal(engine.machine.state, S.IDLE);
    assert.equal(engine.dataset, null);
    assert.equal(engine.replayCursor, null);
    assert.equal(engine.projection.currentEvent, null);
    assert.equal(engine.lastCommand, C.RESET);
    assert.equal(engine.accepted, true);
});

test("invalid commands and missing data reject without advancing accepted state", () => {
    const initial = createInitialReplayEngineState();
    for (const invalid of [null, undefined, "PLAY", {}, { type: "UNKNOWN" }]) {
        const rejected = applyReplayCommand(initial, invalid);
        assert.equal(rejected.accepted, false);
        assert.equal(typeof rejected.rejectionReason, "string");
        assert.equal(rejected.lastCommand, initial.lastCommand);
        assert.equal(rejected.machine.transitionCount, initial.machine.transitionCount);
    }
    for (const type of [C.STEP_FORWARD, C.STEP_BACKWARD, C.JUMP_TO_START, C.JUMP_TO_END]) {
        assert.equal(apply(initial, type).accepted, false);
    }
    assert.equal(apply(initial, C.PLAY).accepted, false);
    assert.equal(canApplyReplayCommand(initial, command(C.LOAD_DATASET, {
        dataset: XRP_REPLAY_FIXTURE,
    })), true);
});

test("cursor-changing commands keep projection synchronized and future-safe", () => {
    let engine = load();
    for (const [type, payload] of [
        [C.STEP_FORWARD],
        [C.SEEK, { timestamp: "2026-07-20T12:00:44.000Z" }],
        [C.JUMP_TO_END],
        [C.RESTART],
    ]) {
        engine = apply(engine, type, payload);
        assert.equal(engine.projection.replayCursor, engine.replayCursor);
        assert.equal(engine.projection.visibleEvents.every(
            (event) => Date.parse(event.timestamp) <= Date.parse(engine.replayCursor),
        ), true);
    }
});

test("engine, dataset, command, and prior projection remain immutable", () => {
    const engine = load(clone(XRP_REPLAY_FIXTURE));
    const engineBefore = clone(engine);
    const seekCommand = command(C.SEEK, { timestamp: "2026-07-20T12:00:45.000Z" });
    const commandBefore = clone(seekCommand);
    applyReplayCommand(engine, seekCommand);
    assert.deepEqual(engine, engineBefore);
    assert.deepEqual(seekCommand, commandBefore);
});

test("identical engine and command inputs are deterministic", () => {
    const first = load(clone(XRP_REPLAY_FIXTURE));
    const second = clone(first);
    const seekCommand = command(C.SEEK, { timestamp: "2026-07-20T12:00:45.000Z" });
    assert.deepEqual(
        applyReplayCommand(first, seekCommand),
        applyReplayCommand(second, clone(seekCommand)),
    );
});
