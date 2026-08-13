import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorSnapshotPanel.jsx", import.meta.url), "utf8");

test("snapshot panel fetches the read-only snapshot contract", function () {
    assert.match(source, /getSupervisorSnapshot/);
    assert.match(source, /READ-ONLY OBSERVATION/);
    assert.match(source, /Snapshot/);
});

test("snapshot exposes capturedAt, freshness, and domain states", function () {
    assert.match(source, /Captured/);
    assert.match(source, /overallFreshness/);
    assert.match(source, /capitalSource/);
    assert.match(source, /pendingOrderState|Execution/);
});

test("snapshot renders warnings as diagnostics without fabricating a live verdict", function () {
    assert.match(source, /Diagnostics/);
    assert.match(source, /No warnings/);
    assert.match(source, /warnings\.map/);
    assert.doesNotMatch(source, /LIVE VERIFIED|REAL VERIFIED|LIVE_VALID/);
});

test("snapshot failure is localized and never claims the Supervisor Core failed (Test E)", function () {
    assert.match(source, /role="alert"/);
    assert.match(source, /Snapshot unavailable/);
    assert.doesNotMatch(source, /Supervisor (DOWN|FAILURE|UNAVAILABLE)/);
});

test("snapshot panel adds no mutation or execution controls", function () {
    assert.doesNotMatch(source, /Start Bot|Start Loop|Execute|Apply|Change Risk|Change Quantity|Cancel Order|POST|PUT|DELETE/);
});

test("null and unknown values render as explicit UNKNOWN, not empty", function () {
    assert.match(source, /"UNKNOWN"/);
});
