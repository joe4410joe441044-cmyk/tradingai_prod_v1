export const HYRO_TRIAL_OPERATOR_FLAG = "VITE_HYRO_TRIAL_OPERATOR_PREVIEW_ENABLED";

export const isHyroTrialOperatorEnabled = (environment = import.meta.env || {}) => (
    environment[HYRO_TRIAL_OPERATOR_FLAG] === "true"
);

export const HYRO_TRIAL_OPERATOR_ENABLED = isHyroTrialOperatorEnabled();

export const HYRO_SAMPLE_CHALLENGES = Object.freeze([
    Object.freeze({
        id: "hyro-sample-free-trial-a",
        accountName: "HyroTrader 無料トライアル Sample A",
        plan: "FREE TRIAL SAMPLE",
        stage: "PRE-ISSUANCE SIMULATION",
        period: "14日（画面検証用サンプル）",
        platform: "HYRO PLATFORM SAMPLE",
        updatedAt: "2026-11-15T00:00:00+09:00",
    }),
    Object.freeze({
        id: "hyro-sample-free-trial-b",
        accountName: "HyroTrader 無料トライアル Sample B",
        plan: "FREE TRIAL SAMPLE",
        stage: "PRE-ISSUANCE SIMULATION",
        period: "7日（口座分離確認用サンプル）",
        platform: "HYRO PLATFORM SAMPLE",
        updatedAt: "2026-11-15T00:00:00+09:00",
    }),
]);

export const EMPTY_HYRO_SETTINGS = Object.freeze({
    strategy: "",
    riskPerTradePercent: "",
    dailyLossLimitPercent: "",
    maximumLossPercent: "",
});

export const SAMPLE_ACCOUNT_STATUS = Object.freeze({
    pnl: "+120.00 USD（サンプル）",
    dailyLossHeadroom: "380.00 USD（サンプル）",
    maximumLossHeadroom: "880.00 USD（サンプル）",
    balance: "10,120.00 USD（サンプル）",
    equity: "未確認",
    positions: "未確認",
    openOrders: "未確認",
    conditionalOrders: "未確認",
    rules: "架空ルール: 日次損失5% / 最大損失10% / 利益目標8%",
});

const delay = (milliseconds) => new Promise((resolve) => {
    globalThis.setTimeout(resolve, milliseconds);
});

export const syntheticHyroTrialClient = Object.freeze({
    async checkConnection() {
        await delay(80);
        return Object.freeze({
            state: "CONNECTED_SAMPLE",
            readOnly: true,
            externalNetworkCalls: 0,
            orderCalls: 0,
        });
    },
    async listChallenges() {
        await delay(100);
        return Object.freeze({
            quality: "COMPLETE_SAMPLE",
            source: "IN_MEMORY_FIXTURE",
            challenges: HYRO_SAMPLE_CHALLENGES,
            externalNetworkCalls: 0,
            orderCalls: 0,
        });
    },
    async startSimulation() {
        await delay(80);
        return Object.freeze({ state: "RUNNING", orderCalls: 0 });
    },
    async stopSimulation() {
        await delay(80);
        return Object.freeze({ state: "STOPPED", orderCalls: 0 });
    },
});

export function validateHyroTrialSettings(settings) {
    const errors = [];
    if (!String(settings?.strategy || "").trim()) errors.push("戦略を選択してください");
    for (const [key, label, maximum] of [
        ["riskPerTradePercent", "1取引リスク", 5],
        ["dailyLossLimitPercent", "日次損失上限", 20],
        ["maximumLossPercent", "最大損失上限", 30],
    ]) {
        const value = Number(settings?.[key]);
        if (!Number.isFinite(value) || value <= 0 || value > maximum) {
            errors.push(`${label}を0より大きく${maximum}以下で入力してください`);
        }
    }
    return Object.freeze({ valid: errors.length === 0, errors: Object.freeze(errors) });
}

export function deriveHyroTrialReadiness({ selectedChallenge, savedSettings, simulation }) {
    const reasons = [];
    if (!selectedChallenge) reasons.push("チャレンジ未選択");
    const validation = validateHyroTrialSettings(savedSettings);
    if (!savedSettings) reasons.push("戦略・リスク設定未保存");
    else if (!validation.valid) reasons.push(...validation.errors);
    if (simulation?.state === "RUNNING") reasons.push("シミュレーションは既に稼働中です");
    if (["STARTING", "STOPPING"].includes(simulation?.state)) reasons.push("状態変更処理中です");
    return Object.freeze({
        state: reasons.length === 0 ? "READY" : "BLOCKED",
        reasons: Object.freeze(reasons),
        executionMode: "SIMULATION_ONLY_NO_ORDERS",
        realHyroStartEnabled: false,
        realHyroStartReason: "実Hyroの読み取り・発注・停止権限が未確認のため無効",
    });
}
