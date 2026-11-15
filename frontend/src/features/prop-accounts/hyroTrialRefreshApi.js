import { authenticatedControlRequest } from "../auth/operatorAuth.js";

export const HYRO_TRIAL_REFRESH_PATH = "/api/prop-accounts/hyro-trial/refresh";

const FORBIDDEN_KEY = /token|secret|credential|authorization/i;
const STATES = new Set(["ACTIVE", "HALTED", "PASSED", "FAILED", "EXPIRED", "CANCELLED", "UNKNOWN"]);
const STAGES = new Set(["EVALUATION", "FUNDED", "UNKNOWN"]);
const keyIsForbidden = (key) => (
    FORBIDDEN_KEY.test(key) || (/publicid/i.test(key) && key !== "stagePublicIdVerified")
);


const hasForbiddenKey = (value) => {
    if (!value || typeof value !== "object") return false;
    return Object.entries(value).some(([key, nested]) => (
        keyIsForbidden(key) || hasForbiddenKey(nested)
    ));
};

const numberOrNull = (value) => value === null || (typeof value === "number" && Number.isFinite(value));

export function validateHyroTrialRefreshChallenge(value) {
    if (!value || typeof value !== "object" || Array.isArray(value) || hasForbiddenKey(value)) return null;
    if (
        value.id !== "hyro-issued-trial-redacted"
        || value.readKind !== "ISSUED_READ_ONLY"
        || value.readOnly !== true
        || value.sample !== false
        || !STATES.has(value.status)
        || !STAGES.has(value.stage)
        || !["READY", "PARTIAL"].includes(value.dataQuality)
        || !Number.isFinite(Date.parse(value.updatedAt))
        || !value.metrics
        || typeof value.metrics !== "object"
        || Array.isArray(value.metrics)
    ) return null;
    const metrics = value.metrics;
    for (const name of [
        "initialBalance", "currentEquity", "currentDrawdown", "currentLoss",
        "utcDayStartEquity", "intradayMinimumEquity", "qualifyingTradingDays",
        "pnl", "positions", "openOrders", "conditionalOrders",
    ]) {
        if (!numberOrNull(metrics[name])) return null;
    }
    if (
        metrics.dailyNetResults !== null
        && (!Array.isArray(metrics.dailyNetResults)
            || metrics.dailyNetResults.some((entry) => typeof entry !== "number" || !Number.isFinite(entry)))
    ) return null;
    if (typeof metrics.tradeHistoryComplete !== "boolean") return null;
    return Object.freeze({
        ...value,
        rules: Object.freeze({ ...value.rules }),
        metrics: Object.freeze({
            ...metrics,
            dailyNetResults: Array.isArray(metrics.dailyNetResults)
                ? Object.freeze([...metrics.dailyNetResults])
                : null,
        }),
    });
}

export async function refreshHyroTrialProgress({ signal } = {}) {
    try {
        const response = await authenticatedControlRequest(HYRO_TRIAL_REFRESH_PATH, {
            method: "POST",
            headers: { Accept: "application/json" },
            signal,
        });
        let body = null;
        try {
            body = await response.json();
        } catch {
            body = null;
        }
        const challenge = response.ok && body?.ok === true
            ? validateHyroTrialRefreshChallenge(body.challenge)
            : null;
        if (challenge) return { ok: true, status: response.status, challenge };
        return {
            ok: false,
            status: response.status,
            code: typeof body?.error?.code === "string" ? body.error.code : "HYRO_TRIAL_REFRESH_FAILED",
        };
    } catch {
        return { ok: false, status: 0, code: "HYRO_TRIAL_REFRESH_NETWORK_FAILED" };
    }
}
