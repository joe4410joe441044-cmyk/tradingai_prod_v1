/* =================================================
   PARAMETER PERFORMANCE view model (pure, testable).

   Maps the read-only E-PERF-3 backend payload into deterministic presentation
   rows.  It contains no React and no network.

   Truthfulness rules:
   - metrics are only shown when the backend actually supplied them;
   - missing history is rendered as an explicit unavailable state, never as a
     fabricated zero;
   - parameter values are shown as observations, never as a recommendation,
     score or "best" revision.
================================================= */

import { LEGACY_RAW_PARAMETERS } from "./parameterGuide.js";
import {
    findSchemaParameter,
    formatParameterValue,
    isLiveScope,
} from "./parameterSettingsModel.js";

const LEGACY_RAW_SET = new Set(LEGACY_RAW_PARAMETERS);

export const PERFORMANCE_METRIC_DEFINITIONS = Object.freeze([
    { key: "tradeCount", labelEn: "Trade count", labelJa: "取引数", format: "count" },
    { key: "winCount", labelEn: "Win count", labelJa: "勝ち数", format: "count" },
    { key: "lossCount", labelEn: "Loss count", labelJa: "負け数", format: "count" },
    { key: "breakevenCount", labelEn: "Breakeven count", labelJa: "損益ゼロ数", format: "count" },
    { key: "winRate", labelEn: "Win rate", labelJa: "勝率", format: "rate" },
    { key: "realizedPnl", labelEn: "Realized PnL", labelJa: "実現損益", format: "pnl" },
    { key: "averagePnl", labelEn: "Average PnL", labelJa: "平均損益", format: "pnl" },
    { key: "medianPnl", labelEn: "Median PnL", labelJa: "損益中央値", format: "pnl" },
    { key: "averageHoldingMs", labelEn: "Average holding time", labelJa: "平均保有時間", format: "duration" },
]);

export const PERFORMANCE_SEMANTICS_NOTE = Object.freeze({
    en: "Observed under this parameter set. Values are the authority resolved at entry; dynamic parameters were not frozen for the whole trade.",
    ja: "このパラメーター構成下で観測。値はエントリー時に解決された権限です。動的パラメーターは取引中ずっと固定されていたわけではありません。",
});

const isNumber = (value) => (
    typeof value === "number" && Number.isFinite(value)
);

export const formatCount = (value) => (
    isNumber(value) ? String(Math.trunc(value)) : "—"
);

export const formatPnl = (value) => (
    isNumber(value) ? value.toFixed(2) : "—"
);

export const formatWinRate = (value) => (
    isNumber(value) ? `${(value * 100).toFixed(1)} %` : "—"
);

export const formatHoldingDuration = (value) => {
    if (!isNumber(value)) return "—";
    if (value < 1000) return `${Math.round(value)} ms`;
    if (value < 60000) return `${(value / 1000).toFixed(1)} s`;
    return `${(value / 60000).toFixed(1)} min`;
};

/* Canonical completed-trade timestamps are stored as Unix epoch seconds.
   They are rendered in local time with a stable, readable pattern; the raw
   canonical value is never mutated. */
export const formatTradeTimestamp = (value) => {
    if (value === null || value === undefined || value === "") return "—";
    const seconds = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(seconds)) return "—";
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.getTime())) return "—";
    const pad = (part) => String(part).padStart(2, "0");
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
        + ` ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    );
};

const formatMetricValue = (format, value) => {
    if (format === "count") return formatCount(value);
    if (format === "rate") return formatWinRate(value);
    if (format === "pnl") return formatPnl(value);
    if (format === "duration") return formatHoldingDuration(value);
    return value === null || value === undefined ? "—" : String(value);
};

export const buildMetricsView = (metrics = {}) => (
    PERFORMANCE_METRIC_DEFINITIONS.map((definition) => {
        const value = metrics?.[definition.key];
        return {
            key: definition.key,
            labelEn: definition.labelEn,
            labelJa: definition.labelJa,
            testId: `performance-metric-${definition.key}`,
            available: value !== null && value !== undefined,
            value: formatMetricValue(definition.format, value),
        };
    })
);

export const buildExitReasonRows = (metrics = {}) => (
    (metrics?.exitReasons ?? []).map((entry) => ({
        reason: entry?.reason ?? "—",
        count: entry?.count ?? 0,
        testId: `performance-exit-${entry?.reason ?? "unknown"}`,
    }))
);

/* A locked LIVE parameter whose legacy runtime semantic is not proven
   equivalent must not be shown with a canonical suffix. */
const isLegacyRawParameter = (name, scope) => (
    isLiveScope(scope) && LEGACY_RAW_SET.has(name)
);

export const displayPerformanceValue = (name, value, scope, metadata) => {
    if (value === null || value === undefined) return "—";
    if (isLegacyRawParameter(name, scope)) return String(value);
    return formatParameterValue(metadata, value);
};

const orderedNames = (values, schema) => {
    const schemaNames = Array.isArray(schema?.parameters)
        ? schema.parameters.map((entry) => entry?.name).filter(Boolean)
        : [];
    const valueNames = Object.keys(values ?? {});
    const ordered = schemaNames.filter((name) => valueNames.includes(name));
    const extra = valueNames
        .filter((name) => !schemaNames.includes(name))
        .sort();
    return [...ordered, ...extra];
};

export const buildRevisionValueRows = (revision, schema) => {
    const values = revision?.parameterValues;
    if (!values || typeof values !== "object") return [];
    return orderedNames(values, schema).map((name) => {
        const metadata = findSchemaParameter(schema, name);
        return {
            name,
            labelEn: metadata?.labelEn ?? name,
            labelJa: metadata?.labelJa ?? name,
            display: displayPerformanceValue(
                name,
                values[name],
                revision?.scope,
                metadata,
            ),
        };
    });
};

export const buildRevisionOptions = (performance = {}) => (
    (performance?.revisions ?? []).map((revision) => ({
        value: revision?.effectiveRevision,
        scope: revision?.scope,
        effectiveRevision: revision?.effectiveRevision,
        label: `${revision?.scope} R${revision?.effectiveRevision}`,
        observedTradeCount: revision?.observedTradeCount ?? 0,
    }))
);

export const buildRevisionHistoryRows = (performance = {}, schema) => (
    (performance?.revisions ?? []).map((revision) => ({
        key: `${revision?.scope}:${revision?.effectiveRevision}`,
        scope: revision?.scope,
        effectiveRevision: revision?.effectiveRevision,
        parameterSetId: revision?.parameterSetId ?? "—",
        featureContract: revision?.featureContract ?? "—",
        capturedAt: revision?.capturedAt ?? revision?.createdAt ?? "—",
        valueSource: revision?.valueSource ?? "UNAVAILABLE",
        observedTradeCount: revision?.observedTradeCount ?? 0,
        valuesAvailable: Boolean(revision?.parameterValues),
        valueRows: buildRevisionValueRows(revision, schema),
        metrics: buildMetricsView(revision?.metrics),
    }))
);

export const buildTradeRows = (records = []) => (
    records.map((record, index) => ({
        key: record?.recordId ?? `${record?.tradeId ?? "trade"}-${index}`,
        tradeId: record?.tradeId ?? "—",
        positionId: record?.positionId ?? "—",
        scope: record?.scope ?? "—",
        effectiveRevision: record?.effectiveRevision ?? "—",
        symbol: record?.symbol ?? "—",
        side: record?.side ?? "—",
        mode: record?.mode ?? "—",
        entryTimeDisplay: formatTradeTimestamp(record?.entryTimestamp),
        exitTimeDisplay: formatTradeTimestamp(record?.exitTimestamp),
        entryDisplay: isNumber(record?.entryPrice)
            ? String(record.entryPrice)
            : "—",
        exitDisplay: isNumber(record?.exitPrice)
            ? String(record.exitPrice)
            : "—",
        holdingDisplay: formatHoldingDuration(record?.holdingMs),
        pnlDisplay: formatPnl(record?.realizedPnl),
        pnlAuthoritative: record?.realizedPnlAuthoritative === true,
        exitReason: record?.exitReason ?? "—",
        parameterSetId: record?.parameterSetId ?? "—",
    }))
);

const formatDelta = (value) => {
    if (!isNumber(value)) return "—";
    const text = Number.isInteger(value) ? String(value) : value.toFixed(2);
    return value > 0 ? `+${text}` : text;
};

export const buildParameterDiffRows = (comparison, schema) => {
    const scope = comparison?.scope;
    return (comparison?.parameterDiff ?? []).map((item) => {
        const metadata = findSchemaParameter(schema, item?.name) ?? {
            unit: item?.unit,
        };
        return {
            name: item?.name,
            labelEn: metadata?.labelEn ?? item?.labelEn ?? item?.name,
            labelJa: metadata?.labelJa ?? item?.labelJa ?? item?.name,
            changed: item?.changed === true,
            aDisplay: displayPerformanceValue(
                item?.name,
                item?.a,
                scope,
                metadata,
            ),
            bDisplay: displayPerformanceValue(
                item?.name,
                item?.b,
                scope,
                metadata,
            ),
            deltaDisplay: formatDelta(item?.delta),
            testId: `performance-diff-${item?.name}`,
        };
    });
};

export const buildPerformanceViewModel = ({
    performance = null,
    comparison = null,
    schema = null,
    loading = false,
    error = null,
} = {}) => {
    const revisions = performance?.revisions ?? [];
    const records = performance?.records ?? [];
    const selectedRevision = (
        performance?.revision === null || performance?.revision === undefined
    )
        ? null
        : performance.revision;
    return {
        loading: loading === true,
        error: error ?? null,
        scope: performance?.scope ?? null,
        selectedRevision,
        allRevisions: selectedRevision === null,
        available: performance?.available === true,
        revisionCount: performance?.revisionCount ?? revisions.length,
        recordCount: performance?.recordCount ?? records.length,
        hasRevisions: revisions.length > 0,
        hasTrades: records.length > 0,
        revisions: buildRevisionHistoryRows(performance ?? {}, schema),
        revisionOptions: buildRevisionOptions(performance ?? {}),
        metrics: buildMetricsView(performance?.metrics),
        exitReasons: buildExitReasonRows(performance?.metrics),
        trades: buildTradeRows(records),
        comparison: comparison
            ? {
                scope: comparison.scope,
                changedCount: comparison.changedCount ?? 0,
                revisionA: comparison.revisionA ?? null,
                revisionB: comparison.revisionB ?? null,
                rows: buildParameterDiffRows(comparison, schema),
            }
            : null,
        semantics: performance?.semantics ?? null,
    };
};
