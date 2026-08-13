import assert from "node:assert/strict";
import test from "node:test";

import {
    DATA_STATE,
    DATA_STATE_VALUES,
    createIdleDataState,
    createLoadingDataState,
    createSuccessDataState,
    createEmptyDataState,
    createErrorDataState,
    createUnavailableDataState,
    isValidDataState,
} from "./recorderDataState.js";

test("DATA_STATE values are frozen and immutable", () => {
    assert.equal(typeof DATA_STATE, "object");
    assert.equal(DATA_STATE.IDLE, "idle");
    assert.equal(DATA_STATE.LOADING, "loading");
    assert.equal(DATA_STATE.SUCCESS, "success");
    assert.equal(DATA_STATE.EMPTY, "empty");
    assert.equal(DATA_STATE.ERROR, "error");
    assert.equal(DATA_STATE.UNAVAILABLE, "unavailable");
    assert.throws(() => { DATA_STATE.NEW = "new"; }, TypeError);
});

test("DATA_STATE_VALUES contains all six states", () => {
    assert.equal(DATA_STATE_VALUES.size, 6);
    assert.ok(DATA_STATE_VALUES.has("idle"));
    assert.ok(DATA_STATE_VALUES.has("loading"));
    assert.ok(DATA_STATE_VALUES.has("success"));
    assert.ok(DATA_STATE_VALUES.has("empty"));
    assert.ok(DATA_STATE_VALUES.has("error"));
    assert.ok(DATA_STATE_VALUES.has("unavailable"));
});

test("isValidDataState returns true for valid states", () => {
    assert.ok(isValidDataState("idle"));
    assert.ok(isValidDataState("loading"));
    assert.ok(isValidDataState("success"));
    assert.ok(isValidDataState("empty"));
    assert.ok(isValidDataState("error"));
    assert.ok(isValidDataState("unavailable"));
});

test("isValidDataState returns false for unknown states", () => {
    assert.equal(isValidDataState("unknown"), false);
    assert.equal(isValidDataState(""), false);
    assert.equal(isValidDataState(null), false);
    assert.equal(isValidDataState(undefined), false);
    assert.equal(isValidDataState(123), false);
});

test("createIdleDataState produces consistent idle state", () => {
    const state = createIdleDataState();
    assert.equal(state.status, DATA_STATE.IDLE);
    assert.equal(state.data, null);
    assert.equal(state.error, null);
    assert.equal(state.updatedAt, null);
    assert.equal(state.isLoading, false);
    assert.equal(state.isSuccess, false);
    assert.equal(state.isEmpty, false);
    assert.equal(state.isError, false);
    assert.equal(state.isUnavailable, false);
});

test("createLoadingDataState produces consistent loading state", () => {
    const state = createLoadingDataState();
    assert.equal(state.status, DATA_STATE.LOADING);
    assert.equal(state.data, null);
    assert.equal(state.error, null);
    assert.equal(state.isLoading, true);
    assert.equal(state.isSuccess, false);
    assert.equal(state.isEmpty, false);
    assert.equal(state.isError, false);
    assert.equal(state.isUnavailable, false);
});

test("createSuccessDataState stores data and sets correct flags", () => {
    const data = { key: "value" };
    const state = createSuccessDataState(data);
    assert.equal(state.status, DATA_STATE.SUCCESS);
    assert.equal(state.data, data);
    assert.equal(state.error, null);
    assert.ok(state.updatedAt > 0);
    assert.equal(state.isLoading, false);
    assert.equal(state.isSuccess, true);
    assert.equal(state.isEmpty, false);
    assert.equal(state.isError, false);
    assert.equal(state.isUnavailable, false);
});

test("createEmptyDataState produces consistent empty state", () => {
    const state = createEmptyDataState();
    assert.equal(state.status, DATA_STATE.EMPTY);
    assert.equal(state.data, null);
    assert.equal(state.error, null);
    assert.equal(state.isLoading, false);
    assert.equal(state.isSuccess, false);
    assert.equal(state.isEmpty, true);
    assert.equal(state.isError, false);
    assert.equal(state.isUnavailable, false);
});

test("createErrorDataState stores error and sets correct flags", () => {
    const error = { message: "fail" };
    const state = createErrorDataState(error);
    assert.equal(state.status, DATA_STATE.ERROR);
    assert.equal(state.data, null);
    assert.equal(state.error, error);
    assert.equal(state.isLoading, false);
    assert.equal(state.isSuccess, false);
    assert.equal(state.isEmpty, false);
    assert.equal(state.isError, true);
    assert.equal(state.isUnavailable, false);
});

test("createErrorDataState handles null error", () => {
    const state = createErrorDataState(null);
    assert.equal(state.status, DATA_STATE.ERROR);
    assert.equal(state.error, null);
    assert.equal(state.isError, true);
});

test("createErrorDataState handles undefined error", () => {
    const state = createErrorDataState(undefined);
    assert.equal(state.status, DATA_STATE.ERROR);
    assert.equal(state.error, null);
    assert.equal(state.isError, true);
});

test("createUnavailableDataState produces consistent unavailable state", () => {
    const state = createUnavailableDataState();
    assert.equal(state.status, DATA_STATE.UNAVAILABLE);
    assert.equal(state.data, null);
    assert.equal(state.error, null);
    assert.equal(state.isLoading, false);
    assert.equal(state.isSuccess, false);
    assert.equal(state.isEmpty, false);
    assert.equal(state.isError, false);
    assert.equal(state.isUnavailable, true);
});

test("success state cannot have contradictory error", () => {
    const state = createSuccessDataState({ a: 1 });
    assert.equal(state.error, null);
    assert.equal(state.isError, false);
});

test("error state cannot have contradictory success flag", () => {
    const state = createErrorDataState({ code: "X" });
    assert.equal(state.data, null);
    assert.equal(state.isSuccess, false);
});

test("empty state cannot have data", () => {
    const state = createEmptyDataState();
    assert.equal(state.data, null);
    assert.equal(state.isSuccess, false);
});
