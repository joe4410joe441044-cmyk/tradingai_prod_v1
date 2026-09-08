import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./HelpDisclosure.jsx", import.meta.url), "utf8");

test("disclosure starts collapsed and uses an accessible toggle button", () => {
    assert.match(source, /useState\('?\s*defaultOpen\s*'?/);
    assert.match(source, /aria-expanded=\{isExpanded\}/);
    assert.match(source, /aria-controls=\{contentId\}/);
    assert.match(source, /type="button"/);
});

test("disclosure supports both uncontrolled and controlled open state", () => {
    assert.match(source, /typeof controlledOpen === "boolean"/);
    assert.match(source, /typeof onToggle === "function"/);
    assert.match(source, /defaultOpen/);
});

test("content renders only after the disclosure expands", () => {
    assert.ok(source.indexOf("{isExpanded &&") < source.indexOf("{children}"));
});

test("disclosure uses a +/− expansion indicator", () => {
    assert.match(source, /isExpanded \? "−" : "\+"/);
});

test("disclosure has no network or persistence integration", () => {
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage/);
});
