import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./AdvisorGuide.jsx", import.meta.url), "utf8");

test("Advisor role is a read-only research/analysis partner", () => {
    assert.match(source, /読み取り専用の研究・分析パートナー/);
});

test("Advisor trust boundary distinguishes facts/inferences/unknowns", () => {
    assert.match(source, /事実（facts）/);
    assert.match(source, /推論（inferences）/);
    assert.match(source, /不明（unknowns）/);
});

test("Advisor exposes UNKNOWN / STALE help", () => {
    assert.match(source, /UNKNOWN \/ STALEとは/);
    assert.match(source, /STALE（古い）/);
});

test("Advisor provides example questions through disclosure", () => {
    assert.match(source, /HelpDisclosure title="質問例"/);
});

test("Advisor lists what it cannot do (no execution)", () => {
    assert.match(source, /できないこと（実行境界）/);
    assert.match(source, /注文/);
    assert.match(source, /Bot開始\/停止/);
    assert.match(source, /利益保証/);
    assert.match(source, /実行/);
});

test("Advisor avoids implying exhaustive or executable capability", () => {
    assert.match(source, /実行や変更は一切しません/);
    assert.doesNotMatch(source, /利益を保証します/);
    assert.doesNotMatch(source, /未来の市場を予測できます/);
});

test("Advisor has no network, persistence, or mutation integration", () => {
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage|botStart|botStop/);
});
