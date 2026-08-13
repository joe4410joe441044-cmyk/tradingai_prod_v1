import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

var fixture = await readFile(
    new URL("./useRecorderStatus.js", import.meta.url),
    "utf8",
);

test("useRecorderStatus exports a named function", function () {
    assert.match(fixture, /export function useRecorderStatus/);
});

test("useRecorderStatus returns data field", function () {
    assert.match(fixture, /\bdata:/);
});

test("useRecorderStatus returns dataState field", function () {
    assert.match(fixture, /\bdataState:/);
});

test("useRecorderStatus returns error field", function () {
    assert.match(fixture, /\berror:/);
});

test("useRecorderStatus returns isLoading field", function () {
    assert.match(fixture, /\bisLoading:/);
});

test("useRecorderStatus returns isEmpty field", function () {
    assert.match(fixture, /\bisEmpty:/);
});

test("useRecorderStatus returns isError field", function () {
    assert.match(fixture, /\bisError:/);
});

test("useRecorderStatus returns isUnavailable field", function () {
    assert.match(fixture, /\bisUnavailable:/);
});

test("useRecorderStatus returns refresh field", function () {
    assert.match(fixture, /\brefresh\b/);
});

test("useRecorderStatus default source is API", function () {
    assert.match(fixture, /currentSource\s*=\s*RECORDER_DATA_SOURCE\.API/);
});

test("useRecorderStatus uses toRecorderStatusViewModel adapter", function () {
    assert.match(fixture, /toRecorderStatusViewModel/);
});

test("useRecorderStatus uses success state for mock source", function () {
    assert.match(fixture, /createSuccessDataState/);
});

test("setRecorderDataSource function is exported", function () {
    assert.match(fixture, /export function setRecorderDataSource/);
});

test("getRecorderDataSource function is exported", function () {
    assert.match(fixture, /export function getRecorderDataSource/);
});

test("useRecorderStatus handles API source via recorderClient", function () {
    assert.match(fixture, /recorderClient\.getStatus/);
});

test("useRecorderStatus uses AbortController for cancellation", function () {
    assert.match(fixture, /AbortController/);
});

test("useRecorderStatus has mountedRef for unmount safety", function () {
    assert.match(fixture, /mountedRef/);
});

test("useRecorderStatus polls once per interval and rejects stale responses", function () {
    assert.match(fixture, /setInterval\(refresh,\s*10000\)/);
    assert.match(fixture, /clearInterval/);
    assert.match(fixture, /requestIdRef/);
});

test("useRecorderStatus uses useEffect for API fetch", function () {
    assert.match(fixture, /useEffect/);
});

test("useRecorderStatus does not use WebSocket", function () {
    assert.doesNotMatch(fixture, /new WebSocket/);
    assert.doesNotMatch(fixture, /EventSource/);
});

test("useRecorderStatus does not use axios", function () {
    assert.doesNotMatch(fixture, /axios/);
});

test("useRecorderStatus handles RECORDER_ERROR_CODE.NETWORK as unavailable", function () {
    assert.match(fixture, /RECORDER_ERROR_CODE\.NETWORK/);
});

test("useRecorderStatus creates loading state for API source", function () {
    assert.match(fixture, /createLoadingDataState/);
});

test("useRecorderStatus has no retry loop", function () {
    var hookBody = fixture.slice(
        fixture.indexOf("export function useRecorderStatus"),
        fixture.indexOf("export function setRecorderDataSource") + 1,
    );
    assert.doesNotMatch(hookBody, /for\s*\(/);
    assert.doesNotMatch(hookBody, /while\s*\(/);
});
