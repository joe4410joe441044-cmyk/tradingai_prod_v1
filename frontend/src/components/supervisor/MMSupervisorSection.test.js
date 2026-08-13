import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./MMSupervisorSection.jsx", import.meta.url), "utf8");

test("MM Supervisor starts collapsed after Master and identifies unknown state", function () {
    assert.match(source, /MM SUPERVISOR/);
    assert.match(source, /State: <strong>UNKNOWN<\/strong>/);
    assert.match(source, /useState\(false\)/);
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
