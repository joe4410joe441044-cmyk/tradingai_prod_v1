import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorGuide.jsx", import.meta.url), "utf8");

test("Supervisor guide has three internally collapsible sections", () => {
    assert.match(source, /Master Supervisor（マスター・スーパーバイザー）/);
    assert.match(source, /MM Supervisor（MMスーパーバイザー）/);
    assert.match(source, /UNKNOWN \/ STALE \/ 権威（Authority）/);
    assert.match(source, /HelpDisclosure/);
});

test("Supervisor guide is SHADOW and explains the read-only mode", () => {
    assert.match(source, /SHADOW/);
    assert.match(source, /実行・変更・注文は一切しません/);
    assert.match(source, /観察・説明のみ/);
});

test("Master section cannot execute or change anything", () => {
    assert.match(source, /注文・ポジション変更/);
    assert.match(source, /数量計算/);
    assert.match(source, /Governance変更/);
    assert.match(source, /憲章書き換えはしません/);
});

test("MM section cannot calculate executable lots or mutate MM", () => {
    assert.match(source, /実際の「何ロット」の算出はしません/);
    assert.match(source, /リスク%・レバ・エクスポージャー/);
    assert.match(source, /MM計算の再実装・値の捏造/);
});

test("drawdown semantics: 0.08 = 0.08% not 8%", () => {
    assert.match(source, /0.08=0.08%/);
    assert.match(source, /8%ではない/);
    assert.match(source, /100倍しない/);
});

test("exposure distinctions are explained", () => {
    assert.match(source, /現在\/残り\/上限エクスポージャーは別物/);
    assert.match(source, /エクスポージャー：現在/);
    assert.match(source, /は別物/);
});

test("capital facts do not equal overall MM state", () => {
    assert.match(source, /全体のMM評価がUNKNOWNなら「MMはNORMAL」とは言えません/);
    assert.match(source, /「資本が健全」＝「全体がNORMAL」ではありません/);
});

test("UNKNOWN is not broken; STALE is not current evidence", () => {
    assert.match(source, /「壊れている」という意味ではありません/);
    assert.match(source, /現在の健康な証拠/);
});

test("Supervisor guide focuses a requested section", () => {
    assert.match(source, /focusSection/);
    assert.match(source, /focusSection === "master"/);
    assert.match(source, /focusSection === "mm"/);
});

test("Supervisor guide has no network, persistence, or mutation integration", () => {
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage|botStart|botStop/);
});
