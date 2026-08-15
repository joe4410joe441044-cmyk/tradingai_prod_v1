import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorOverview.jsx", import.meta.url), "utf8");

test("overview renders a compact status bar with Core, AI, Provider, Connection, Effect, and Mode", function () {
    assert.match(source, /label="Core"/);
    assert.match(source, /label="AI"/);
    assert.match(source, /label="Provider"/);
    assert.match(source, /label="Connection"/);
    assert.match(source, /label="Effect"/);
    assert.match(source, /label="Mode"/);
});

test("overview derives state from the supervisor provider status client", function () {
    assert.match(source, /getSupervisorProviderStatus/);
    assert.match(source, /supervisorCoreSeverity\(core\)/);
    assert.match(source, /llmInterpretationSeverity\(llm\)/);
    assert.match(source, /deriveProviderConnection\(status\)/);
});

test("Provider state is rendered as a distinct chip, never as a Core failure", function () {
    assert.match(source, /label="Provider"/);
    assert.doesNotMatch(source, /Supervisor (UNAVAILABLE|DOWN|FAILURE)/);
    assert.doesNotMatch(source, /<dd>ERROR<\/dd>/);
});

test("operational effect NONE is treated as a neutral, non-alarming state", function () {
    assert.match(source, /effect === "NONE" \? "neutral" : "error"/);
});

test("overview keeps a local error state without a whole-page failure", function () {
    assert.match(source, /role="alert"/);
});

test("overview adds no operational or provider-setup controls", function () {
    assert.doesNotMatch(source, /Start Bot|Start Loop|Auto Trade|Execute Order|Cancel Order|Flatten|Enable Provider|API Key|Load Model|Start Ollama/);
});
