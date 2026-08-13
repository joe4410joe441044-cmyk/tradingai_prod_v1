import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorOverview.jsx", import.meta.url), "utf8");

test("overview separates Supervisor Core, AI Interpretation, and Operational Effect layers", function () {
    assert.match(source, /<dt>Supervisor Core<\/dt>/);
    assert.match(source, /<dt>AI Interpretation<\/dt>/);
    assert.match(source, /<dt>Operational Effect<\/dt>/);
});

test("overview derives state from the supervisor provider status client", function () {
    assert.match(source, /import[\s\S]*getSupervisorProviderStatus[\s\S]*supervisorClient/);
    assert.match(source, /supervisorCoreSeverity\(core\)/);
    assert.match(source, /llmInterpretationSeverity\(llm\)/);
    assert.match(source, /deriveProviderConnection\(status\)/);
});

test("Provider DISABLED is rendered as a distinct provider line, never as a Core failure", function () {
    assert.match(source, /Provider: \{provider\} · Connection: \{connection\}/);
    assert.doesNotMatch(source, /Supervisor (UNAVAILABLE|DOWN|FAILURE)/);
    assert.doesNotMatch(source, /<dd>ERROR<\/dd>/);
});

test("operational effect NONE is treated as a neutral, non-alarming state", function () {
    assert.match(source, /operationalEffect === "NONE" \? "neutral" : "error"/);
});

test("overview has local loading and error states without a whole-page failure", function () {
    assert.match(source, /Status Loading…/);
    assert.match(source, /role="alert"/);
});

test("overview no longer claims the Supervisor is in a disconnected preparation stage", function () {
    assert.doesNotMatch(source, /準備段階|接続されていません|Posture|Human action/);
});

test("overview adds no operational or provider-setup controls", function () {
    assert.doesNotMatch(source, /Start Bot|Start Loop|Auto Trade|Execute Order|Cancel Order|Flatten|Enable Provider|API Key|Load Model|Start Ollama/);
});
