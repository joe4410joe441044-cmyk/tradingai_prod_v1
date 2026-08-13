import assert from "node:assert/strict";
import test from "node:test";

import {
    formatBytes,
    formatDuration,
    formatUtcDate,
    formatRecorderStatus,
} from "./recorderFormatters.js";

const PLACEHOLDER = "--";

test("formatBytes formats 0 bytes", () => {
    assert.equal(formatBytes(0), "0 B");
});

test("formatBytes formats bytes less than 1024", () => {
    assert.equal(formatBytes(500), "500 B");
    assert.equal(formatBytes(1023), "1023 B");
});

test("formatBytes formats KB", () => {
    assert.equal(formatBytes(1024), "1.00 KB");
    assert.equal(formatBytes(2048), "2.00 KB");
    assert.equal(formatBytes(1536), "1.50 KB");
});

test("formatBytes formats MB", () => {
    assert.equal(formatBytes(1048576), "1.00 MB");
    assert.equal(formatBytes(5242880), "5.00 MB");
});

test("formatBytes formats GB", () => {
    assert.equal(formatBytes(1073741824), "1.00 GB");
});

test("formatBytes formats TB", () => {
    assert.equal(formatBytes(1099511627776), "1.00 TB");
});

test("formatBytes handles NaN", () => {
    assert.equal(formatBytes(NaN), PLACEHOLDER);
});

test("formatBytes handles Infinity", () => {
    assert.equal(formatBytes(Infinity), PLACEHOLDER);
    assert.equal(formatBytes(-Infinity), PLACEHOLDER);
});

test("formatBytes handles negative input", () => {
    assert.equal(formatBytes(-1), PLACEHOLDER);
    assert.equal(formatBytes(-1000), PLACEHOLDER);
});

test("formatBytes handles null", () => {
    assert.equal(formatBytes(null), PLACEHOLDER);
});

test("formatBytes handles undefined", () => {
    assert.equal(formatBytes(undefined), PLACEHOLDER);
});

test("formatBytes handles non-number input", () => {
    assert.equal(formatBytes("1024"), PLACEHOLDER);
    assert.equal(formatBytes(true), PLACEHOLDER);
    assert.equal(formatBytes([]), PLACEHOLDER);
    assert.equal(formatBytes({}), PLACEHOLDER);
});

test("formatDuration formats zero seconds", () => {
    assert.equal(formatDuration(0), "00:00:00");
});

test("formatDuration formats seconds only", () => {
    assert.equal(formatDuration(45), "00:00:45");
    assert.equal(formatDuration(5), "00:00:05");
});

test("formatDuration formats minutes and seconds", () => {
    assert.equal(formatDuration(65), "00:01:05");
    assert.equal(formatDuration(125), "00:02:05");
});

test("formatDuration formats hours, minutes, seconds", () => {
    assert.equal(formatDuration(3661), "01:01:01");
    assert.equal(formatDuration(5025), "01:23:45");
    assert.equal(formatDuration(3600), "01:00:00");
});

test("formatDuration handles null", () => {
    assert.equal(formatDuration(null), PLACEHOLDER);
});

test("formatDuration handles undefined", () => {
    assert.equal(formatDuration(undefined), PLACEHOLDER);
});

test("formatDuration handles NaN", () => {
    assert.equal(formatDuration(NaN), PLACEHOLDER);
});

test("formatDuration handles Infinity", () => {
    assert.equal(formatDuration(Infinity), PLACEHOLDER);
});

test("formatDuration handles negative input", () => {
    assert.equal(formatDuration(-10), PLACEHOLDER);
});

test("formatDuration handles non-number input", () => {
    assert.equal(formatDuration("3600"), PLACEHOLDER);
    assert.equal(formatDuration(true), PLACEHOLDER);
});

test("formatUtcDate formats valid ISO timestamp", () => {
    assert.equal(formatUtcDate("2026-07-31T00:00:00Z"), "2026-07-31");
    assert.equal(formatUtcDate("2026-01-01T12:30:00Z"), "2026-01-01");
});

test("formatUtcDate handles date-only strings", () => {
    assert.equal(formatUtcDate("2026-07-31"), "2026-07-31");
});

test("formatUtcDate handles invalid timestamp", () => {
    assert.equal(formatUtcDate("not-a-date"), PLACEHOLDER);
    assert.equal(formatUtcDate(""), PLACEHOLDER);
});

test("formatUtcDate handles null", () => {
    assert.equal(formatUtcDate(null), PLACEHOLDER);
});

test("formatUtcDate handles undefined", () => {
    assert.equal(formatUtcDate(undefined), PLACEHOLDER);
});

test("formatUtcDate handles non-string input", () => {
    assert.equal(formatUtcDate(12345), PLACEHOLDER);
    assert.equal(formatUtcDate(true), PLACEHOLDER);
});

test("formatUtcDate handles short string", () => {
    assert.equal(formatUtcDate("abc"), PLACEHOLDER);
});

test("formatRecorderStatus formats RUNNING variants", () => {
    assert.equal(formatRecorderStatus("RUNNING"), "RUNNING");
    assert.equal(formatRecorderStatus("running"), "RUNNING");
    assert.equal(formatRecorderStatus("Running"), "RUNNING");
    assert.equal(formatRecorderStatus("RECORDING"), "RUNNING");
    assert.equal(formatRecorderStatus("recording"), "RUNNING");
});

test("formatRecorderStatus formats STOPPED variants", () => {
    assert.equal(formatRecorderStatus("STOPPED"), "STOPPED");
    assert.equal(formatRecorderStatus("stopped"), "STOPPED");
    assert.equal(formatRecorderStatus("Stopped"), "STOPPED");
});

test("formatRecorderStatus handles unknown status", () => {
    assert.equal(formatRecorderStatus("PAUSED"), PLACEHOLDER);
    assert.equal(formatRecorderStatus("UNKNOWN"), PLACEHOLDER);
    assert.equal(formatRecorderStatus(""), PLACEHOLDER);
});

test("formatRecorderStatus handles null", () => {
    assert.equal(formatRecorderStatus(null), PLACEHOLDER);
});

test("formatRecorderStatus handles undefined", () => {
    assert.equal(formatRecorderStatus(undefined), PLACEHOLDER);
});

test("formatRecorderStatus handles non-string input", () => {
    assert.equal(formatRecorderStatus(123), PLACEHOLDER);
    assert.equal(formatRecorderStatus(true), PLACEHOLDER);
});

test("formatters do not throw on any input", () => {
    const inputs = [null, undefined, NaN, Infinity, -Infinity, "", "invalid", 0, -1, {}, [], true, false];
    for (const input of inputs) {
        assert.doesNotThrow(() => formatBytes(input));
        assert.doesNotThrow(() => formatDuration(input));
        assert.doesNotThrow(() => formatUtcDate(input));
        assert.doesNotThrow(() => formatRecorderStatus(input));
    }
});
