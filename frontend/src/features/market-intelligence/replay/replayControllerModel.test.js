import assert from "node:assert/strict";
import test from "node:test";

import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import {
    buildReplayControllerModel,
    convertSeekPercentToTimestamp,
    convertTimestampToSeekPercent,
} from "./replayControllerModel.js";

const apply = (engine, type, payload) => applyReplayCommand(engine, { type, payload });
const loaded = () => apply(createInitialReplayEngineState(), C.LOAD_DATASET, {
    dataset: XRP_REPLAY_FIXTURE,
});

test("IDLE model is safe and only load is enabled", () => {
    const model = buildReplayControllerModel(createInitialReplayEngineState());
    assert.equal(model.machineState, "IDLE");
    assert.equal(model.datasetSummary.id, "—");
    assert.equal(model.cursor, "—");
    assert.equal(model.progressPercent, 0);
    assert.deepEqual(model.controls, {
        canLoad: true,
        canPlay: false,
        canPause: false,
        canStepBackward: false,
        canStepForward: false,
        canJumpStart: false,
        canJumpEnd: false,
        canRestart: false,
        canReset: false,
        canRetry: false,
        canSeek: false,
    });
});

test("READY, PLAYING, PAUSED, and COMPLETED controls follow engine state", () => {
    const ready = loaded();
    assert.equal(buildReplayControllerModel(ready).controls.canPlay, true);
    assert.equal(buildReplayControllerModel(ready).controls.canStepBackward, false);
    const playing = apply(ready, C.PLAY);
    const playingControls = buildReplayControllerModel(playing).controls;
    assert.equal(playingControls.canPause, true);
    assert.equal(playingControls.canLoad, false);
    assert.equal(playingControls.canStepForward, false);
    const paused = apply(playing, C.PAUSE);
    assert.equal(buildReplayControllerModel(paused).controls.canPlay, true);
    const completed = apply(paused, C.JUMP_TO_END);
    const completedControls = buildReplayControllerModel(completed).controls;
    assert.equal(completedControls.canRestart, true);
    assert.equal(completedControls.canStepForward, false);
    assert.equal(completedControls.canStepBackward, true);
});

test("ERROR enables retry and retry loading permits explicit reload", () => {
    const error = apply(createInitialReplayEngineState(), C.LOAD_FAILURE, {
        code: "FAIL",
        message: "Failed.",
    });
    const errorModel = buildReplayControllerModel(error);
    assert.equal(errorModel.controls.canRetry, true);
    assert.deepEqual(errorModel.error, { code: "FAIL", message: "Failed." });
    const retrying = apply(error, C.RETRY);
    assert.equal(buildReplayControllerModel(retrying).controls.canLoad, true);
});

test("rejections remain visible while replay summary remains available", () => {
    const ready = loaded();
    const rejected = apply(ready, C.PAUSE);
    const model = buildReplayControllerModel(rejected);
    assert.equal(model.accepted, false);
    assert.equal(typeof model.rejectionReason, "string");
    assert.equal(model.datasetSummary.id, XRP_REPLAY_FIXTURE.datasetId);
    assert.equal(model.cursor, ready.replayCursor);
});

test("seek conversion maps 0, 50, and 100 percent to replay range", () => {
    assert.equal(convertSeekPercentToTimestamp(XRP_REPLAY_FIXTURE, 0),
        XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(convertSeekPercentToTimestamp(XRP_REPLAY_FIXTURE, 50),
        "2026-07-20T12:00:45.000Z");
    assert.equal(convertSeekPercentToTimestamp(XRP_REPLAY_FIXTURE, 100),
        XRP_REPLAY_FIXTURE.endedAt);
    assert.equal(convertTimestampToSeekPercent(
        XRP_REPLAY_FIXTURE,
        "2026-07-20T12:00:45.000Z",
    ), 50);
});

test("seek conversion clamps, rejects invalid values, and handles zero duration", () => {
    assert.equal(convertSeekPercentToTimestamp(XRP_REPLAY_FIXTURE, -10),
        XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(convertSeekPercentToTimestamp(XRP_REPLAY_FIXTURE, 110),
        XRP_REPLAY_FIXTURE.endedAt);
    assert.equal(convertSeekPercentToTimestamp(XRP_REPLAY_FIXTURE, "invalid"), null);
    assert.equal(convertSeekPercentToTimestamp(null, 50), null);
    const zero = { ...XRP_REPLAY_FIXTURE, endedAt: XRP_REPLAY_FIXTURE.startedAt };
    assert.equal(convertSeekPercentToTimestamp(zero, 50), zero.startedAt);
    assert.equal(convertTimestampToSeekPercent(zero, zero.startedAt), 0);
});
