import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
    new URL("./AccountRuntimeOverview.jsx", import.meta.url),
    "utf8",
);
const apiSource = await readFile(new URL("../../api/index.js", import.meta.url), "utf8");

test("Paper card exposes an explicit confirmed capital reset workflow", () => {
    assert.match(source, /Set Paper Capital/);
    assert.match(source, /Simulation Capital \(USDT\)/);
    assert.match(source, /Apply Paper Capital/);
    assert.match(source, /Reset Paper Account\?/);
    assert.match(source, /Real funds are not affected/);
    assert.match(source, /aria-live="polite"/);
});

test("presets only populate input and real available uses an explicit source", () => {
    assert.match(source, /\["100", "1000", "10000"\]/);
    assert.match(source, /REAL_AVAILABLE_PRESET/);
    assert.match(source, /disabled=\{!realAvailablePresetEnabled\}/);
    assert.match(source, /REAL_ACCOUNT_NOT_SYNCED/);
    assert.equal((source.match(/fetch\(API\.paperAccountCapital\(\)/g) || []).length, 1);
});

test("paper reset uses the same-origin backend API and refreshes authority", () => {
    assert.match(apiSource, /paperAccountCapital:[\s\S]*join\("\/bot\/paper-account\/capital"\)/);
    assert.match(source, /if \(onPaperCapitalApplied\) await onPaperCapitalApplied\(\)/);
    assert.doesNotMatch(source, /localStorage|sessionStorage|window\.confirm/);
});
