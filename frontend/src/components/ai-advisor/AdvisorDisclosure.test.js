import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
    new URL("./AdvisorDisclosure.jsx", import.meta.url),
    "utf8",
);

test("disclosure starts collapsed and uses an accessible toggle button", () => {
    assert.match(source, /useState\(false\)/);
    assert.match(source, /aria-expanded=\{isExpanded\}/);
    assert.match(source, /aria-controls=\{contentId\}/);
    assert.match(
        source,
        /onClick=\{\(\) => setIsExpanded\(\(expanded\) => !expanded\)\}/,
    );
});

test("content is rendered only after the disclosure expands", () => {
    assert.ok(source.indexOf("{isExpanded &&") < source.indexOf("{children}"));
});

test("disclosure has no network or persistence integration", () => {
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage/);
});

test("toggle uses bilingual Expand/Collapse labels with +/− indicator", () => {
    assert.match(source, /Expand（開く）/);
    assert.match(source, /Collapse（閉じる）/);
    assert.match(source, /isExpanded \? "−" : "\+"/);
});
