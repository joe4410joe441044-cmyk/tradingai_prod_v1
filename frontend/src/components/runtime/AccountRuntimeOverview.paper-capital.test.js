import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const overviewSource = await readFile(
    new URL("./AccountRuntimeOverview.jsx", import.meta.url),
    "utf8",
);
const controlSource = await readFile(
    new URL("./PaperCapitalControl.jsx", import.meta.url),
    "utf8",
);
const apiSource = await readFile(new URL("../../api/index.js", import.meta.url), "utf8");

test("Paper card exposes an explicit confirmed capital reset workflow", () => {
    assert.match(controlSource, /SET PAPER CAPITAL（ペーパー資金設定）/);
    assert.match(controlSource, /SIMULATION CAPITAL（シミュレーション資金） \(USDT\)/);
    assert.match(controlSource, /APPLY PAPER CAPITAL（ペーパー資金を適用）/);
    assert.match(controlSource, /REAL AVAILABLE（実口座利用可能額）/);
    assert.match(controlSource, /Reset Paper Account\?（ペーパー口座をリセットしますか？）/);
    assert.match(controlSource, /Real funds are not affected/);
    assert.match(controlSource, /aria-live="polite"/);
});

test("presets only populate input and real available uses an explicit source", () => {
    assert.match(controlSource, /\["100", "1000", "10000"\]/);
    assert.match(controlSource, /REAL_AVAILABLE_PRESET/);
    assert.match(controlSource, /disabled=\{!realAvailablePresetEnabled\}/);
    assert.match(controlSource, /REAL_ACCOUNT_NOT_SYNCED/);
    assert.equal((controlSource.match(/fetch\(API\.paperAccountCapital\(\)/g) || []).length, 0);
    assert.equal((controlSource.match(/authenticatedControlRequest\(API\.paperAccountCapital\(\)/g) || []).length, 1);
});

test("paper reset uses the same-origin backend API and refreshes authority", () => {
    assert.match(apiSource, /paperAccountCapital:[\s\S]*join\("\/bot\/paper-account\/capital"\)/);
    assert.match(controlSource, /if \(onPaperCapitalApplied\) await onPaperCapitalApplied\(\)/);
    assert.doesNotMatch(controlSource, /localStorage|sessionStorage|window\.confirm/);
});

test("Account Runtime Overview reuses the single shared Paper Capital control", () => {
    assert.match(overviewSource, /import PaperCapitalControl from "\.\/PaperCapitalControl";/);
    assert.match(overviewSource, /<PaperCapitalControl/);
});
