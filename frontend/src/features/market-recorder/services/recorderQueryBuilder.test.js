import assert from "node:assert/strict";
import test from "node:test";

import { buildArchivesQuery } from "./recorderQueryBuilder.js";

test("buildArchivesQuery returns empty string for null input", function () {
    assert.equal(buildArchivesQuery(null), "");
});

test("buildArchivesQuery returns empty string for undefined input", function () {
    assert.equal(buildArchivesQuery(undefined), "");
});

test("buildArchivesQuery returns empty string for empty object", function () {
    assert.equal(buildArchivesQuery({}), "");
});

test("buildArchivesQuery serializes page and page_size", function () {
    var result = buildArchivesQuery({ page: 2, page_size: 50 });
    assert.ok(result.startsWith("?"));
    assert.ok(result.includes("page=2"));
    assert.ok(result.includes("page_size=50"));
});

test("buildArchivesQuery uses default paging when unspecified", function () {
    var result = buildArchivesQuery({ symbol: "BTCUSDT" });
    assert.ok(!result.includes("page="));
    assert.equal(result, "?symbol=BTCUSDT");
});

test("buildArchivesQuery rejects page less than 1", function () {
    var result = buildArchivesQuery({ page: 0 });
    assert.ok(!result.includes("page="));
    assert.equal(result, "");

    result = buildArchivesQuery({ page: -1 });
    assert.equal(result, "");
});

test("buildArchivesQuery rejects page_size less than 1", function () {
    var result = buildArchivesQuery({ page_size: 0 });
    assert.equal(result, "");

    result = buildArchivesQuery({ page_size: -5 });
    assert.equal(result, "");
});

test("buildArchivesQuery rejects page_size greater than 200", function () {
    var result = buildArchivesQuery({ page_size: 201 });
    assert.equal(result, "");

    result = buildArchivesQuery({ page_size: 1000 });
    assert.equal(result, "");
});

test("buildArchivesQuery allows page_size 1 through 200", function () {
    assert.ok(buildArchivesQuery({ page_size: 1 }).includes("page_size=1"));
    assert.ok(buildArchivesQuery({ page_size: 200 }).includes("page_size=200"));
});

test("buildArchivesQuery serializes sort with allowed values", function () {
    assert.ok(buildArchivesQuery({ sort: "start_time" }).includes("sort=start_time"));
    assert.ok(buildArchivesQuery({ sort: "end_time" }).includes("sort=end_time"));
    assert.ok(buildArchivesQuery({ sort: "record_count" }).includes("sort=record_count"));
    assert.ok(buildArchivesQuery({ sort: "compressed_bytes" }).includes("sort=compressed_bytes"));
    assert.ok(buildArchivesQuery({ sort: "verification_status" }).includes("sort=verification_status"));
});

test("buildArchivesQuery rejects unknown sort field", function () {
    var result = buildArchivesQuery({ sort: "unknown_field" });
    assert.ok(!result.includes("sort="));
});

test("buildArchivesQuery serializes order asc and desc", function () {
    assert.ok(buildArchivesQuery({ order: "asc" }).includes("order=asc"));
    assert.ok(buildArchivesQuery({ order: "desc" }).includes("order=desc"));
});

test("buildArchivesQuery rejects unknown order value", function () {
    var result = buildArchivesQuery({ order: "ASC" });
    assert.ok(!result.includes("order="));
});

test("buildArchivesQuery serializes boolean downloadable", function () {
    assert.ok(buildArchivesQuery({ downloadable: true }).includes("downloadable=true"));
    assert.ok(buildArchivesQuery({ downloadable: false }).includes("downloadable=false"));
});

test("buildArchivesQuery rejects non-boolean downloadable", function () {
    var result = buildArchivesQuery({ downloadable: "true" });
    assert.ok(!result.includes("downloadable="));
});

test("buildArchivesQuery serializes stream parameter", function () {
    var result = buildArchivesQuery({ stream: "btcusdt@trade" });
    assert.ok(result.includes("stream=btcusdt%40trade") || result.includes("stream=btcusdt%2540trade"));
});

test("buildArchivesQuery serializes symbol parameter", function () {
    var result = buildArchivesQuery({ symbol: "BTCUSDT" });
    assert.equal(result, "?symbol=BTCUSDT");
});

test("buildArchivesQuery serializes from and to parameters", function () {
    var result = buildArchivesQuery({ from: "2026-07-01T00:00:00Z", to: "2026-07-31T23:59:59Z" });
    assert.ok(result.includes("from=2026-07-01T00"));
    assert.ok(result.includes("to=2026-07-31T23"));
});

test("buildArchivesQuery serializes verification_status", function () {
    var result = buildArchivesQuery({ verification_status: "completed" });
    assert.ok(result.includes("verification_status=completed"));

    result = buildArchivesQuery({ verification_status: "recording" });
    assert.ok(result.includes("verification_status=recording"));

    result = buildArchivesQuery({ verification_status: "failed" });
    assert.ok(result.includes("verification_status=failed"));
});

test("buildArchivesQuery rejects unknown verification_status", function () {
    var result = buildArchivesQuery({ verification_status: "unknown" });
    assert.ok(!result.includes("verification_status="));
});

test("buildArchivesQuery does not include undefined or null values", function () {
    var result = buildArchivesQuery({ page: 1, symbol: undefined, stream: null, sort: "start_time" });
    assert.ok(result.includes("page=1"));
    assert.ok(!result.includes("symbol="));
    assert.ok(!result.includes("stream="));
    assert.ok(result.includes("sort=start_time"));
});

test("buildArchivesQuery does not send unknown parameters", function () {
    var result = buildArchivesQuery({ unknown_key: "value", page: 1 });
    assert.ok(!result.includes("unknown_key"));
    assert.ok(result.includes("page=1"));
});

test("buildArchivesQuery rejects non-string sort values", function () {
    var result = buildArchivesQuery({ sort: 123 });
    assert.ok(!result.includes("sort="));
});

test("buildArchivesQuery rejects empty string parameters", function () {
    var result = buildArchivesQuery({ symbol: "", stream: "" });
    assert.ok(!result.includes("symbol="));
    assert.ok(!result.includes("stream="));
});
