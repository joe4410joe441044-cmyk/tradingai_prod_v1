import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

const loadCard = async () => {
    const sourceUrl = new URL("./AutoMarketSelectionCard.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".ams-card-g6-"));
    const output = join(temporary, "AutoMarketSelectionCard.mjs");
    const modelUrl = pathToFileURL(join(directory,
        "../features/auto-market-selection/autoMarketSelectionModel.js")).href;
    const operationModelUrl = pathToFileURL(join(directory,
        "./operation/operationPreparationModel.js")).href;
    const code = transformed.code
        .replace('from "../features/auto-market-selection/autoMarketSelectionModel.js";', `from "${modelUrl}";`)
        .replace('from "./operation/operationPreparationModel.js";', `from "${operationModelUrl}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=ams-g6`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const status = {
    selectionMode: "AUTO",
    activeSymbol: "XRPUSDTM",
    requestedSymbol: "MEWUSDT",
    topCandidate: { symbol: "DYMUSDT", score: "0.91", spreadScore: "0.8", liquidityScore: "0.7", activityScore: "0.6" },
    autoRuntime: {
        mode: "LIVE_READ_ONLY", runtimeState: "OBSERVING", status: "IDLE",
        cycleId: "ams-cycle-0123456789abcdef0123456789abcdef",
        lastCycleStatus: "COMPLETED_BLOCKED", lastCycleId: "ams-cycle-9",
        evaluatedAt: "2026-09-26 22:44:44",
        reasonCodes: ["MM_STALE", "ELIGIBILITY_STALE", "CAPITAL_INELIGIBLE"],
    },
    scanner: { status: "READY", universeCount: 120, evaluatedCount: 120, eligibleCount: 7, rejectedCount: 113, evaluatedAt: "2026-09-26 22:44:41" },
    ranking: { status: "RANKED_CANDIDATES_AVAILABLE", rankedCount: 7 },
    switch: { state: "IDLE", previousSymbol: "XRPUSDTM", proposedSymbol: "DYMUSDT", committedSymbol: "DYMUSDT", transactionId: "txn-0123456789abcdef", reasonCodes: [] },
    reasons: [],
    capitalEligibility: {
        status: "ELIGIBLE", availableCapital: "7.9184", riskBudget: "0.0396",
        remainingExposure: "0.0000", remainingPositionCapacity: "1",
        mmRegime: "CAPITAL_PROTECTION_STANDARD",
    },
    freshness: { universe: "FRESH", scanner: "FRESH", ranking: "FRESH", mm: "FRESH" },
};

const renderStatic = async (props) => {
    const { default: Card } = await loadCard();
    return renderToStaticMarkup(createElement(Card, props));
};

test("G6 AUTO MARKET SELECTION essential labels are bilingual", async () => {
    const html = await renderStatic({ status, collapsible: true });
    for (const label of [
        "AUTO MARKET SELECTION / 自動市場選定",
        "ACTIVE SYMBOL / 現在銘柄", "TOP CANDIDATE / 最有力候補 · PREVIEW",
        "STATUS / 状態", "LAST EVALUATED / 最終評価",
        "SKIP / RESELECT", "スキップ / 再選定",
        "CAPITAL / 資金", "AVAILABLE CAPITAL / 利用可能資金", "RISK BUDGET / リスク予算",
        "CURRENT REASONS / 現在の理由", "DETAILS / DIAGNOSTICS / 詳細・診断",
        "市場スキャン / ランキング / 選定",
    ]) assert.ok(html.includes(label), `missing ${label}`);
});

test("G6 DETAILS / DIAGNOSTICS groups are bilingual", async () => {
    const html = await renderStatic({ status, collapsible: false });
    for (const label of [
        "SELECTION MODE / 選定モード", "NEXT REQUESTED SYMBOL / 次回要求銘柄",
        "AUTO RUNTIME MODE / 自動実行モード", "RUNTIME STATE / 実行状態",
        "CYCLE STATUS / サイクル状態", "CYCLE ID / サイクルID",
        "LAST CYCLE STATUS / 前回サイクル状態", "LAST CYCLE ID / 前回サイクルID",
        "SCANNER / スキャナー", "UNIVERSE / 対象市場数", "EVALUATED / 評価済み",
        "ELIGIBLE / 適格", "REJECTED / 除外",
        "RANKING / ランキング", "RANKED / ランク対象", "TOP SCORE / 最高スコア",
        "SPREAD SCORE / スプレッド評価", "LIQUIDITY SCORE / 流動性評価", "ACTIVITY SCORE / 活動度評価",
        "CAPITAL DETAILS / 資金詳細", "REMAINING EXPOSURE / 残り許容エクスポージャー",
        "POSITION CAPACITY / 建玉余力", "MM REGIME / MM運用状態",
        "SYMBOL SWITCH / 銘柄切替", "STATE / 状態", "PREVIOUS / 前回", "PROPOSED / 候補",
        "COMMITTED / 確定", "TRANSACTION / トランザクション", "NEW ENTRIES PAUSED / 新規エントリー停止",
        "UNIVERSE / 対象市場: FRESH", "SCANNER / スキャナー: FRESH",
        "LAST CYCLE REASONS / 前回サイクルの理由",
    ]) assert.ok(html.includes(label), `missing ${label}`);
});

test("G6 preserves dynamic values and machine identifiers exactly", async () => {
    const html = await renderStatic({ status, collapsible: false });
    for (const value of [
        "XRPUSDTM", "MEWUSDT", "DYMUSDT", "LIVE_READ_ONLY", "CAPITAL_PROTECTION_STANDARD",
        "MM_STALE · ELIGIBILITY_STALE · CAPITAL_INELIGIBLE", "ams-cycle-0123456789abcdef0123456789abcdef",
        "txn-0123456789abcdef", "ELIGIBLE", "RANKED_CANDIDATES_AVAILABLE",
    ]) assert.ok(html.includes(value), `missing preserved value ${value}`);
});

test("G6 does not regress G5 full-value and disclosure behavior", async () => {
    const collapsed = await renderStatic({ status, collapsible: true });
    assert.match(collapsed, /aria-expanded="false"/);
    assert.doesNotMatch(collapsed, /data-testid="auto-market-selection-details"/);
    assert.ok(collapsed.includes("XRPUSDTM"));
    assert.ok(collapsed.includes("DYMUSDT"));
    assert.match(collapsed, /TOP CANDIDATE \/ 最有力候補 · PREVIEW/);

    const expanded = await renderStatic({ status, collapsible: false });
    assert.match(expanded, /aria-expanded="true"/);
    assert.match(expanded, /data-testid="auto-market-selection-details"/);
    assert.match(expanded, /class="ams-field ams-field--wrap"/);
    for (const critical of ["XRPUSDTM", "DYMUSDT", "MEWUSDT", "LIVE_READ_ONLY", "CAPITAL_PROTECTION_STANDARD"])
        assert.ok(expanded.includes(critical), `critical value ${critical} must render fully`);

    const css = await readFile(new URL("../styles/dashboard.css", import.meta.url), "utf8");
    const wrapBlock = css.match(/\.ams-field--wrap \.ams-field-value\s*\{[^}]*\}/);
    assert.ok(wrapBlock, "critical wrap rule must exist");
    assert.match(wrapBlock[0], /white-space:\s*normal/);
    assert.doesNotMatch(wrapBlock[0], /text-overflow:\s*ellipsis/);
    // bilingual labels are allowed to wrap rather than truncate
    assert.match(css, /\.ams-field-label\s*\{[^}]*white-space:\s*normal/);
});
