import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

var fixture = await readFile(
    new URL("./useRecorderArchives.js", import.meta.url),
    "utf8",
);

test("useRecorderArchives exports a named function", function () {
    assert.match(fixture, /export function useRecorderArchives/);
});

test("useRecorderArchives returns data field", function () {
    assert.match(fixture, /\bdata:/);
});

test("useRecorderArchives returns dataState field", function () {
    assert.match(fixture, /\bdataState:/);
});

test("useRecorderArchives returns error field", function () {
    assert.match(fixture, /\berror:/);
});

test("useRecorderArchives returns isLoading field", function () {
    assert.match(fixture, /\bisLoading:/);
});

test("useRecorderArchives returns isEmpty field", function () {
    assert.match(fixture, /\bisEmpty:/);
});

test("useRecorderArchives returns isError field", function () {
    assert.match(fixture, /\bisError:/);
});

test("useRecorderArchives returns isUnavailable field", function () {
    assert.match(fixture, /\bisUnavailable:/);
});

test("useRecorderArchives returns refresh field", function () {
    assert.match(fixture, /\brefresh\b/);
});

test("useRecorderArchives uses empty state when no archives", function () {
    assert.match(fixture, /createEmptyDataState/);
});

test("useRecorderArchives uses mock data as default source", function () {
    assert.match(fixture, /RECORDER_DATA_SOURCE\.MOCK/);
});

test("useRecorderArchives does not use WebSocket", function () {
    assert.doesNotMatch(fixture, /new WebSocket/);
    assert.doesNotMatch(fixture, /EventSource/);
});

test("useRecorderArchives does not use axios", function () {
    assert.doesNotMatch(fixture, /axios/);
});

test("useRecorderArchives uses toRecorderArchivesViewModel adapter", function () {
    assert.match(fixture, /toRecorderArchivesViewModel/);
});

test("useRecorderArchives uses recorderClient for API source", function () {
    assert.match(fixture, /recorderClient\.getArchives/);
});

test("useRecorderArchives requests bounded latest-first pages", function () {
    assert.match(fixture, /ARCHIVE_PAGE_SIZE\s*=\s*20/);
    assert.match(fixture, /sort:\s*"start_time"/);
    assert.match(fixture, /order:\s*"desc"/);
    assert.match(fixture, /previousPage/);
    assert.match(fixture, /nextPage/);
});

test("useRecorderArchives uses AbortController for cancellation", function () {
    assert.match(fixture, /AbortController/);
});

test("useRecorderArchives handles RECORDER_ERROR_CODE.NETWORK as unavailable", function () {
    assert.match(fixture, /RECORDER_ERROR_CODE\.NETWORK/);
});

test("useRecorderArchives creates loading state for API source", function () {
    assert.match(fixture, /createLoadingDataState/);
});

test("useRecorderArchives has no retry loop", function () {
    var hookBody = fixture.slice(
        fixture.indexOf("export function useRecorderArchives"),
    );
    assert.doesNotMatch(hookBody, /for\s*\(/);
    assert.doesNotMatch(hookBody, /while\s*\(/);
});
