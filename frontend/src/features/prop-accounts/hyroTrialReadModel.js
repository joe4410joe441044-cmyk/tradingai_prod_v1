export const HYRO_DASHBOARD_URL = "https://my.hyrotrader.com/";

export const HYRO_CORE_25K_RULES = Object.freeze({
    sourceLabel: "HyroTrader公式公開ルール（2026-11-15確認）",
    sourceUrl: "https://www.hyrotrader.com/faq/getting-started/what-is-hyro-core/",
    initialBalance: 25_000,
    profitTarget: 2_500,
    dailyLossLimit: 750,
    maximumLoss: 1_250,
    minimumQualifyingTradingDays: 4,
    dailyProfitContributionCap: 1_000,
    timezone: "UTC",
});

const unknown = (reason) => Object.freeze({ state: "UNKNOWN", reason });
const knownNumber = (value) => typeof value === "number" && Number.isFinite(value);
const CHALLENGE_STATES = new Set(["ACTIVE", "HALTED", "PASSED", "FAILED", "EXPIRED", "CANCELLED"]);

export function classifyIssuedTrialRead(raw, { now = Date.now(), maximumAgeMs = 15 * 60 * 1000 } = {}) {
    if (!raw || typeof raw !== "object") return Object.freeze({ state: "FAILED", reason: "READ_ENVELOPE_INVALID" });
    if (raw.scopeMatch !== true) return Object.freeze({ state: "FAILED", reason: "CHALLENGE_ID_MISMATCH" });
    if (!CHALLENGE_STATES.has(raw.status) || !["EVALUATION", "FUNDED"].includes(raw.stage)) {
        return Object.freeze({ state: "FAILED", reason: "STATUS_OR_STAGE_UNCONFIRMED" });
    }
    const observed = Date.parse(raw.observedAt);
    if (!Number.isFinite(observed)) return Object.freeze({ state: "PARTIAL", reason: "OBSERVED_AT_UNKNOWN" });
    if (now - observed > maximumAgeMs) return Object.freeze({ state: "STALE", reason: "READ_TOO_OLD" });
    if (["PASSED", "FAILED", "EXPIRED", "CANCELLED"].includes(raw.status)) {
        return Object.freeze({ state: "ENDED", reason: `CHALLENGE_${raw.status}` });
    }
    return Object.freeze({
        state: raw.metricsComplete === true ? "READY" : "PARTIAL",
        reason: raw.metricsComplete === true ? null : "METRICS_OR_HISTORY_INCOMPLETE",
    });
}

export const ISSUED_HYRO_TRIAL_EVIDENCE = Object.freeze({
    id: "hyro-issued-trial-redacted",
    accountName: "Hyro Terminal 無料Trial — 25,000 USDT",
    plan: "FREE TRIAL（購入予定のHyro Coreとは別口座）",
    stage: "EVALUATION",
    period: "swing",
    platform: "HYRO TERMINAL",
    updatedAt: "2026-11-15T09:15:25.342619Z",
    source: "HYRO OFFICIAL MCP / CC-6R REDACTED READ",
    readKind: "ISSUED_READ_ONLY",
    sample: false,
    readOnly: true,
    status: "ACTIVE",
    dataQuality: "PARTIAL",
    stagePublicIdVerified: true,
    rules: Object.freeze({
        ruleSheetPresent: true,
        ruleSheetEntryCount: 6,
        adoptedRuleValueCount: 0,
        minimumTradingDays: 5,
        minimumTradingDaysUnit: "days",
        note: "TrialのruleSheet値は型・単位契約未確定のため自動採用しません",
    }),
    metrics: Object.freeze({
        source: "GET_STAGE_METRICS_AND_GET_STAGE_TRADES",
        observedAt: "2026-11-15T09:15:24.574156Z",
        initialBalance: null,
        currentEquity: 25_000,
        currentDrawdown: 0,
        currentLoss: 0,
        utcDayStartEquity: null,
        intradayMinimumEquity: null,
        qualifyingTradingDays: 0,
        dailyNetResults: Object.freeze([]),
        tradeHistoryComplete: true,
        tradePagesRead: 1,
        tradeMaximumPages: 5,
        periodLabel: "全期間指定 / 取得時点まで（開始・終了日は未提供）",
        pnl: null,
        positions: null,
        openOrders: null,
        conditionalOrders: null,
    }),
});

export function evaluateHyroCore25kReference(metrics = {}) {
    const rules = HYRO_CORE_25K_RULES;
    const currentEquity = metrics.currentEquity;
    const utcDayStartEquity = metrics.utcDayStartEquity;
    const intradayMinimumEquity = metrics.intradayMinimumEquity;
    const qualifyingTradingDays = metrics.qualifyingTradingDays;
    const dailyNetResults = metrics.dailyNetResults;

    const dailyLoss = knownNumber(utcDayStartEquity) && knownNumber(intradayMinimumEquity)
        ? Object.freeze({
            state: utcDayStartEquity - intradayMinimumEquity <= rules.dailyLossLimit ? "PASS" : "BLOCK",
            used: Math.max(0, utcDayStartEquity - intradayMinimumEquity),
            limit: rules.dailyLossLimit,
            basis: "UTC日初equityから日中最小equityまで",
        })
        : unknown("UTC日初equityまたは日中最小equityが未取得");

    const maximumLoss = knownNumber(currentEquity)
        ? Object.freeze({
            state: rules.initialBalance - currentEquity <= rules.maximumLoss ? "PASS" : "BLOCK",
            used: Math.max(0, rules.initialBalance - currentEquity),
            limit: rules.maximumLoss,
            basis: "25,000 USDT初期残高と現在equityの差",
        })
        : unknown("現在equityが未取得");

    const tradingDays = Number.isInteger(qualifyingTradingDays) && qualifyingTradingDays >= 0
        ? Object.freeze({
            state: qualifyingTradingDays >= rules.minimumQualifyingTradingDays ? "PASS" : "IN_PROGRESS",
            actual: qualifyingTradingDays,
            required: rules.minimumQualifyingTradingDays,
        })
        : unknown("適格取引日の判定材料が未取得");

    let profitProgress = unknown("UTC日別の決済損益が未取得または全期間取得を確認できません");
    if (Array.isArray(dailyNetResults) && dailyNetResults.every(knownNumber)) {
        const countedProfit = dailyNetResults.reduce((total, result) => (
            total + (result > 0 ? Math.min(result, rules.dailyProfitContributionCap) : result)
        ), 0);
        profitProgress = Object.freeze({
            state: countedProfit >= rules.profitTarget ? "PASS" : "IN_PROGRESS",
            countedProfit,
            target: rules.profitTarget,
            basis: "利益日は1日1,000 USDT上限、損失日は全額算入",
        });
    }

    const states = [dailyLoss.state, maximumLoss.state, tradingDays.state, profitProgress.state];
    const overall = states.includes("BLOCK")
        ? "BLOCK"
        : states.includes("UNKNOWN")
            ? "UNKNOWN"
            : states.every((state) => state === "PASS") ? "PASS" : "IN_PROGRESS";

    return Object.freeze({
        label: "Hyro Core 25K 参考評価（Trial公式判定とは別）",
        overall,
        rules,
        period: metrics.periodStart && metrics.periodEnd
            ? `${metrics.periodStart} — ${metrics.periodEnd}`
            : metrics.periodLabel || "期間未確認",
        dailyLoss,
        maximumLoss,
        tradingDays,
        profitProgress,
    });
}

export function accountStatusForChallenge(challenge) {
    if (challenge?.readKind !== "ISSUED_READ_ONLY") return null;
    const metrics = challenge.metrics || {};
    const shown = (value, suffix = "") => knownNumber(value) ? `${value.toLocaleString()}${suffix}` : "未確認";
    return Object.freeze({
        pnl: shown(metrics.pnl, " USDT"),
        dailyLossHeadroom: "未確認",
        maximumLossHeadroom: "未確認",
        balance: "未確認",
        equity: shown(metrics.currentEquity, " USDT"),
        currentDrawdown: shown(metrics.currentDrawdown, "（MCP報告値・単位未確認）"),
        currentLoss: shown(metrics.currentLoss, "（MCP報告値・単位未確認）"),
        qualifyingTradingDays: Number.isInteger(metrics.qualifyingTradingDays)
            ? `${metrics.qualifyingTradingDays}日（全決済履歴取得完了）`
            : "未確認",
        positions: metrics.positions === 0 ? "0（全件取得確認済み）" : "未確認",
        openOrders: metrics.openOrders === 0 ? "0（全件取得確認済み）" : "未確認",
        conditionalOrders: metrics.conditionalOrders === 0 ? "0（全件取得確認済み）" : "未確認",
        rules: challenge.rules.note,
    });
}
