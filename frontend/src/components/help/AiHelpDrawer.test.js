import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./AiHelpDrawer.jsx", import.meta.url), "utf8");

test("drawer is closed by default and only renders when opened", () => {
    assert.match(source, /if \(!open\) return null;/);
});

test("drawer uses a modal dialog role with an accessible label", () => {
    assert.match(source, /role="dialog"/);
    assert.match(source, /aria-modal="true"/);
    assert.match(source, /aria-labelledby=\{`\$\{id\}-title`\}/);
    assert.match(source, /tabIndex=\{-1\}/);
});

test("drawer closes on Escape via a keydown listener", () => {
    assert.match(source, /addEventListener\("keydown"/);
    assert.match(source, /event\.key === "Escape"/);
    assert.match(source, /onClose\(\)/);
});

test("drawer restores focus to the previously focused element", () => {
    assert.match(source, /document\.activeElement/);
    assert.match(source, /panelRef\.current\?\.focus\(\)/);
    assert.match(source, /previouslyFocused\?\.focus\?\.\(\)/);
});

test("drawer exposes an explicit close control", () => {
    assert.match(source, /ai-help-drawer__close/);
    assert.match(source, /aria-label="ヘルプを閉じる"/);
    assert.match(source, /onClick=\{onClose\}/);
});

test("backdrop click closes while clicks inside the drawer do not propagate", () => {
    assert.match(source, /onMouseDown=\{onClose\}/);
    assert.match(source, /onMouseDown=\{\(event\) => event\.stopPropagation\(\)\}/);
});

test("drawer follows the requested left/right edge", () => {
    assert.match(source, /ai-help-overlay--\$\{side\}/);
    assert.match(source, /ai-help-drawer--\$\{side\}/);
});

test("drawer has no network, persistence, or mutation integration", () => {
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage/);
});
