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
let derivePositionCards;
let initialAccountView;
let resolveAccountView;
let displayRuntimeValue;
let isAvailable;

test.before(async () => {
    const module = await loadModule();
    ({
        buildAccountRuntimeProps,
        deriveAccountRuntime,
        deriveLiveContext,
        deriveFinancialMetrics,
        derivePositionCards,
        initialAccountView,
        resolveAccountView,
        displayRuntimeValue,
        isAvailable,
    } = module);
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
                walletBalance: 1487.5,
                unrealizedPnl: 12.5,
                realizedPnlToday: 3,
                totalPnlToday: 15.5,
                marginRatio: 5,
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

    assert.equal(byKey.walletBalance.value, "1,487.50");
    assert.equal(byKey.walletBalance.unit, "USDT");
    assert.equal(byKey.realizedPnlToday.value, "+3.00");
    assert.equal(byKey.realizedPnlToday.tone, "positive");
    assert.equal(byKey.totalPnlToday.value, "+15.50");
    assert.equal(byKey.marginRatio.value, "5.00");
    assert.equal(byKey.marginRatio.unit, "%");
    ["marginUsed", "marginAvailable"]
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

test("position projections preserve null, zero, units and canonical authority", async () => {
    const m = await loadModule();
    assert.equal(m.positionNumber(null), "—");
    for (const v of [undefined, NaN, Infinity, true, "0"]) assert.equal(m.positionNumber(v), "—");
    assert.equal(m.positionNumber(0, true), "0.00");
    assert.equal(m.positionNumber(-1.5, true), "-1.50");
    assert.equal(m.positionQuantity({quantity:12,quantityUnit:"contract"}), "12 contracts");
    assert.equal(m.positionQuantity({quantity:6174,quantityUnit:"coin"}), "6,174 coin");
    assert.equal(m.positionQuantity({quantity:12}), "12 UNIT UNKNOWN");
    for (const [ms, expected] of [[643,"643 ms"],[12400,"12.4 sec"],[133000,"2m 13s"],[3840000,"1h 04m"],[null,"—"],[0,"0 ms"]]) assert.equal(m.positionHolding(ms), expected);
    assert.equal(m.positionTime(0), "1970-01-01 00:00:00 UTC");
    assert.equal(m.positionTime(null), "—");
    const currentPosition = {status:"UNKNOWN",quantity:null};
    const lastPositionEvent = {event:"CLOSED",realizedPnl:0};
    assert.deepEqual(m.derivePositionCards({currentPosition,lastPositionEvent,paperAccount:{position:{side:"BUY"}}}), {currentPosition,lastPositionEvent});
    assert.deepEqual(m.derivePositionCards(), {currentPosition:{},lastPositionEvent:{}});
});

/* =================================================
   C-P6-3 ACCOUNT VIEW — display-only selection
================================================= */

test("initialAccountView follows selectedMode and safely defaults to PAPER", async () => {
    assert.equal(initialAccountView("LIVE"), "LIVE");
    assert.equal(initialAccountView("live"), "LIVE");
    assert.equal(initialAccountView("PAPER"), "PAPER");
    assert.equal(initialAccountView(undefined), "PAPER");
    assert.equal(initialAccountView(null), "PAPER");
    assert.equal(initialAccountView(""), "PAPER");
    assert.equal(initialAccountView("BOGUS"), "PAPER");
});

test("resolveAccountView preserves a manual selection over later selectedMode changes", async () => {
    // A manual choice always wins, so polling cannot force the view back.
    assert.equal(resolveAccountView("LIVE", "PAPER"), "PAPER");
    assert.equal(resolveAccountView("PAPER", "LIVE"), "LIVE");
    assert.equal(resolveAccountView("LIVE", null), "LIVE");
    assert.equal(resolveAccountView("PAPER", undefined), "PAPER");
    assert.equal(resolveAccountView("PAPER", "BOGUS"), "PAPER");
});

test("derivePositionCards selects the requested view from dual projections", async () => {
    const paper = { status: "OPEN", mode: "PAPER", symbol: "PAPERONLY" };
    const live = { status: "OPEN", mode: "LIVE", symbol: "REALONLY" };
    const paperEvent = { event: "CLOSED", mode: "PAPER", symbol: "PAPEREVENT" };
    const liveEvent = { event: "CLOSED", mode: "LIVE", symbol: "REALEVENT" };
    const runtime = {
        positionsByMode: { PAPER: paper, LIVE: live },
        lastPositionEventsByMode: { PAPER: paperEvent, LIVE: liveEvent },
        // legacy values must be ignored once dual projections exist
        currentPosition: { mode: "PAPER", symbol: "LEGACY" },
        lastPositionEvent: { mode: "LIVE", symbol: "LEGACY_EVENT" },
    };
    assert.deepEqual(derivePositionCards(runtime, "PAPER"), {
        currentPosition: paper,
        lastPositionEvent: paperEvent,
    });
    assert.deepEqual(derivePositionCards(runtime, "LIVE"), {
        currentPosition: live,
        lastPositionEvent: liveEvent,
    });
});

test("derivePositionCards never cross-falls back when the requested view key is absent", async () => {
    const runtime = {
        positionsByMode: { PAPER: { status: "FLAT", mode: "PAPER" } },
        lastPositionEventsByMode: { PAPER: { event: "NONE", mode: "PAPER" } },
        currentPosition: { status: "OPEN", mode: "LIVE", symbol: "LEGACY_LIVE" },
        lastPositionEvent: { event: "CLOSED", mode: "LIVE", symbol: "LEGACY_LIVE_EVENT" },
    };
    const live = derivePositionCards(runtime, "LIVE");
    assert.deepEqual(live, { currentPosition: {}, lastPositionEvent: {} });
});

test("derivePositionCards legacy fallback is mode-scoped and view-less calls stay compatible", async () => {
    const runtime = {
        currentPosition: { mode: "PAPER", symbol: "PAPER_LEGACY" },
        lastPositionEvent: { mode: "LIVE", symbol: "LIVE_LEGACY" },
    };
    // With no dual projections, a matching legacy mode is allowed.
    assert.deepEqual(derivePositionCards(runtime, "PAPER").currentPosition, runtime.currentPosition);
    assert.deepEqual(derivePositionCards(runtime, "LIVE").lastPositionEvent, runtime.lastPositionEvent);
    // Mismatched legacy data never crosses the requested view boundary.
    assert.deepEqual(derivePositionCards(runtime, "LIVE").currentPosition, {});
    assert.deepEqual(derivePositionCards(runtime, "PAPER").lastPositionEvent, {});
    // No view keeps the historical behavior untouched.
    assert.deepEqual(derivePositionCards(runtime), {
        currentPosition: runtime.currentPosition,
        lastPositionEvent: runtime.lastPositionEvent,
    });
});

test("deriveFinancialMetrics dispatches PAPER vs LIVE with no cross-account values", async () => {
    const connected = makeStatus({
        realAccountConnected: true,
        accountRuntime: {
            ...makeStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                connected: true,
                authenticated: true,
                permission: "READ_ONLY",
                equity: 7.92,
                availableBalance: 5.42,
                balance: 7.92,
                walletBalance: 7.92,
                unrealizedPnl: 1.23,
                realizedPnlToday: 0.5,
                totalPnlToday: 1.73,
                marginUsed: 0,
                marginAvailable: 7.92,
                marginRatio: 5,
                lastSync: Date.now() / 1000,
            },
            paperAccount: {
                balance: 10000,
                equity: 10000,
                availableBalance: 9800,
                positions: [],
                totalPnl: 42,
                realizedPnl: 42,
                unrealizedPnl: 0,
                available: true,
                source: "PAPER_SIMULATION",
            },
        },
    });
    const { derived } = derive(connected);

    const paper = Object.fromEntries(
        deriveFinancialMetrics(derived, "PAPER").map((m) => [m.key, m]),
    );
    const live = Object.fromEntries(
        deriveFinancialMetrics(derived, "LIVE").map((m) => [m.key, m]),
    );

    assert.equal(paper.equity.value, "10,000.00");
    assert.equal(paper.availableBalance.value, "9,800.00");
    assert.equal(paper.walletBalance.value, "10,000.00");
    assert.equal(paper.walletBalance.label, "BALANCE");
    assert.equal(paper.unrealizedPnl.value, "0.00");
    assert.equal(paper.realizedPnlToday.value, "+42.00");
    assert.equal(paper.totalPnlToday.value, "+42.00");
    ["marginUsed", "marginAvailable", "marginRatio"].forEach((key) => {
        assert.equal(paper[key].state, "UNAVAILABLE", `paper ${key}`);
        assert.equal(paper[key].value, null, `paper ${key} must not be fabricated`);
    });

    assert.equal(live.equity.value, "7.92");
    assert.equal(live.availableBalance.value, "5.42");
    assert.equal(live.walletBalance.value, "7.92");
    assert.equal(live.marginRatio.value, "5.00");

    // No PAPER value leaks into REAL and vice versa.
    assert.notEqual(live.equity.value, paper.equity.value);
    // The default dispatch remains the REAL projection for existing consumers.
    assert.deepEqual(
        deriveFinancialMetrics(derived).map((m) => m.value),
        deriveFinancialMetrics(derived, "LIVE").map((m) => m.value),
    );
});

test("deriveFinancialMetrics PAPER never fabricates zeros for missing fields", async () => {
    const { derived } = derive(makeStatus({
        accountRuntime: {
            ...makeStatus().accountRuntime,
            paperAccount: {
                balance: 1000,
                equity: 1000,
                availableBalance: 980,
                positions: [],
                totalPnl: 0,
                available: true,
                source: "PAPER_SIMULATION",
                // realizedPnl / unrealizedPnl intentionally missing
            },
        },
    }));
    const paper = Object.fromEntries(
        deriveFinancialMetrics(derived, "PAPER").map((m) => [m.key, m]),
    );
    ["unrealizedPnl", "realizedPnlToday"].forEach((key) => {
        assert.equal(paper[key].state, "UNAVAILABLE", `paper ${key}`);
        assert.equal(paper[key].value, null, `paper ${key} must not be zero`);
    });
    // Authoritative zero (totalPnl) is still a valid value.
    assert.equal(paper.totalPnlToday.value, "0.00");
    assert.equal(paper.totalPnlToday.tone, "neutral");
});
