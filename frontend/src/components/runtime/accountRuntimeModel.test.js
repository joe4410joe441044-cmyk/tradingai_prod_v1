import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const loadModule = async () => {
    const source = new URL("./accountRuntimeModel.js", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".account-runtime-model-test-"));
    const output = join(temporary, "accountRuntimeModel.mjs");
    const apiStub = moduleUrl(
        "export const API={botStatus:()=>'/api/bot/status',paperAccountCapital:()=>'/api/bot/paper-account/capital'};",
    );
    try {
        await writeFile(output, transformed.code
            .replace('from "../../api/index.js";', `from "${apiStub}";`));
        return await import(`${pathToFileURL(output).href}?test=account-runtime-model`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

/* Canonical shared-model fixtures. Mirrors the AccountStatusPage fixture so
   both consumers agree on canonical values. */
const REAL_NOT_CONNECTED = {
    exchange: "kucoin",
    accountType: "KUCOIN_FUTURES",
    connected: false,
    authenticated: false,
    apiKeyPresent: false,
    permission: "NOT_VERIFIED",
    balance: null,
    equity: null,
    availableBalance: null,
    positions: [],
    positionSummary: null,
    lastSync: null,
    stale: false,
    loading: false,
};

const makeStatus = (overrides = {}) => ({
    selectedMode: "PAPER",
    executionMode: "SIMULATION",
    realOrderAllowed: false,
    executionEntryAllowed: false,
    liveOrderEntryAllowed: false,
    executionEnabled: false,
    botState: "STOPPED",
    pendingOrder: false,
    exchange: "kucoin",
    exchangeAuth: "NOT_VERIFIED",
    exchangeConnection: "NOT_CONNECTED",
    apiKeyStatus: "MISSING",
    permission: "NOT_VERIFIED",
    accountType: "UNKNOWN",
    realAccountConnected: false,
    balance: 1000,
    equity: 1000,
    availableBalance: 980,
    pnl: 0,
    accountRuntime: {
        realAccount: { ...REAL_NOT_CONNECTED },
        paperAccount: {
            balance: 1000,
            equity: 1000,
            availableBalance: 980,
            positions: [],
            totalPnl: 0,
            source: "PAPER_SIMULATION",
            positionState: "FLAT",
            available: true,
        },
        execution: {
            selectedMode: "PAPER",
            executionMode: "SIMULATION",
            realOrderAllowed: false,
        },
        connection: {
            exchange: "kucoin",
            connected: false,
            authenticated: false,
            apiKeyStatus: "MISSING",
            permission: "NOT_VERIFIED",
        },
    },
    ...overrides,
});

const derive = (botStatus) => {
    const props = buildAccountRuntimeProps(botStatus);
    const derived = deriveAccountRuntime(props);
    const liveContext = deriveLiveContext(props, derived);
    return { props, derived, liveContext };
};

let buildAccountRuntimeProps;
let deriveAccountRuntime;
let deriveLiveContext;
let deriveFinancialMetrics;
let displayRuntimeValue;
let isAvailable;

test.before(async () => {
    const module = await loadModule();
    ({ buildAccountRuntimeProps, deriveAccountRuntime, deriveLiveContext, deriveFinancialMetrics, displayRuntimeValue, isAvailable } = module);
});

test("nested realAccount is authoritative over flattened compatibility fields", async () => {
    const { derived } = derive(makeStatus({
        // flattened legacy values should never win over a valid nested value
        realBalance: 99999,
        realEquity: 99999,
        realAvailableBalance: 99999,
        realPositionState: "NOT_SYNCED",
        realAccountConnected: true,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                apiKeyPresent: true,
                permission: "READ_ONLY",
                balance: 1500,
                equity: 1500,
                availableBalance: 1200,
                positions: [],
                positionSummary: "FLAT",
                lastSync: Date.now() / 1000,
            },
        },
    }));

    assert.equal(derived.realBalanceValue, "1,500.00");
    assert.equal(derived.realEquityValue, "1,500.00");
    assert.equal(derived.realAvailableValue, "1,200.00");
    assert.equal(derived.realPositionValue, "FLAT");
    assert.equal(derived.resolvedPermission, "READ_ONLY");
});

test("UNKNOWN permission, account type and auth never upgrade to READY / VERIFIED", async () => {
    const { derived, liveContext } = derive(makeStatus({
        permission: "UNKNOWN",
        accountType: "UNKNOWN",
        exchangeAuth: "UNKNOWN",
        exchangeConnection: "UNKNOWN",
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                permission: "UNKNOWN",
                accountType: "UNKNOWN",
                balance: null,
                lastSync: null,
            },
        },
    }));

    assert.equal(derived.resolvedPermission, "UNKNOWN");
    assert.equal(derived.resolvedAccountType, "UNKNOWN");
    // UNKNOWN auth stays UNKNOWN — the model never upgrades it to VERIFIED or READY
    assert.equal(derived.resolvedExchangeAuth, "UNKNOWN");
    // no fabricated numeric balance is exposed
    assert.notEqual(derived.realBalanceValue, "0.00");
    assert.equal(derived.realBalanceValue, "NOT_CONNECTED");
    assert.equal(liveContext.dataFreshness, "NOT_FETCHED");
    assert.equal(liveContext.currentContext, "PAPER MODE — LIVE ACCOUNT INACTIVE");
    assert.equal(derived.resolvedExchangeConnection, "NOT_CONNECTED");
});

test("UNAVAILABLE account reason fails closed instead of exposing a fabricated balance", async () => {
    const { derived } = derive(makeStatus({
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                accountReason: "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
                balanceReason: "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
                positionReason: "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
            },
        },
    }));

    assert.equal(derived.realBalanceValue, "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE");
    assert.equal(derived.realEquityValue, "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE");
    assert.equal(derived.realAvailableValue, "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE");
    assert.equal(derived.realPositionValue, "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE");
});

test("STALE canonical state stays STALE and never surfaces a numeric balance", async () => {
    const { derived, liveContext } = derive(makeStatus({
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                permission: "READ_ONLY",
                balance: 1500,
                lastSync: Date.now() / 1000 - 3600,
                stale: true,
            },
        },
    }));

    assert.equal(derived.realStale, true);
    assert.equal(derived.realSyncStatus, "STALE");
    assert.equal(derived.realBalanceValue, "STALE");
    assert.equal(liveContext.dataFreshness, "STALE");
});

test("NOT_FETCHED is distinct from FRESH when no sync has occurred", async () => {
    const { derived, liveContext } = derive(makeStatus());
    assert.equal(derived.realConnected, false);
    assert.equal(derived.realSyncStatus, "NOT_CONNECTED");
    assert.equal(derived.realBalanceValue, "NOT_CONNECTED");
    assert.equal(liveContext.dataFreshness, "NOT_FETCHED");
    assert.notEqual(liveContext.dataFreshness, "FRESH");
});

test("FRESH requires an available sync timestamp, not mere connection", async () => {
    const { liveContext } = derive(makeStatus({
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                permission: "READ_ONLY",
                balance: 1500,
            },
        },
    }));
    assert.equal(liveContext.dataFreshness, "NOT_FETCHED");
});

test("READ_ONLY is preserved as a status and does not imply LIVE execution", async () => {
    const { derived, liveContext } = derive(makeStatus({
        selectedMode: "LIVE",
        executionMode: "LIVE",
        realOrderAllowed: false,
        realAccountConnected: true,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                apiKeyPresent: true,
                permission: "READ_ONLY",
                balance: 1500,
                lastSync: Date.now() / 1000,
            },
            execution: { selectedMode: "LIVE", executionMode: "LIVE", realOrderAllowed: false },
        },
    }));

    assert.equal(derived.resolvedPermission, "READ_ONLY");
    assert.equal(derived.resolvedExchangeConnection, "CONNECTED");
    assert.equal(liveContext.accountAccess, "READ_ONLY");
    assert.equal(liveContext.liveExecution, "NOT ALLOWED");
    assert.equal(liveContext.currentContext, "LIVE MODE — REAL EXECUTION NOT ALLOWED");
});

test("PAPER mode keeps the Real Account visible and surfaces the inactive context", async () => {
    const { derived, liveContext } = derive(makeStatus({
        selectedMode: "PAPER",
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                permission: "READ_ONLY",
                connected: false,
            },
        },
    }));

    assert.equal(derived.paperMode, true);
    // Real Account canonical fields remain populated (observability preserved)
    assert.equal(derived.realAccount.permission, "READ_ONLY");
    assert.equal(liveContext.currentContext, "PAPER MODE — LIVE ACCOUNT INACTIVE");
    assert.equal(liveContext.paperModeContext, true);
});

test("execution authority is derived display only, never fed by connection or auth", async () => {
    // connected + read-only but realOrderAllowed false -> execution NOT ALLOWED
    const paper = derive(makeStatus({
        selectedMode: "LIVE",
        realOrderAllowed: false,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                permission: "READ_ONLY",
                lastSync: Date.now() / 1000,
            },
        },
    }));
    assert.equal(paper.liveContext.liveExecution, "NOT ALLOWED");

    // realOrderAllowed true + LIVE executionMode -> only then ALLOWED
    const live = derive(makeStatus({
        selectedMode: "LIVE",
        executionMode: "LIVE",
        realOrderAllowed: true,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                permission: "READ_ONLY",
                lastSync: Date.now() / 1000,
            },
            execution: { selectedMode: "LIVE", executionMode: "LIVE", realOrderAllowed: true },
        },
    }));
    assert.equal(live.liveContext.liveExecution, "ALLOWED");
});

test("firstAvailable and isAvailable reject empty sentinels but keep explicit strings", async () => {
    assert.equal(isAvailable("UNKNOWN"), false);
    assert.equal(isAvailable("UNAVAILABLE"), true);
    assert.equal(isAvailable("READ_ONLY"), true);
    assert.equal(isAvailable(null), false);
    assert.equal(isAvailable(0), true);
    assert.equal(isAvailable(""), false);
});

test("displayRuntimeValue refuses to invent a value for missing numeric state", async () => {
    assert.equal(displayRuntimeValue(null, { formatter: (v) => String(v) }), "NOT FETCHED");
    assert.equal(displayRuntimeValue(null, { loading: true }), "REFRESHING");
    assert.equal(displayRuntimeValue(null, { stale: true }), "STALE");
});

test("Dashboard and Account Status resolve identical canonical values from one snapshot", async () => {
    const status = makeStatus({
        realAccountConnected: true,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                apiKeyPresent: true,
                permission: "READ_ONLY",
                balance: 1500,
                equity: 1500,
                availableBalance: 1200,
                positions: [],
                positionSummary: "FLAT",
                lastSync: Date.now() / 1000,
            },
            connection: { connected: true, authenticated: true, apiKeyStatus: "VERIFIED", permission: "READ_ONLY" },
        },
    });

    // Account Status page path
    const pageDerived = deriveAccountRuntime(buildAccountRuntimeProps(status));

    // Dashboard path mirrors the same canonical field mapping into the same shared model
    const dashboardProps = {
        accountRuntime: status.accountRuntime,
        exchange: status.exchange,
        selectedMode: status.selectedMode,
        executionMode: status.executionMode,
        realOrderAllowed: status.realOrderAllowed === true,
        dryRun: status.dryRun !== false,
        accountSource: status.accountSource,
        balanceSource: status.balanceSource,
        positionSource: status.positionSource,
        exchangeAuth: status.exchangeAuth,
        exchangeConnection: status.exchangeConnection,
        apiKeyStatus: status.apiKeyStatus,
        permission: status.permission,
        accountType: status.accountType,
        realAccountConnected: status.realAccountConnected === true,
        realBalance: status.realBalance,
        realEquity: status.realEquity,
        realAvailableBalance: status.realAvailableBalance,
        realPosition: status.realPosition,
        realPositionState: status.realPositionState,
        balance: status.balance,
        equity: status.equity,
        availableBalance: status.availableBalance,
        pnl: status.pnl,
    };
    const dashboardDerived = deriveAccountRuntime(dashboardProps);

    const canonicalKeys = [
        "realBalanceValue",
        "realEquityValue",
        "realAvailableValue",
        "realPositionValue",
        "resolvedExchangeConnection",
        "resolvedExchangeAuth",
        "resolvedApiKeyStatus",
        "resolvedPermission",
        "realConnected",
        "realSyncStatus",
        "paperBalance",
        "paperEquity",
        "paperAvailableBalance",
        "paperPosition",
        "paperPnl",
        "paperMode",
    ];
    canonicalKeys.forEach((key) => {
        assert.equal(dashboardDerived[key], pageDerived[key], `canonical value must match for ${key}`);
    });
});

test("financial metrics preserve the authoritative 3x3 priority order", async () => {
    const { derived } = derive(makeStatus());
    const metrics = deriveFinancialMetrics(derived);
    assert.deepEqual(
        metrics.map((metric) => metric.key),
        [
            "equity", "availableBalance", "walletBalance", "unrealizedPnl",
            "realizedPnlToday", "totalPnlToday", "marginUsed", "marginAvailable", "marginRatio",
        ],
    );
    assert.equal(metrics.length, 9);
    // Asset row -> PnL row -> Margin row (desktop 3x3)
    assert.deepEqual(metrics.slice(0, 3).map((m) => m.category), ["asset", "asset", "asset"]);
    assert.deepEqual(metrics.slice(3, 6).map((m) => m.category), ["pnl", "pnl", "pnl"]);
    assert.deepEqual(metrics.slice(6, 9).map((m) => m.category), ["margin", "margin", "margin"]);
});

test("financial metrics surface authoritative Equity / Available and never fabricate zeros", async () => {
    const connected = makeStatus({
        realAccountConnected: true,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                apiKeyPresent: true,
                permission: "READ_ONLY",
                balance: 1500,
                equity: 1500,
                availableBalance: 1200,
                unrealizedPnl: 12.5,
                positions: [],
                positionSummary: "FLAT",
                lastSync: Date.now() / 1000,
            },
        },
    });
    const { derived } = derive(connected);
    const metrics = deriveFinancialMetrics(derived);
    const byKey = Object.fromEntries(metrics.map((m) => [m.key, m]));

    assert.equal(byKey.equity.value, "1,500.00");
    assert.equal(byKey.equity.unit, "USDT");
    assert.equal(byKey.equity.state, null);
    assert.equal(byKey.availableBalance.value, "1,200.00");
    assert.equal(byKey.availableBalance.unit, "USDT");
    assert.equal(byKey.unrealizedPnl.value, "+12.50");
    assert.equal(byKey.unrealizedPnl.unit, "USDT");
    assert.equal(byKey.unrealizedPnl.tone, "positive");

    // walletBalance aliases equity -> classified ambiguous -> UNAVAILABLE (no duplicate zero)
    assert.equal(byKey.walletBalance.state, "UNAVAILABLE");
    assert.equal(byKey.walletBalance.value, null);
    // No authoritative source for the remaining metrics -> UNAVAILABLE
    ["realizedPnlToday", "totalPnlToday", "marginUsed", "marginAvailable", "marginRatio"]
        .forEach((key) => {
            assert.equal(byKey[key].state, "UNAVAILABLE", `${key} should be UNAVAILABLE`);
            assert.equal(byKey[key].value, null, `${key} must not be fabricated`);
        });
});

test("financial metrics never turn an unavailable account into zeros", async () => {
    const { derived } = derive(makeStatus()); // real account not connected
    const metrics = deriveFinancialMetrics(derived);
    metrics.forEach((metric) => {
        assert.equal(metric.state, "UNAVAILABLE", `${metric.key} unavailable`);
        assert.equal(metric.value, null, `${metric.key} value must be null, not 0`);
    });
});

test("financial PnL tone follows the sign and treats zero as neutral", async () => {
    const positive = deriveFinancialMetrics(derive(makeStatus({
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED, connected: true, authenticated: true,
                equity: 1500, availableBalance: 1200, balance: 1500, unrealizedPnl: 5,
                positions: [], positionSummary: "FLAT", lastSync: 1,
            },
        },
    })).derived);
    assert.equal(positive.find((m) => m.key === "unrealizedPnl").tone, "positive");

    const zero = deriveFinancialMetrics(derive(makeStatus({
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED, connected: true, authenticated: true,
                equity: 1500, availableBalance: 1200, balance: 1500, unrealizedPnl: 0,
                positions: [], positionSummary: "FLAT", lastSync: 1,
            },
        },
    })).derived);
    assert.equal(zero.find((m) => m.key === "unrealizedPnl").tone, "neutral");
});
