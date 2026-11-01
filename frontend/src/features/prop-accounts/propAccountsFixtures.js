import { PROP_ACCOUNTS_VIEW_SCHEMA } from "./propAccountsViewModel.js";

export const NORMAL_ACCOUNT_ID = "acc_10000000000040008000000000000001";
export const PROP_ACCOUNT_ID = "acc_20000000000040008000000000000002";

const money = (amount, currency = "USDT", unit = "ASSET") => ({ amount, currency, unit });
const usd = (amount) => money(amount, "USD", "USD_EQUIVALENT");

const normalAccount = Object.freeze({
    accountSummary: {
        accountId: NORMAL_ACCOUNT_ID,
        label: "通常取引サンプル口座",
        accountType: "NORMAL",
        platform: "KUCOIN_FUTURES_FIXTURE",
        phase: null,
        environment: "LIVE",
    },
    connection: {
        state: "NOT_CONNECTED",
        readOnly: true,
        keyEligibility: "NOT_APPLICABLE",
        safeReasonCode: "FIXTURE_NORMAL_ACCOUNT",
    },
    observation: {
        quality: "COMPLETE",
        freshness: "FRESH",
        observedAt: "2026-11-01T07:40:00Z",
        oldestSourceAt: "2026-11-01T07:39:58Z",
        newestSourceAt: "2026-11-01T07:40:00Z",
        source: "FABRICATED_NORMAL_FIXTURE",
        balance: money("98765432101234567890.123456789012345678", "USDT"),
        equity: money("98765432101234567891.000000000000000001", "USDT"),
        realizedPnl: money("0", "USDT"),
        unrealizedPnl: money("0.876543210987654323", "USDT"),
        missingFields: [],
    },
    positions: { quality: "COMPLETE", items: [], missingFields: [] },
    openOrders: { quality: "COMPLETE", items: [], missingFields: [] },
    propRules: { readiness: "NOT_APPLICABLE", limits: [], unknownFields: [] },
    executionCapability: { reasons: ["NORMAL_FIXTURE_VIEW_ONLY"] },
    aiContext: { freshness: "UNKNOWN", missingFields: ["canonicalContextBinding"] },
});

const propBase = Object.freeze({
    accountSummary: {
        accountId: PROP_ACCOUNT_ID,
        label: "HyroTrader Demo サンプル口座",
        accountType: "PROP",
        platform: "BYBIT_DEMO",
        phase: "CHALLENGE",
        environment: "EXTERNAL_SIMULATION",
    },
    connection: {
        state: "NOT_CONNECTED",
        readOnly: true,
        keyEligibility: "SUPPORT_CONFIRMATION_REQUIRED",
        safeReasonCode: "DIAGNOSTIC_NOT_RUN",
    },
    observation: {
        quality: "UNKNOWN",
        freshness: "UNKNOWN",
        observedAt: null,
        oldestSourceAt: null,
        newestSourceAt: null,
        source: "FABRICATED_PROP_FIXTURE",
        balance: null,
        equity: null,
        realizedPnl: null,
        unrealizedPnl: null,
        missingFields: ["balance", "equity", "realizedPnl", "unrealizedPnl"],
    },
    positions: { quality: "UNKNOWN", items: [], missingFields: ["positions"] },
    openOrders: { quality: "UNKNOWN", items: [], missingFields: ["openOrders"] },
    propRules: {
        readiness: "RULES_UNKNOWN",
        ruleSetId: null,
        revision: null,
        phase: "CHALLENGE",
        sampleCalculated: false,
        explanation: "公式ルールと評価engineは未接続です。未確認を正常扱いしません。",
        limits: [
            { code: "DAILY_LOSS", state: "UNKNOWN", threshold: null, actual: null, headroom: null },
            { code: "MAXIMUM_LOSS", state: "UNKNOWN", threshold: null, actual: null, headroom: null },
            { code: "PROFIT_TARGET", state: "UNKNOWN", threshold: null, actual: null, headroom: null },
        ],
        unknownFields: ["dailyLossLimit", "maximumLossLimit", "profitTarget"],
    },
    executionCapability: { reasons: [] },
    aiContext: { freshness: "UNKNOWN", missingFields: ["canonicalContextBinding"] },
});

const connectedObservation = {
    quality: "COMPLETE",
    freshness: "FRESH",
    observedAt: "2026-11-01T07:45:00Z",
    oldestSourceAt: "2026-11-01T07:44:57Z",
    newestSourceAt: "2026-11-01T07:45:00Z",
    source: "FABRICATED_PROP_FIXTURE",
    balance: money("12345678901234567890.123456789012345678", "USDT"),
    equity: usd("12345678901234567999.000000000000000001"),
    realizedPnl: money("-42.000000000000000009", "USDT"),
    unrealizedPnl: money("108.876543210987654332", "USDT"),
    missingFields: [],
};

const connectedPositions = {
    quality: "COMPLETE",
    missingFields: [],
    items: [{
        symbol: "BTCUSDT",
        side: "LONG",
        quantity: "0.000000010000000001",
        quantityUnit: "BTC",
        entryPrice: money("67321.12345678", "USDT"),
        markPrice: money("67429.99999999", "USDT"),
        unrealizedPnl: money("108.876543210987654332", "USDT"),
        status: "OPEN",
    }],
};

const connectedOrders = {
    quality: "COMPLETE",
    missingFields: [],
    items: [{
        symbol: "ETHUSDT",
        side: "SELL",
        quantity: "12.000000000000000001",
        quantityUnit: "ETH",
        price: money("4250.123456789", "USDT"),
        status: "NEW",
    }],
};

const sampleRules = {
    readiness: "READY",
    ruleSetId: "fixture-rule-set",
    revision: "1",
    phase: "CHALLENGE",
    sampleCalculated: true,
    explanation: "架空ルールのサンプルです。HyroTraderの現行公式ルールではありません。",
    limits: [
        { code: "DAILY_LOSS", state: "PASS", threshold: usd("500.00"), actual: usd("42.00"), headroom: usd("458.00") },
        { code: "MAXIMUM_LOSS", state: "PASS", threshold: usd("1000.00"), actual: usd("42.00"), headroom: usd("958.00") },
        { code: "PROFIT_TARGET", state: "IN_PROGRESS", threshold: usd("800.00"), actual: usd("108.876543210987654332"), headroom: usd("691.123456789012345668") },
    ],
    unknownFields: [],
};

const mergeProp = (overrides = {}) => ({
    ...propBase,
    ...overrides,
    accountSummary: { ...propBase.accountSummary, ...(overrides.accountSummary ?? {}) },
    connection: { ...propBase.connection, ...(overrides.connection ?? {}) },
    observation: { ...propBase.observation, ...(overrides.observation ?? {}) },
    positions: { ...propBase.positions, ...(overrides.positions ?? {}) },
    openOrders: { ...propBase.openOrders, ...(overrides.openOrders ?? {}) },
    propRules: { ...propBase.propRules, ...(overrides.propRules ?? {}) },
    executionCapability: {
        ...propBase.executionCapability,
        ...(overrides.executionCapability ?? {}),
    },
    aiContext: { ...propBase.aiContext, ...(overrides.aiContext ?? {}) },
});

export const PROP_FIXTURE_SCENARIOS = Object.freeze([
    {
        id: "not_configured",
        label: "1. 未設定・口座未作成",
        account: mergeProp({
            accountSummary: { phase: "UNKNOWN" },
            connection: { state: "NOT_CONFIGURED", safeReasonCode: "ACCOUNT_NOT_CREATED" },
        }),
    },
    {
        id: "observer_eligibility_pending",
        label: "2. observerキー条件確認待ち",
        account: mergeProp({
            connection: {
                state: "EXTERNAL_REQUIREMENT_PENDING",
                keyEligibility: "SUPPORT_CONFIRMATION_REQUIRED",
                safeReasonCode: "OBSERVER_KEY_ELIGIBILITY_PENDING",
            },
        }),
    },
    {
        id: "credential_reference_missing",
        label: "3. credential reference未設定",
        account: mergeProp({
            connection: {
                state: "CREDENTIAL_REFERENCE_MISSING",
                safeReasonCode: "CREDENTIAL_REFERENCE_MISSING",
            },
        }),
    },
    {
        id: "not_connected",
        label: "4. 未接続",
        account: mergeProp(),
    },
    {
        id: "connected_read_only",
        label: "5. サンプル上のread-only接続成功",
        account: mergeProp({
            connection: {
                state: "CONNECTED_READ_ONLY",
                keyEligibility: "SAMPLE_ASSUMED_ELIGIBLE",
                safeReasonCode: "SAMPLE_CONNECTION_ONLY",
            },
            observation: connectedObservation,
            positions: connectedPositions,
            openOrders: connectedOrders,
            propRules: sampleRules,
        }),
    },
    {
        id: "auth_failure",
        label: "6. auth failure",
        account: mergeProp({
            connection: { state: "AUTH_FAILED", safeReasonCode: "AUTHENTICATION_FAILED" },
            observation: { quality: "FAILED", freshness: "UNKNOWN" },
            positions: { quality: "FAILED" },
            openOrders: { quality: "FAILED" },
        }),
    },
    {
        id: "scope_mismatch",
        label: "7. account / scope mismatch",
        account: mergeProp({
            connection: { state: "SCOPE_MISMATCH", safeReasonCode: "ACCOUNT_SCOPE_MISMATCH" },
            observation: { quality: "FAILED", freshness: "UNKNOWN" },
            positions: { quality: "FAILED" },
            openOrders: { quality: "FAILED" },
        }),
    },
    {
        id: "partial_data",
        label: "8. partial data",
        account: mergeProp({
            connection: { state: "CONNECTED_READ_ONLY", safeReasonCode: "PARTIAL_ENDPOINT_RESULT" },
            observation: {
                ...connectedObservation,
                quality: "PARTIAL",
                equity: null,
                missingFields: ["equity", "openOrders"],
            },
            positions: { ...connectedPositions, quality: "PARTIAL", missingFields: ["markPrice"] },
            openOrders: { quality: "FAILED", items: [], missingFields: ["openOrders"] },
        }),
    },
    {
        id: "stale_data",
        label: "9. stale data",
        account: mergeProp({
            connection: { state: "CONNECTED_READ_ONLY", safeReasonCode: "SOURCE_DATA_STALE" },
            observation: {
                ...connectedObservation,
                quality: "STALE",
                freshness: "STALE",
                observedAt: "2026-10-31T07:45:00Z",
                oldestSourceAt: "2026-10-31T07:44:57Z",
                newestSourceAt: "2026-10-31T07:45:00Z",
            },
            positions: { ...connectedPositions, quality: "STALE" },
            openOrders: { ...connectedOrders, quality: "STALE" },
        }),
    },
    {
        id: "rules_unknown",
        label: "10. PROP rules unknown",
        account: mergeProp({
            connection: { state: "CONNECTED_READ_ONLY", safeReasonCode: "RULE_SOURCE_NOT_CONFIRMED" },
            observation: connectedObservation,
            positions: { quality: "COMPLETE", items: [], missingFields: [] },
            openOrders: { quality: "COMPLETE", items: [], missingFields: [] },
        }),
    },
]);

export const PROP_FIXTURE_SCENARIO_IDS = Object.freeze(
    PROP_FIXTURE_SCENARIOS.map(({ id }) => id),
);

export function createPropAccountsFixture({
    scenarioId = "not_configured",
    viewedAccountId = PROP_ACCOUNT_ID,
} = {}) {
    const scenario = PROP_FIXTURE_SCENARIOS.find(({ id }) => id === scenarioId)
        ?? PROP_FIXTURE_SCENARIOS[0];
    return {
        schemaVersion: PROP_ACCOUNTS_VIEW_SCHEMA,
        generatedAt: "2026-11-01T08:00:00Z",
        displayTimezone: "Asia/Tokyo",
        fixture: { enabled: true, label: "サンプル表示 / 実口座未接続" },
        viewedAccountId,
        accounts: [normalAccount, scenario.account],
    };
}
