import assert from "node:assert/strict";
import test from "node:test";

import {
    REPLAY_MACHINE_EVENTS as E,
    REPLAY_STATES as S,
    canTransitionReplayState,
    createInitialReplayMachineState,
    transitionReplayState,
} from "./replayStateMachine.js";

const send = (machine, type, payload) => transitionReplayState(machine, { type, payload });
const reachReady = () => {
    let machine = createInitialReplayMachineState();
    machine = send(machine, E.SELECT_POSITION);
    machine = send(machine, E.START_LOADING);
    return send(machine, E.LOAD_SUCCESS);
};

test("exports every required immutable state and event constant", () => {
    assert.deepEqual(Object.values(S), [
        "IDLE", "POSITION_SELECTED", "REPLAY_LOADING", "REPLAY_READY", "PLAYING",
        "PAUSED", "SEEKING", "COMPLETED", "REPLAY_ERROR",
    ]);
    assert.deepEqual(Object.values(E), [
        "SELECT_POSITION", "START_LOADING", "LOAD_SUCCESS", "LOAD_FAILURE", "PLAY",
        "PAUSE", "SEEK", "SEEK_COMPLETE", "STEP", "REACH_END", "RESTART", "RESET",
        "RETRY",
    ]);
    assert.equal(Object.isFrozen(S), true);
    assert.equal(Object.isFrozen(E), true);
});

test("creates a fresh canonical initial state", () => {
    const first = createInitialReplayMachineState();
    const second = createInitialReplayMachineState();
    assert.deepEqual(first, {
        state: S.IDLE,
        resumeState: null,
        error: null,
        transitionCount: 0,
        lastEvent: null,
    });
    assert.notEqual(first, second);
});

test("supports the normal loading, playback, pause, completion, and restart flow", () => {
    let machine = createInitialReplayMachineState();
    machine = send(machine, E.SELECT_POSITION);
    assert.equal(machine.state, S.POSITION_SELECTED);
    machine = send(machine, E.START_LOADING);
    assert.equal(machine.state, S.REPLAY_LOADING);
    machine = send(machine, E.LOAD_SUCCESS);
    assert.equal(machine.state, S.REPLAY_READY);
    machine = send(machine, E.PLAY);
    assert.equal(machine.state, S.PLAYING);
    machine = send(machine, E.PAUSE);
    assert.equal(machine.state, S.PAUSED);
    machine = send(machine, E.PLAY);
    machine = send(machine, E.REACH_END);
    assert.equal(machine.state, S.COMPLETED);
    machine = send(machine, E.RESTART);
    assert.equal(machine.state, S.REPLAY_READY);
    assert.equal(machine.error, null);
});

test("load failure enters error and retry returns to loading", () => {
    let machine = send(createInitialReplayMachineState(), E.SELECT_POSITION);
    machine = send(machine, E.START_LOADING);
    machine = send(machine, E.LOAD_FAILURE, { code: "UNAVAILABLE", message: "Unavailable." });
    assert.equal(machine.state, S.REPLAY_ERROR);
    assert.deepEqual(machine.error, { code: "UNAVAILABLE", message: "Unavailable." });
    machine = send(machine, E.RETRY);
    assert.equal(machine.state, S.REPLAY_LOADING);
    assert.equal(machine.error, null);
});

test("load failure while playing is accepted", () => {
    const playing = send(reachReady(), E.PLAY);
    const failed = send(playing, E.LOAD_FAILURE);
    assert.equal(failed.state, S.REPLAY_ERROR);
    assert.equal(failed.accepted, true);
});

test("seek returns ready and paused origins safely", () => {
    const ready = reachReady();
    const seekingFromReady = send(ready, E.SEEK);
    assert.equal(seekingFromReady.resumeState, S.REPLAY_READY);
    const readyAgain = send(seekingFromReady, E.SEEK_COMPLETE);
    assert.equal(readyAgain.state, S.REPLAY_READY);
    assert.equal(readyAgain.resumeState, null);

    const paused = send(send(ready, E.PLAY), E.PAUSE);
    const seekingFromPaused = send(paused, E.SEEK);
    assert.equal(seekingFromPaused.resumeState, S.PAUSED);
    assert.equal(send(seekingFromPaused, E.SEEK_COMPLETE).state, S.PAUSED);
});

test("seek from playing completes paused and never auto-resumes", () => {
    const playing = send(reachReady(), E.PLAY);
    const seeking = send(playing, E.SEEK);
    assert.equal(seeking.resumeState, S.PLAYING);
    const completed = send(seeking, E.SEEK_COMPLETE);
    assert.equal(completed.state, S.PAUSED);
    assert.equal(completed.resumeState, null);
});

test("seek from completed safely returns to completed", () => {
    const completed = send(send(reachReady(), E.PLAY), E.REACH_END);
    const seeking = send(completed, E.SEEK);
    assert.equal(seeking.resumeState, S.COMPLETED);
    assert.equal(send(seeking, E.SEEK_COMPLETE).state, S.COMPLETED);
});

test("step is an accepted same-state transition and increments count", () => {
    const ready = reachReady();
    const steppedReady = send(ready, E.STEP);
    assert.equal(steppedReady.state, S.REPLAY_READY);
    assert.equal(steppedReady.accepted, true);
    assert.equal(steppedReady.transitionCount, ready.transitionCount + 1);

    const paused = send(send(ready, E.PLAY), E.PAUSE);
    assert.equal(send(paused, E.STEP).state, S.PAUSED);
});

test("failure defaults are safe and success clears prior error", () => {
    let loading = send(send(createInitialReplayMachineState(), E.SELECT_POSITION), E.START_LOADING);
    const failed = send(loading, E.LOAD_FAILURE);
    assert.deepEqual(failed.error, {
        code: "REPLAY_LOAD_FAILED",
        message: "Replay loading failed.",
    });
    loading = send(failed, E.RETRY);
    const succeeded = send(loading, E.LOAD_SUCCESS);
    assert.equal(succeeded.error, null);
});

test("reset is accepted from every state and returns a fresh reset state", () => {
    const samples = [
        createInitialReplayMachineState(),
        reachReady(),
        send(reachReady(), E.PLAY),
        send(send(reachReady(), E.PLAY), E.REACH_END),
    ];
    for (const sample of samples) {
        const reset = send(sample, E.RESET);
        assert.deepEqual(reset, {
            state: S.IDLE,
            resumeState: null,
            error: null,
            transitionCount: 0,
            lastEvent: E.RESET,
            accepted: true,
            rejectionReason: null,
        });
        assert.notEqual(reset, sample);
    }
});

test("invalid transitions and malformed events are safely rejected", () => {
    const idle = createInitialReplayMachineState();
    for (const event of [
        { type: E.PLAY },
        { type: "UNKNOWN" },
        null,
        undefined,
        "PLAY",
    ]) {
        const rejected = transitionReplayState(idle, event);
        assert.equal(rejected.state, S.IDLE);
        assert.equal(rejected.transitionCount, 0);
        assert.equal(rejected.accepted, false);
        assert.equal(typeof rejected.rejectionReason, "string");
    }
    assert.equal(send(send(idle, E.SELECT_POSITION), E.PLAY).accepted, false);
    assert.equal(send(send(reachReady(), E.PLAY), E.PLAY).accepted, false);
    const errored = send(
        send(send(idle, E.SELECT_POSITION), E.START_LOADING),
        E.LOAD_FAILURE,
    );
    assert.equal(send(errored, E.PLAY).accepted, false);
});

test("canTransition reports allowed and rejected transitions without mutation", () => {
    const idle = createInitialReplayMachineState();
    const original = structuredClone(idle);
    assert.equal(canTransitionReplayState(idle, { type: E.SELECT_POSITION }), true);
    assert.equal(canTransitionReplayState(idle, { type: E.PLAY }), false);
    assert.equal(canTransitionReplayState(idle, null), false);
    assert.deepEqual(idle, original);
});

test("transitions do not mutate state, event, payload, or error input", () => {
    const loading = send(send(createInitialReplayMachineState(), E.SELECT_POSITION), E.START_LOADING);
    const stateBefore = structuredClone(loading);
    const payload = { code: "FAIL", message: "Failed.", nested: { untouched: true } };
    const event = { type: E.LOAD_FAILURE, payload };
    const eventBefore = structuredClone(event);
    const failed = transitionReplayState(loading, event);
    assert.deepEqual(loading, stateBefore);
    assert.deepEqual(event, eventBefore);
    assert.notEqual(failed.error, payload);
    payload.code = "CHANGED";
    assert.equal(failed.error.code, "FAIL");
});

test("the machine is deterministic for identical inputs", () => {
    const initialA = createInitialReplayMachineState();
    const initialB = createInitialReplayMachineState();
    const eventA = { type: E.SELECT_POSITION, payload: { positionId: "ignored" } };
    const eventB = structuredClone(eventA);
    assert.deepEqual(
        transitionReplayState(initialA, eventA),
        transitionReplayState(initialB, eventB),
    );
});
