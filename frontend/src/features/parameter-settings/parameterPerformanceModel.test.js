import assert from "node:assert/strict";
import test from "node:test";

import {
    PERFORMANCE_METRIC_DEFINITIONS,
    PERFORMANCE_SEMANTICS_NOTE,
    buildExitReasonRows,
    buildMetricsView,
    buildParameterDiffRows,
    buildPerformanceViewModel,
    buildRevisionHistoryRows,
    buildRevisionOptions,
    buildTradeRows,
    displayPerformanceValue,
    formatHoldingDuration,
    formatPnl,
    formatTradeTimestamp,
    formatWinRate,
} from "./parameterPerformanceModel.js";

const SCHEMA = {
    parameters: [
        { name: "minimumCompositeScore", labelEn: "Composite Entry Score", labelJa: "総合エントリースコア", unit: "normalized score (0.0-1.0)" },
        { name: "maximumStrategySpreadPct", labelEn: "Maximum Strategy Spread", labelJa: "最大スプレッド", unit: "percent (0-100 scale)" },
        { name: "absorptionVolumePercentile", labelEn: "Absorption Volume Percentile", labelJa: "吸収出来高パーセンタイル", unit: "normalized percentile (0.0-1.0)" },
    ],
};

const METRICS = {
    tradeCount: 3,
    winCount: 2,
    lossCount: 1,
    breakevenCount: 0,
    winRate: 2 / 3,
    realizedPnl: 12.0,
    averagePnl: 4.0,
    medianPnl: 5.0,
    averageHoldingMs: 2000,
    realizedPnlAuthoritative: true,
    exitReasons: [
        { reason: "TP", count: 2 },
        { reason: "SL", count: 1 },
    ],
};

const PERFORMANCE = {
    available: true,
    scope: "PAPER",
    revisionCount: 2,
    recordCount: 2,
    revisions: [
        {
            scope: "PAPER",
            effectiveRevision: 2,
            parameterSetId: "strategy-params/PAPER",
            featureContract: "TIME_SYMBOL_NORMALIZED_V1",
            capturedAt: "2026-09-18T00:00:00Z",
            parameterValues: {
                minimumCompositeScore: 0.42,
                maximumStrategySpreadPct: 0.5,
                absorptionVolumePercentile: 0.9,
            },
            valueSource: "REVISION_ARCHIVE",
            observedTradeCount: 2,
            metrics: METRICS,
        },
        {
            scope: "PAPER",
            effectiveRevision: 3,
            parameterSetId: "strategy-params/PAPER",
            featureContract: "TIME_SYMBOL_NORMALIZED_V1",
            capturedAt: "2026-09-18T01:00:00Z",
            parameterValues: { minimumCompositeScore: 0.55 },
            valueSource: "REVISION_ARCHIVE",
            observedTradeCount: 0,
            metrics: { ...METRICS, tradeCount: 0, winCount: 0, lossCount: 0 },
        },
    ],
    records: [
        { recordId: "r1", tradeId: "t1", positionId: "p1", scope: "PAPER", effectiveRevision: 2, symbol: "MOVEUSDT", side: "BUY", mode: "paper", entryPrice: 0.1, exitPrice: 0.11, holdingMs: 1000, realizedPnl: 5.0, realizedPnlAuthoritative: true, exitReason: "TP" },
        { recordId: "r2", tradeId: "t2", positionId: "p2", scope: "PAPER", effectiveRevision: 2, symbol: "MOVEUSDT", side: "SELL", mode: "paper", entryPrice: 0.2, exitPrice: 0.19, holdingMs: 3000, realizedPnl: -1.0, realizedPnlAuthoritative: true, exitReason: "SL" },
    ],
    metrics: METRICS,
    semantics: {
        entrySnapshotParameters: ["minimumHoldMs"],
        dynamicAuthorityParameters: ["minimumCompositeScore"],
        note: "note",
    },
};

const COMPARISON = {
    available: true,
    scope: "PAPER",
    revisionA: { effectiveRevision: 2 },
    revisionB: { effectiveRevision: 3 },
    parameterDiff: [
        { name: "minimumCompositeScore", labelEn: "Composite Entry Score", labelJa: "総合エントリースコア", unit: "normalized score (0.0-1.0)", a: 0.42, b: 0.55, delta: 0.13, changed: true },
        { name: "maximumStrategySpreadPct", labelEn: "Maximum Strategy Spread", labelJa: "最大スプレッド", unit: "percent (0-100 scale)", a: 0.5, b: 0.5, delta: 0, changed: false },
    ],
    changedCount: 1,
};


test("format helpers are deterministic and null-safe", () => {
    assert.equal(formatPnl(12.345), "12.35");
    assert.equal(formatPnl(null), "—");
    assert.equal(formatWinRate(0.5), "50.0 %");
    assert.equal(formatWinRate(null), "—");
    assert.equal(formatHoldingDuration(500), "500 ms");
    assert.equal(formatHoldingDuration(2500), "2.5 s");
    assert.equal(formatHoldingDuration(120000), "2.0 min");
    assert.equal(formatHoldingDuration(null), "—");
});


test("metrics view marks unavailable values explicitly", () => {
    const rows = buildMetricsView({
        tradeCount: 0,
        winCount: 0,
        winRate: null,
        realizedPnl: null,
    });
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
    assert.equal(byKey.tradeCount.value, "0");
    assert.equal(byKey.tradeCount.available, true);
    assert.equal(byKey.winRate.value, "—");
    assert.equal(byKey.winRate.available, false);
    assert.equal(byKey.realizedPnl.value, "—");
    assert.equal(rows.length, PERFORMANCE_METRIC_DEFINITIONS.length);
});


test("exit reason rows are derived from backend metrics", () => {
    assert.deepEqual(buildExitReasonRows(METRICS), [
        { reason: "TP", count: 2, testId: "performance-exit-TP" },
        { reason: "SL", count: 1, testId: "performance-exit-SL" },
    ]);
    assert.deepEqual(buildExitReasonRows({}), []);
});


test("revision history rows expose values and observed trade counts", () => {
    const rows = buildRevisionHistoryRows(PERFORMANCE, SCHEMA);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].effectiveRevision, 2);
    assert.equal(rows[0].observedTradeCount, 2);
    assert.equal(rows[0].valuesAvailable, true);
    const composite = rows[0].valueRows.find(
        (row) => row.name === "minimumCompositeScore"
    );
    assert.equal(composite.display, "0.42");
    assert.equal(rows[1].observedTradeCount, 0);
});


test("revision history marks unavailable values truthfully", () => {
    const rows = buildRevisionHistoryRows({
        revisions: [{
            scope: "PAPER",
            effectiveRevision: 6,
            parameterValues: null,
            valueSource: "UNAVAILABLE",
            observedTradeCount: 1,
        }],
    }, SCHEMA);
    assert.equal(rows[0].valuesAvailable, false);
    assert.deepEqual(rows[0].valueRows, []);
});


test("revision options use the canonical (scope, revision) label", () => {
    const options = buildRevisionOptions(PERFORMANCE);
    assert.deepEqual(options.map((option) => option.value), [2, 3]);
    assert.equal(options[0].label, "PAPER R2");
});


test("LIVE legacy raw spread is never shown with a percent suffix", () => {
    const display = displayPerformanceValue(
        "maximumStrategySpreadPct",
        0.0005,
        "LIVE",
        { unit: "percent (0-100 scale)" },
    );
    assert.equal(display, "0.0005");
    assert.doesNotMatch(display, /%/);
});


test("percentile values stay decimal without a percent suffix", () => {
    const display = displayPerformanceValue(
        "absorptionVolumePercentile",
        0.9,
        "PAPER",
        { unit: "normalized percentile (0.0-1.0)" },
    );
    assert.equal(display, "0.90");
    assert.doesNotMatch(display, /%/);
});


test("parameter diff identifies changed values and shows a factual delta", () => {
    const rows = buildParameterDiffRows(COMPARISON, SCHEMA);
    const composite = rows.find((row) => row.name === "minimumCompositeScore");
    assert.equal(composite.changed, true);
    assert.equal(composite.aDisplay, "0.42");
    assert.equal(composite.bDisplay, "0.55");
    assert.equal(composite.deltaDisplay, "+0.13");
    const spread = rows.find((row) => row.name === "maximumStrategySpreadPct");
    assert.equal(spread.changed, false);
});


test("diff rows never contain winner/best/optimal wording", () => {
    const rows = buildParameterDiffRows(COMPARISON, SCHEMA);
    const text = JSON.stringify(rows);
    assert.doesNotMatch(text, /best|winner|optimal|recommend/i);
});


test("trade rows are factual and null-safe", () => {
    const rows = buildTradeRows(PERFORMANCE.records);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].pnlDisplay, "5.00");
    assert.equal(rows[1].pnlDisplay, "-1.00");
    assert.equal(rows[0].holdingDisplay, "1.0 s");
    assert.equal(rows[0].exitReason, "TP");
});


test("trade timestamps are formatted truthfully and null-safely", () => {
    assert.equal(formatTradeTimestamp(null), "—");
    assert.equal(formatTradeTimestamp(undefined), "—");
    assert.equal(formatTradeTimestamp("not-a-number"), "—");
    const formatted = formatTradeTimestamp(1789784124.9367893);
    assert.match(formatted, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
});


test("trade rows expose entry and exit times", () => {
    const rows = buildTradeRows([{
        recordId: "t",
        entryTimestamp: 1789784124.9367893,
        exitTimestamp: 1789784125.7253401,
    }]);
    assert.match(rows[0].entryTimeDisplay, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    assert.match(rows[0].exitTimeDisplay, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    assert.equal(buildTradeRows([{}])[0].entryTimeDisplay, "—");
});


test("view model exposes the selected revision and all-revision state", () => {
    const scoped = buildPerformanceViewModel({
        performance: { ...PERFORMANCE, revision: 2 },
    });
    assert.equal(scoped.selectedRevision, 2);
    assert.equal(scoped.allRevisions, false);
    const all = buildPerformanceViewModel({
        performance: { ...PERFORMANCE, revision: null },
    });
    assert.equal(all.selectedRevision, null);
    assert.equal(all.allRevisions, true);
});


test("view model exposes an explicit empty state", () => {
    const view = buildPerformanceViewModel({
        performance: null,
        comparison: null,
        schema: SCHEMA,
    });
    assert.equal(view.available, false);
    assert.equal(view.hasRevisions, false);
    assert.equal(view.hasTrades, false);
    assert.deepEqual(view.revisions, []);
    assert.equal(view.comparison, null);
    assert.equal(view.metrics.length, PERFORMANCE_METRIC_DEFINITIONS.length);
});


test("view model exposes comparison data and semantics note", () => {
    const view = buildPerformanceViewModel({
        performance: PERFORMANCE,
        comparison: COMPARISON,
        schema: SCHEMA,
    });
    assert.equal(view.hasRevisions, true);
    assert.equal(view.hasTrades, true);
    assert.equal(view.comparison.changedCount, 1);
    assert.equal(view.comparison.rows.length, 2);
    assert.equal(view.semantics.entrySnapshotParameters.length, 1);
    assert.match(PERFORMANCE_SEMANTICS_NOTE.en, /Observed under this parameter set/);
    assert.match(PERFORMANCE_SEMANTICS_NOTE.ja, /このパラメーター構成下で観測/);
});
