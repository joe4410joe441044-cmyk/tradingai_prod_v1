import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const statusStripSource = await readFile(
    new URL("./StatusStrip.jsx", import.meta.url),
    "utf8",
);

test("TOP runtime status bar keeps the five runtime-critical items", () => {
    assert.match(statusStripSource, /BOT \/ ボット/);
    assert.match(statusStripSource, /BROWSER WS \/ 画面接続/);
    assert.match(statusStripSource, /RUNTIME ENGINE/);
    assert.match(statusStripSource, /LATENCY \/ 遅延/);
    assert.match(statusStripSource, /MODE/);
});

test("TOP runtime status bar removes the low-value presentation items", () => {
    assert.doesNotMatch(statusStripSource, /EXEC \/ 実行/);
    assert.doesNotMatch(statusStripSource, /PIPELINE/);
    assert.doesNotMatch(statusStripSource, /STAGES/);
    assert.doesNotMatch(statusStripSource, /SESSION/);
    assert.doesNotMatch(statusStripSource, /VERSION/);
});
