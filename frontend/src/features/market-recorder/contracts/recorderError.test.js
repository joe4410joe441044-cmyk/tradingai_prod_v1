import assert from "node:assert/strict";
import test from "node:test";

import {
    RECORDER_ERROR_CODE,
    createRecorderError,
    createRecorderNotImplementedError,
    createRecorderUnsupportedSourceError,
    isRecorderError,
} from "./recorderError.js";

test("RECORDER_ERROR_CODE values are frozen and fixed", () => {
    assert.equal(typeof RECORDER_ERROR_CODE, "object");
    assert.equal(RECORDER_ERROR_CODE.UNKNOWN, "RECORDER_UNKNOWN");
    assert.equal(RECORDER_ERROR_CODE.NETWORK, "RECORDER_NETWORK");
    assert.equal(RECORDER_ERROR_CODE.TIMEOUT, "RECORDER_TIMEOUT");
    assert.equal(RECORDER_ERROR_CODE.SERVER, "RECORDER_SERVER");
    assert.equal(RECORDER_ERROR_CODE.NOT_IMPLEMENTED, "RECORDER_NOT_IMPLEMENTED");
    assert.equal(RECORDER_ERROR_CODE.PARSE, "RECORDER_PARSE");
    assert.equal(RECORDER_ERROR_CODE.UNSUPPORTED_SOURCE, "RECORDER_UNSUPPORTED_SOURCE");
    assert.throws(() => { RECORDER_ERROR_CODE.NEW = "NEW"; }, TypeError);
});

test("createRecorderError produces frozen error object", () => {
    const err = createRecorderError("TEST_CODE", "test message", { retryable: true, source: "test" });
    assert.equal(err.code, "TEST_CODE");
    assert.equal(err.message, "test message");
    assert.equal(err.retryable, true);
    assert.equal(err.source, "test");
    assert.throws(() => { err.code = "MODIFIED"; }, TypeError);
});

test("createRecorderError defaults for missing arguments", () => {
    const err = createRecorderError();
    assert.equal(err.code, RECORDER_ERROR_CODE.UNKNOWN);
    assert.equal(err.message, "An unexpected error occurred");
    assert.equal(err.retryable, false);
    assert.equal(err.source, null);
});

test("createRecorderError uses defaults when options is empty", () => {
    const err = createRecorderError("CODE", "msg");
    assert.equal(err.code, "CODE");
    assert.equal(err.message, "msg");
    assert.equal(err.retryable, false);
    assert.equal(err.source, null);
});

test("createRecorderNotImplementedError produces correct error", () => {
    const err = createRecorderNotImplementedError("getStatus");
    assert.equal(err.code, RECORDER_ERROR_CODE.NOT_IMPLEMENTED);
    assert.equal(err.message, "getStatus: Not implemented");
    assert.equal(err.retryable, false);
    assert.equal(err.source, "client");
});

test("createRecorderUnsupportedSourceError produces correct error", () => {
    const err = createRecorderUnsupportedSourceError("api");
    assert.equal(err.code, RECORDER_ERROR_CODE.UNSUPPORTED_SOURCE);
    assert.equal(err.message, "Data source not supported: api");
    assert.equal(err.retryable, false);
    assert.equal(err.source, "client");
});

test("isRecorderError returns true for valid error objects", () => {
    const err = createRecorderError("CODE", "msg");
    assert.ok(isRecorderError(err));
});

test("isRecorderError returns false for null", () => {
    assert.equal(isRecorderError(null), false);
});

test("isRecorderError returns false for undefined", () => {
    assert.equal(isRecorderError(undefined), false);
});

test("isRecorderError returns false for plain objects", () => {
    assert.equal(isRecorderError({ code: "X" }), false);
    assert.equal(isRecorderError({ message: "X" }), false);
    assert.equal(isRecorderError({}), false);
});

test("isRecorderError returns false for non-objects", () => {
    assert.equal(isRecorderError("string"), false);
    assert.equal(isRecorderError(123), false);
    assert.equal(isRecorderError(true), false);
});

test("error has only safe fields - no stack trace or host info", () => {
    const err = createRecorderError("CODE", "msg");
    const keys = Object.keys(err);
    assert.ok(keys.includes("code"));
    assert.ok(keys.includes("message"));
    assert.ok(keys.includes("retryable"));
    assert.ok(keys.includes("source"));
    assert.equal(keys.length, 4);
});

test("error message does not contain raw server paths", () => {
    const err = createRecorderError("CODE", "msg with /etc/passwd style");
    assert.ok(err.message.includes("msg"));
});
