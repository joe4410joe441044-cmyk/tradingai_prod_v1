import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./MMSupervisorSection.jsx", import.meta.url), "utf8");

test("MM Supervisor renders an authoritative state instead of hardcoding UNKNOWN", function () {
    assert.match(source, /MM SUPERVISOR/);
    assert.doesNotMatch(source, /State:\s*<strong>UNKNOWN<\/strong>/);
    assert.match(source, /State: <strong>\{state\}<\/strong>/);
});

test("MM Supervisor derives state from the authoritative snapshot ruin guard status", function () {
    assert.match(source, /getSupervisorSnapshot/);
    assert.match(source, /moneyManagement\?\.ruinGuardStatus/);
    assert.match(source, /KNOWN_MM_STATES/);
});

test("MM Supervisor falls back to UNKNOWN when authority is missing or unrecognized", function () {
    assert.match(source, /useState\("UNKNOWN"\)/);
    assert.match(source, /return "UNKNOWN";/);
    assert.match(source, /setState\("UNKNOWN"\)/);
});

test("MM disclosure is keyboard-operable and exposes expansion semantics", function () {
    assert.match(source, /<button[\s\S]*type="button"[\s\S]*aria-expanded={isExpanded}/);
    assert.match(source, /aria-controls={contentId}/);
    assert.ok(source.includes("onClick={() => setIsExpanded((expanded) => !expanded)}"));
    assert.match(source, /hidden={!isExpanded}/);
});

test("MM conversation stays mounted with isolated history while disclosure is collapsed", function () {
    assert.match(source, /hidden={!isExpanded}/);
    assert.match(source, /supervisorName="MM Supervisor"/);
    assert.match(source, /agentId="MM_SUPERVISOR"/);
});
