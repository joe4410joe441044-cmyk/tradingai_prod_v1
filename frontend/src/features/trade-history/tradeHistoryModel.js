/* =================================================
   TRADE HISTORY view model (pure, testable).

   Maps the read-only canonical Trade History payload into deterministic
   presentation rows and owns the deeplink contract shared with Parameter
   Settings.  It contains no React and no network.

   Truthfulness rules:
   - only Production-eligible records returned by the backend are shown;
   - missing values render as an explicit "—", never as a fabricated zero;
   - the result is a factual classification of the realized PnL and is never a
     score, ranking or recommendation.
================================================ */

import {
    formatHoldingDuration,
    formatPnl,
    formatTradeTimestamp,
} from "../parameter-settings/parameterPerformanceModel.js";

export const TRADE_HISTORY_PATH = "/trade-history";
export const PARAMETER_SETTINGS_PATH = "/parameter-settings";

export const DEFAULT_PAGE_SIZE = 50;

export const DEFAULT_FILTERS = Object.freeze({
    scope: null,
    period: "all",
    mode: null,
    symbol: null,
    side: null,
    result: null,
    revision: null,
    exitReason: null,
    controlSource: null,
    fromTimestamp: null,
    toTimestamp: null,
    sort: "exitTimestamp",
    direction: "desc",
    page: 1,
    pageSize: DEFAULT_PAGE_SIZE,
});

export const RESULT_OPTIONS = Object.freeze([
    { value: "WIN", labelEn: "Win", labelJa: "勝ち" },
    { value: "LOSS", labelEn: "Loss", labelJa: "負け" },
    { value: "BREAKEVEN", labelEn: "Breakeven", labelJa: "損益ゼロ" },
    { value: "UNKNOWN", labelEn: "Unknown", labelJa: "不明" },
]);

export const CONTROL_SOURCE_OPTIONS = Object.freeze([
    { value: "BOT", labelEn: "BOT", labelJa: "自動" },
    { value: "MANUAL", labelEn: "MANUAL", labelJa: "手動" },
    { value: "UNKNOWN", labelEn: "Unknown", labelJa: "不明" },
]);

export const SORT_OPTIONS = Object.freeze([
    { value: "exitTimestamp", labelEn: "Exit time", labelJa: "決済時刻" },
    { value: "entryTimestamp", labelEn: "Entry time", labelJa: "エントリー時刻" },
    { value: "realizedPnl", labelEn: "Realized PnL", labelJa: "実現損益" },
    { value: "holdingMs", labelEn: "Holding time", labelJa: "保有時間" },
    { value: "symbol", labelEn: "Symbol", labelJa: "銘柄" },
    { value: "effectiveRevision", labelEn: "Revision", labelJa: "改訂" },
    { value: "tradeId", labelEn: "Trade ID", labelJa: "取引ID" },
]);

const SORT_FIELD_SET = new Set(SORT_OPTIONS.map((item) => item.value));
const SCOPES = new Set(["PAPER", "LIVE"]);
const MODES = new Set(["paper", "live"]);
const SIDES = new Set(["BUY", "SELL"]);
const RESULTS = new Set(["WIN", "LOSS", "BREAKEVEN", "UNKNOWN"]);
const CONTROL_SOURCES = new Set(["BOT", "MANUAL", "UNKNOWN"]);

const toNumber = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
};

const toStringOrNull = (value) => (
    typeof value === "string" && value.trim() !== "" ? value.trim() : null
);

const firstParam = (params, keys) => {
    for (const key of keys) {
        const value = params.get(key);
        if (value !== null && value !== undefined && value !== "") return value;
    }
    return null;
};

export const parseTradeHistoryQuery = (search = "") => {
    const params = new URLSearchParams(
        typeof search === "string" ? search.replace(/^\?/, "") : "",
    );
    const scopeRaw = firstParam(params, ["scope"]);
    const scope = scopeRaw && SCOPES.has(scopeRaw.toUpperCase())
        ? scopeRaw.toUpperCase()
        : DEFAULT_FILTERS.scope;
    const modeRaw = firstParam(params, ["mode"]);
    const mode = modeRaw && MODES.has(modeRaw.toLowerCase())
        ? modeRaw.toLowerCase()
        : null;
    const sideRaw = firstParam(params, ["side"]);
    const side = sideRaw && SIDES.has(sideRaw.toUpperCase())
        ? sideRaw.toUpperCase()
        : null;
    const resultRaw = firstParam(params, ["result"]);
    const result = resultRaw && RESULTS.has(resultRaw.toUpperCase())
        ? resultRaw.toUpperCase()
        : null;
    const controlRaw = firstParam(params, ["controlSource", "control_source"]);
    const controlSource = (
        controlRaw && CONTROL_SOURCES.has(controlRaw.toUpperCase())
    )
        ? controlRaw.toUpperCase()
        : null;
    const sortRaw = firstParam(params, ["sort"]);
    const sort = sortRaw && SORT_FIELD_SET.has(sortRaw)
        ? sortRaw
        : DEFAULT_FILTERS.sort;
    const directionRaw = firstParam(params, ["direction"]);
    const direction = directionRaw && directionRaw.toLowerCase() === "asc"
        ? "asc"
        : "desc";
    const page = Math.max(1, Math.trunc(toNumber(firstParam(params, ["page"])) ?? 1));
    const pageSize = Math.max(
        1,
        Math.trunc(
            toNumber(firstParam(params, ["pageSize", "page_size"]))
                ?? DEFAULT_PAGE_SIZE,
        ),
    );

    return {
        scope,
        period: ["today", "7d", "30d", "90d", "all", "custom"].includes(params.get("period")) ? params.get("period") : "all",
        mode,
        symbol: toStringOrNull(firstParam(params, ["symbol"])),
        side,
        result,
        revision: toNumber(firstParam(params, ["revision"])),
        exitReason: toStringOrNull(firstParam(params, ["exitReason", "exit_reason"])),
        controlSource,
        fromTimestamp: toNumber(firstParam(params, ["fromTimestamp", "from"])),
        toTimestamp: toNumber(firstParam(params, ["toTimestamp", "to"])),
        sort,
        direction,
        page,
        pageSize,
    };
};

export const buildTradeHistoryQuery = (filters = {}) => {
    const params = new URLSearchParams();
    const append = (key, value) => {
        if (value === null || value === undefined || value === "") return;
        params.set(key, String(value));
    };
    append("period", filters.period);
    append("scope", filters.scope);
    append("mode", filters.mode);
    append("symbol", filters.symbol);
    append("side", filters.side);
    append("result", filters.result);
    append("revision", filters.revision);
    append("exitReason", filters.exitReason);
    append("controlSource", filters.controlSource);
    append("fromTimestamp", filters.fromTimestamp);
    append("toTimestamp", filters.toTimestamp);
    if (filters.sort && filters.sort !== DEFAULT_FILTERS.sort) {
        append("sort", filters.sort);
    }
    if (filters.direction && filters.direction !== DEFAULT_FILTERS.direction) {
        append("direction", filters.direction);
    }
    if (filters.page && Number(filters.page) > 1) {
        append("page", filters.page);
    }
    if (filters.pageSize && Number(filters.pageSize) !== DEFAULT_PAGE_SIZE) {
        append("pageSize", filters.pageSize);
    }
    return params.toString();
};

export const isTradeHistoryQueryReady = (filters = {}) => {
    if (filters.period !== "custom") return true;
    const from = filters.fromTimestamp;
    const to = filters.toTimestamp;
    return (
        typeof from === "number"
        && Number.isFinite(from)
        && typeof to === "number"
        && Number.isFinite(to)
        && from <= to
    );
};

export const buildTradeHistoryDeeplink = (scope, revision, extra = {}) => {
    const query = buildTradeHistoryQuery({
        ...DEFAULT_FILTERS,
        ...extra,
        scope: scope ?? DEFAULT_FILTERS.scope,
        revision: revision ?? null,
    });
    return query ? `${TRADE_HISTORY_PATH}?${query}` : TRADE_HISTORY_PATH;
};

export const buildParameterSettingsDeeplink = (scope, revision) => {
    const params = new URLSearchParams();
    if (scope) params.set("scope", String(scope));
    if (revision !== null && revision !== undefined && revision !== "") {
        params.set("revision", String(revision));
    }
    const query = params.toString();
    return query
        ? `${PARAMETER_SETTINGS_PATH}?${query}`
        : PARAMETER_SETTINGS_PATH;
};

export const resultLabel = (result) => {
    const match = RESULT_OPTIONS.find((item) => item.value === result);
    if (!match) return "—";
    return `${match.labelEn}（${match.labelJa}）`;
};

const pad = (value) => String(value).padStart(2, "0");

/* Period inputs are local calendar dates.  They convert to the canonical Unix
   epoch-second bounds that the backend applies to the EXIT time. */
export const dateInputToEpoch = (value, endOfDay = false) => {
    if (typeof value !== "string" || value.trim() === "") return null;
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
    if (!match) return null;
    const [, year, month, day] = match;
    const date = endOfDay
        ? new Date(
            Number(year), Number(month) - 1, Number(day),
            23, 59, 59, 999,
        )
        : new Date(Number(year), Number(month) - 1, Number(day), 0, 0, 0, 0);
    if (Number.isNaN(date.getTime())) return null;
    return date.getTime() / 1000;
};

export const epochToDateInput = (value) => {
    if (value === null || value === undefined || value === "") return "";
    const seconds = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(seconds)) return "";
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.getTime())) return "";
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

export const buildTradeRows = (records = []) => (
    records.map((record, index) => ({
        key: record?.recordId ?? `${record?.tradeId ?? "trade"}-${index}`,
        recordId: record?.recordId ?? null,
        tradeId: record?.tradeId ?? "—",
        positionId: record?.positionId ?? "—",
        scope: record?.scope ?? "—",
        mode: record?.mode ?? "—",
        symbol: record?.symbol ?? "—",
        side: record?.side ?? "—",
        effectiveRevision: (
            Number.isInteger(record?.effectiveRevision) ? record.effectiveRevision : "—"
        ),
        controlSource: record?.controlSource ?? "UNKNOWN",
        result: record?.result ?? "UNKNOWN",
        resultLabel: resultLabel(record?.result ?? "UNKNOWN"),
        entryTimeDisplay: formatTradeTimestamp(record?.entryTimestamp),
        exitTimeDisplay: formatTradeTimestamp(record?.exitTimestamp),
        entryDisplay: typeof record?.entryPrice === "number"
            ? String(record.entryPrice)
            : "—",
        exitDisplay: typeof record?.exitPrice === "number"
            ? String(record.exitPrice)
            : "—",
        quantityDisplay: typeof record?.quantity === "number" ? String(record.quantity) : "—",
        holdingDisplay: formatHoldingDuration(record?.holdingMs),
        pnlDisplay: formatPnl(record?.realizedPnl),
        pnlAuthoritative: record?.realizedPnlAuthoritative === true,
        exitReason: record?.exitReason ?? "—",
        parameterSetId: record?.parameterSetId ?? "—",
        parameterContextAvailable: record?.parameterContextAvailable === true,
    }))
);

export const buildPaginationView = (pagination = {}) => {
    const page = pagination?.page ?? 1;
    const pageSize = pagination?.pageSize ?? DEFAULT_PAGE_SIZE;
    const total = pagination?.total ?? 0;
    const pageCount = pagination?.pageCount ?? 0;
    const hasNext = pagination?.hasNext === true;
    const hasPrevious = pagination?.hasPrevious === true;
    return {
        page,
        pageSize,
        total,
        pageCount,
        hasNext,
        hasPrevious,
        rangeStart: total === 0 ? 0 : (page - 1) * pageSize + 1,
        rangeEnd: total === 0 ? 0 : Math.min(page * pageSize, total),
    };
};

export const buildFilterOptions = (options = {}) => ({
    symbols: Array.isArray(options?.symbol) ? options.symbol : [],
    revisions: Array.isArray(options?.revision) ? options.revision : [],
    exitReasons: Array.isArray(options?.exitReason) ? options.exitReason : [],
});

export const buildTradeHistoryViewModel = ({
    data = null,
    loading = false,
    error = null,
} = {}) => {
    const records = data?.records ?? [];
    return {
        loading: loading === true,
        error: error ?? null,
        available: data?.available === true,
        records: buildTradeRows(records),
        recordCount: records.length,
        metrics: data?.metrics ?? null,
        pagination: buildPaginationView(data?.pagination),
        options: buildFilterOptions(data?.options),
        filters: data?.filters ?? null,
        sort: data?.sort ?? null,
        periodTimeAuthority: data?.periodTimeAuthority ?? "EXIT_TIME",
        resultClassification: data?.resultClassification ?? null,
        semantics: data?.semantics ?? null,
    };
};
