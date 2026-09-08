import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./AiHelpLauncher.jsx", import.meta.url), "utf8");

test("launcher renders a compact button with an aria-expanded state", () => {
    assert.match(source, /<button/);
    assert.match(source, /type="button"/);
    assert.match(source, /aria-expanded=\{expanded\}/);
    assert.match(source, /aria-controls=\{controls\}/);
    assert.match(source, /onClick=\{onToggle\}/);
});

test("launcher exposes a leading '?' mark and the passed label", () => {
    assert.match(source, /ai-help-launcher__mark/);
    assert.match(source, /aria-hidden="true"/);
    assert.match(source, /label/);
});

test("launcher carries the side used to open the matching drawer", () => {
    assert.match(source, /ai-help-launcher--\$\{side\}/);
});

test("launcher has no network, persistence, or mutation integration", () => {
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage|botStart|botStop|order|cancel/);
});
