import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

var fixture = await readFile(
    new URL("./useRecorderStorage.js", import.meta.url),
    "utf8",
);

test("useRecorderStorage exports a named function", function () {
    assert.match(fixture, /export function useRecorderStorage/);
});

test("useRecorderStorage returns data field", function () {
    assert.match(fixture, /\bdata:/);
});

test("useRecorderStorage returns dataState field", function () {
    assert.match(fixture, /\bdataState:/);
});

test("useRecorderStorage returns error field", function () {
    assert.match(fixture, /\berror:/);
});

test("useRecorderStorage returns isLoading field", function () {
    assert.match(fixture, /\bisLoading:/);
});

test("useRecorderStorage returns isEmpty field", function () {
    assert.match(fixture, /\bisEmpty:/);
});

test("useRecorderStorage returns isError field", function () {
    assert.match(fixture, /\bisError:/);
});

test("useRecorderStorage returns isUnavailable field", function () {
    assert.match(fixture, /\bisUnavailable:/);
});

test("useRecorderStorage returns refresh field", function () {
    assert.match(fixture, /\brefresh\b/);
});

test("useRecorderStorage uses mock data as default source", function () {
    assert.match(fixture, /RECORDER_DATA_SOURCE\.MOCK/);
});

test("useRecorderStorage does not use WebSocket", function () {
    assert.doesNotMatch(fixture, /new WebSocket/);
    assert.doesNotMatch(fixture, /EventSource/);
});

test("useRecorderStorage does not use axios", function () {
    assert.doesNotMatch(fixture, /axios/);
});

test("useRecorderStorage uses toRecorderStorageViewModel adapter", function () {
    assert.match(fixture, /toRecorderStorageViewModel/);
});

test("useRecorderStorage uses recorderClient for API source", function () {
    assert.match(fixture, /recorderClient\.getStorage/);
});

test("useRecorderStorage uses AbortController for cancellation", function () {
    assert.match(fixture, /AbortController/);
});

test("useRecorderStorage handles RECORDER_ERROR_CODE.NETWORK as unavailable", function () {
    assert.match(fixture, /RECORDER_ERROR_CODE\.NETWORK/);
});

test("useRecorderStorage creates loading state for API source", function () {
    assert.match(fixture, /createLoadingDataState/);
});

test("useRecorderStorage has no retry loop", function () {
    var hookBody = fixture.slice(
        fixture.indexOf("export function useRecorderStorage"),
    );
    assert.doesNotMatch(hookBody, /for\s*\(/);
    assert.doesNotMatch(hookBody, /while\s*\(/);
});
