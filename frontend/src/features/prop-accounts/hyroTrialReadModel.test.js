import assert from "node:assert/strict";
import test from "node:test";

import {
    HYRO_CORE_25K_RULES,
    ISSUED_HYRO_TRIAL_EVIDENCE,
    accountStatusForChallenge,
    classifyIssuedTrialRead,
    evaluateHyroCore25kReference,
} from "./hyroTrialReadModel.js";

test("issued Trial evidence is read-only, redacted and distinct from Core", () => {
    assert.equal(ISSUED_HYRO_TRIAL_EVIDENCE.status, "ACTIVE");
    assert.equal(ISSUED_HYRO_TRIAL_EVIDENCE.stage, "EVALUATION");
    assert.equal(ISSUED_HYRO_TRIAL_EVIDENCE.readOnly, true);
    assert.equal(ISSUED_HYRO_TRIAL_EVIDENCE.rules.adoptedRuleValueCount, 0);
    assert.equal(ISSUED_HYRO_TRIAL_EVIDENCE.metrics.currentEquity, 25_000);
    assert.equal(ISSUED_HYRO_TRIAL_EVIDENCE.metrics.tradeHistoryComplete, true);
    assert.doesNotMatch(JSON.stringify(ISSUED_HYRO_TRIAL_EVIDENCE), /"publicId"\s*:|Bearer|token/i);
    assert.match(ISSUED_HYRO_TRIAL_EVIDENCE.plan, /Coreとは別口座/);
});

test("Core 25K reference constants match the explicit fixed contract", () => {
    assert.deepEqual({
        target: HYRO_CORE_25K_RULES.profitTarget,
        daily: HYRO_CORE_25K_RULES.dailyLossLimit,
        maximum: HYRO_CORE_25K_RULES.maximumLoss,
        days: HYRO_CORE_25K_RULES.minimumQualifyingTradingDays,
        cap: HYRO_CORE_25K_RULES.dailyProfitContributionCap,
    }, { target: 2500, daily: 750, maximum: 1250, days: 4, cap: 1000 });
});

test("Core reference counts profitable days with cap and losing days in full", () => {
    const result = evaluateHyroCore25kReference({
        currentEquity: 27_700,
        utcDayStartEquity: 27_000,
        intradayMinimumEquity: 26_500,
        qualifyingTradingDays: 4,
        dailyNetResults: [1_600, 900, 700, -100],
        periodStart: "2026-11-01",
        periodEnd: "2026-11-15",
    });
    assert.equal(result.dailyLoss.state, "PASS");
    assert.equal(result.maximumLoss.state, "PASS");
    assert.equal(result.tradingDays.state, "PASS");
    assert.equal(result.profitProgress.countedProfit, 2_500);
    assert.equal(result.profitProgress.state, "PASS");
    assert.equal(result.overall, "PASS");
});

test("Core boundary blocks loss and preserves UNKNOWN for missing evidence", () => {
    const blocked = evaluateHyroCore25kReference({
        currentEquity: 23_749.99,
        utcDayStartEquity: 25_000,
        intradayMinimumEquity: 24_249.99,
        qualifyingTradingDays: 3,
        dailyNetResults: [1000, 1000, 499.99],
    });
    assert.equal(blocked.dailyLoss.state, "BLOCK");
    assert.equal(blocked.maximumLoss.state, "BLOCK");
    assert.equal(blocked.tradingDays.state, "IN_PROGRESS");
    assert.equal(blocked.profitProgress.state, "IN_PROGRESS");
    assert.equal(blocked.overall, "BLOCK");

    const unknown = evaluateHyroCore25kReference({});
    assert.equal(unknown.dailyLoss.state, "UNKNOWN");
    assert.equal(unknown.maximumLoss.state, "UNKNOWN");
    assert.equal(unknown.tradingDays.state, "UNKNOWN");
    assert.equal(unknown.profitProgress.state, "UNKNOWN");
    assert.equal(unknown.overall, "UNKNOWN");
});

test("issued account status never converts absent collection reads to zero", () => {
    const status = accountStatusForChallenge(ISSUED_HYRO_TRIAL_EVIDENCE);
    assert.equal(status.positions, "未確認");
    assert.equal(status.openOrders, "未確認");
    assert.equal(status.conditionalOrders, "未確認");
    assert.equal(status.equity, "25,000 USDT");
    assert.equal(status.currentDrawdown, "0（MCP報告値・単位未確認）");
    assert.equal(status.qualifyingTradingDays, "0日（全決済履歴取得完了）");
});

test("issued Trial Core reference uses only confirmed metrics and keeps daily loss unknown", () => {
    const result = evaluateHyroCore25kReference(ISSUED_HYRO_TRIAL_EVIDENCE.metrics);
    assert.equal(result.dailyLoss.state, "UNKNOWN");
    assert.equal(result.maximumLoss.state, "PASS");
    assert.equal(result.maximumLoss.used, 0);
    assert.equal(result.tradingDays.state, "IN_PROGRESS");
    assert.equal(result.tradingDays.actual, 0);
    assert.equal(result.profitProgress.state, "IN_PROGRESS");
    assert.equal(result.profitProgress.countedProfit, 0);
    assert.equal(result.overall, "UNKNOWN");
});

test("issued read classifier separates mismatch, ended, partial and stale", () => {
    const now = Date.parse("2026-11-15T10:00:00Z");
    const base = { scopeMatch: true, status: "ACTIVE", stage: "EVALUATION", observedAt: "2026-11-15T09:55:00Z", metricsComplete: false };
    assert.equal(classifyIssuedTrialRead(base, { now }).state, "PARTIAL");
    assert.deepEqual(classifyIssuedTrialRead({ ...base, scopeMatch: false }, { now }), { state: "FAILED", reason: "CHALLENGE_ID_MISMATCH" });
    assert.equal(classifyIssuedTrialRead({ ...base, status: "EXPIRED" }, { now }).state, "ENDED");
    assert.equal(classifyIssuedTrialRead({ ...base, observedAt: "2026-11-15T09:00:00Z" }, { now }).state, "STALE");
    assert.equal(classifyIssuedTrialRead({ ...base, metricsComplete: true }, { now }).state, "READY");
});
