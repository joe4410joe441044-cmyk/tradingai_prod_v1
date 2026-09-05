import { API } from "../../api/index.js";

/* =================================================
   Canonical /api/bot/status account consumer
   Shared by Dashboard (AccountRuntimeOverview) and
   the independent AccountStatusPage.

   The backend remains the single canonical account
   source (GET /api/bot/status). This module only maps
   canonical values to deterministic presentation
   values. It never infers runtime authority and never
   creates a second account source.
================================================= */

export const fetchBotStatus = async () => {
    const response = await fetch(API.botStatus());

    if (!response.ok) {
        throw new Error(`Bot status request failed: ${response.status}`);
    }

    return {
        data: await response.json(),
        receivedAt: Date.now(),
    };
};

export const firstAvailable = (...values) => (
    values.find((value) => (
        value !== null
        && value !== undefined
        && value !== ""
        && !(typeof value === "number" && !Number.isFinite(value))
    ))
);

export const getPositionSide = (position) => {
    const candidate = Array.isArray(position)
        ? position[0]
        : position;

    if (!candidate) {
        return undefined;
    }

    if (typeof candidate !== "object") {
        return candidate;
    }

    return firstAvailable(
        candidate.side,
        candidate.position_side,
        candidate.state,
    );
};

export const normalizeTimestamp = (value) => {
    if (value === null || value === undefined || value === "") {
        return undefined;
    }

    const numericValue = Number(value);

    if (Number.isFinite(numericValue)) {
        return numericValue < 1_000_000_000_000
            ? numericValue * 1000
            : numericValue;
    }

    return value;
};

const EMPTY_VALUES = new Set([
    "UNKNOWN",
    "NO DATA",
    "NONE",
    "UNDEFINED",
    "NAN",
]);

export const isAvailable = (value) => {
    if (value === null || value === undefined || value === "") {
        return false;
    }

    if (typeof value === "number" && !Number.isFinite(value)) {
        return false;
    }

    return !EMPTY_VALUES.has(String(value).trim().toUpperCase());
};

export const displayValue = (value, formatter) => {
    if (!isAvailable(value)) {
        return "--";
    }

    return formatter ? formatter(value) : String(value);
};

export const displayRuntimeValue = (
    value,
    {
        formatter,
        loading = false,
        stale = false,
        emptyLabel = "NOT FETCHED",
    } = {},
) => {
    if (loading) {
        return "REFRESHING";
    }

    if (stale) {
        return "STALE";
    }

    if (Array.isArray(value) && value.length === 0) {
        return "NO OPEN POSITION";
    }

    if (!isAvailable(value)) {
        return emptyLabel;
    }

    return formatter ? formatter(value) : String(value);
};

export const formatAmount = (value) => {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return "--";
    }

    return numericValue.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
};

export const formatPnl = (value) => {
    const numericValue = Number(value);

    if (!Number.isFinite(numericValue)) {
        return "--";
    }

    return `${numericValue > 0 ? "+" : ""}${numericValue.toFixed(2)}`;
};

export const formatLastUpdate = (value) => {
    const numericValue = Number(value);
    const date = new Date(
        Number.isFinite(numericValue) && numericValue < 1000000000000
            ? numericValue * 1000
            : value,
    );

    if (Number.isNaN(date.getTime())) {
        return "--";
    }

    return date.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
    });
};

export const formatPositionValue = (
    value,
    state,
    {
        loading = false,
        stale = false,
        emptyLabel = "NOT FETCHED",
    } = {},
) => {
    if (loading) {
        return "REFRESHING";
    }

    if (stale) {
        return "STALE";
    }

    if (Array.isArray(value)) {
        if (value.length === 0) {
            return "FLAT";
        }

        return formatPositionValue(value[0], state);
    }

    if (value && typeof value === "object") {
        const symbol = value.symbol ?? value.pair ?? "--";
        const side = value.side ?? value.position_side ?? value.state ?? "--";
        const qty = value.qty ?? value.size ?? value.coin_qty;

        return qty !== null && qty !== undefined && qty !== ""
            ? `${symbol} ${side} ${qty}`
            : `${symbol} ${side}`;
    }

    if (isAvailable(value)) {
        return String(value);
    }

    if (state === "NO_OPEN_POSITION" || state === "FLAT") {
        return "FLAT";
    }

    return displayRuntimeValue(state, { emptyLabel });
};

/* =================================================
   deriveAccountRuntime
   Maps the canonical account snapshot into resolved
   display values used by both the Dashboard summary
   and the independent Account Status page.
================================================= */
export const deriveAccountRuntime = (props) => {
    const {
        accountRuntime,
        exchange,
        selectedMode,
        realOrderAllowed,
        safetyReason,
        exchangeAuth,
        exchangeConnection,
        apiKeyStatus,
        permission,
        accountType,
        exchangeAuthReason,
        exchangeConnectionReason,
        accountReason,
        balanceReason,
        positionReason,
        realAccountConnected,
        realBalance,
        realEquity,
        realAvailableBalance,
        realPosition,
        realPositionState,
        realAccountLastSync,
        realLastSync,
        balance,
        equity,
        availableBalance,
        position,
        pnl,
        lastUpdate,
    } = props || {};

    const runtime = accountRuntime && typeof accountRuntime === "object"
        ? accountRuntime
        : {};
    const paperAccount = runtime.paperAccount || {};
    const realAccount = runtime.realAccount || {};
    const connection = runtime.connection || {};
    const hasAccountRuntime = Boolean(runtime.paperAccount || runtime.realAccount);
    const paperAvailable = hasAccountRuntime
        ? paperAccount.available !== false
        : true;
    const paperBalance = paperAvailable
        ? paperAccount.balance ?? balance
        : null;
    const paperEquity = paperAvailable
        ? paperAccount.equity ?? equity
        : null;
    const paperAvailableBalance = paperAvailable
        ? paperAccount.availableBalance ?? availableBalance
        : null;
    const paperPosition = paperAvailable
        ? paperAccount.positions ?? paperAccount.position ?? position
        : null;
    const paperPnl = paperAvailable
        ? paperAccount.totalPnl ?? pnl
        : null;

    const selectedExchange = String(exchange ?? "").trim().toUpperCase();
    const realExchange = String(realAccount.exchange ?? "").trim().toUpperCase();
    const realExchangeMatches = !realExchange || realExchange === selectedExchange;
    const realLoading = realExchangeMatches && realAccount.loading === true;
    const realStale = realExchangeMatches && realAccount.stale === true;
    const realAuthenticated = realExchangeMatches
        && (
            realAccount.authenticated === true
            || Boolean(realAccount.balanceSource)
            || Boolean(realAccount.positionSource)
        );
    const resolvedExchangeAuth = realAuthenticated
        ? "VERIFIED"
        : exchangeAuth;
    const resolvedExchangeConnection = realExchangeMatches
        ? connection.apiKeyStatus
            ? realAccount.connected === true
                ? "CONNECTED"
                : "NOT_CONNECTED"
            : exchangeConnection
        : "NOT_CONNECTED";
    const resolvedApiKeyStatus = connection.apiKeyStatus || apiKeyStatus;
    const resolvedPermission = realAccount.permission || permission;
    const resolvedAccountType = realAccount.accountType || accountType;
    const resolvedAuthReason = realAccount.authReason || exchangeAuthReason;
    const resolvedConnectionReason = realExchangeMatches
        ? realAccount.connectionReason || exchangeConnectionReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const resolvedAccountReason = realExchangeMatches
        ? realAccount.accountReason || accountReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const resolvedBalanceReason = realExchangeMatches
        ? realAccount.balanceReason || balanceReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const resolvedPositionReason = realExchangeMatches
        ? realAccount.positionReason || positionReason
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const realPositions = realExchangeMatches
        ? realAccount.positions ?? realPosition
        : null;
    const realBalanceRaw = realExchangeMatches
        ? realAccount.balance ?? realBalance
        : null;
    const realEquityRaw = realExchangeMatches
        ? realAccount.equity ?? realEquity
        : null;
    const realAvailableRaw = realExchangeMatches
        ? realAccount.availableBalance ?? realAvailableBalance
        : null;
    const realPositionSummary = realExchangeMatches
        ? realAccount.positionSummary ?? realPositionState
        : "ACCOUNT_EXCHANGE_MISMATCH";
    const realConnected = realExchangeMatches
        && (
            realAccountConnected
            || realAuthenticated
            || realAccount.connected === true
        );
    const realAvailablePresetEnabled = realConnected
        && !realLoading
        && !realStale
        && Number.isFinite(Number(realAvailableRaw));
    const normalizedSelectedMode = String(selectedMode ?? "PAPER").toUpperCase();
    const paperMode = normalizedSelectedMode === "PAPER";
    const realSyncStatus = realLoading
        ? "REFRESHING"
        : realStale
            ? "STALE"
            : realConnected
                ? "CONNECTED"
                : "NOT_CONNECTED";
    const normalizedAuth = String(resolvedExchangeAuth ?? "NOT_VERIFIED").toUpperCase();
    const authVerified = normalizedAuth === "VERIFIED";
    const accountLastSync = realAccount.lastSync
        ?? realLastSync
        ?? realAccountLastSync
        ?? lastUpdate;
    const realUnavailable = displayValue(
        resolvedAccountReason
        || resolvedBalanceReason
        || "NOT_CONNECTED",
    );
    const realBalanceValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realBalanceRaw, {
            formatter: formatAmount,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
    const realEquityValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realEquityRaw, {
            formatter: formatAmount,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
    const realAvailableValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realAvailableRaw, {
            formatter: formatAmount,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
    const realPositionValue = realConnected || realLoading || realStale
        ? formatPositionValue(realPositions, realPositionSummary, {
            loading: realLoading,
            stale: realStale,
        })
        : displayValue(resolvedPositionReason || resolvedAccountReason || "NOT_CONNECTED");
    const displayedReason = normalizedSelectedMode === "LIVE" && !realOrderAllowed
        && !String(safetyReason ?? "").includes("LIVE_NOT_ENABLED")
        ? "LIVE_NOT_ENABLED / DRY_RUN_ACTIVE"
        : displayValue(safetyReason);

    return {
        runtime,
        paperAccount,
        realAccount,
        connection,
        hasAccountRuntime,
        paperAvailable,
        paperBalance,
        paperEquity,
        paperAvailableBalance,
        paperPosition,
        paperPnl,
        selectedExchange,
        realExchange,
        realExchangeMatches,
        realLoading,
        realStale,
        realAuthenticated,
        resolvedExchangeAuth,
        resolvedExchangeConnection,
        resolvedApiKeyStatus,
        resolvedPermission,
        resolvedAccountType,
        resolvedAuthReason,
        resolvedConnectionReason,
        resolvedAccountReason,
        resolvedBalanceReason,
        resolvedPositionReason,
        realPositions,
        realBalanceRaw,
        realEquityRaw,
        realAvailableRaw,
        realPositionSummary,
        realConnected,
        realAvailablePresetEnabled,
        normalizedSelectedMode,
        paperMode,
        realSyncStatus,
        normalizedAuth,
        authVerified,
        accountLastSync,
        realUnavailable,
        realBalanceValue,
        realEquityValue,
        realAvailableValue,
        realPositionValue,
        displayedReason,
    };
};

/* =================================================
   deriveLiveContext
   Deterministic, read-only presentation of the
   relationship between runtime mode, account access,
   LIVE execution authority and data freshness.

   This is NOT a readiness engine.
================================================= */
export const deriveLiveContext = (props, derived = deriveAccountRuntime(props)) => {
    const {
        realOrderAllowed,
        executionMode,
    } = props || {};

    const {
        normalizedSelectedMode,
        resolvedPermission,
        resolvedExchangeConnection,
        accountLastSync,
        realStale,
        realLoading,
        realConnected,
    } = derived;

    const currentMode = normalizedSelectedMode;

    const accountAccess = isAvailable(resolvedPermission)
        ? resolvedPermission
        : resolvedExchangeConnection;

    const liveExecution = (
        realOrderAllowed === true
        && String(executionMode ?? "SIMULATION").toUpperCase() === "LIVE"
    ) ? "ALLOWED" : "NOT ALLOWED";

    const freshnessSource = (() => {
        if (realStale) {
            return "STALE";
        }
        if (realLoading) {
            return "REFRESHING";
        }
        if (
            realConnected
            && isAvailable(accountLastSync)
        ) {
            return "FRESH";
        }
        return "NOT_FETCHED";
    })();

    const currentContext = currentMode === "PAPER"
        ? "PAPER MODE — LIVE ACCOUNT INACTIVE"
        : currentMode === "LIVE"
            ? liveExecution === "ALLOWED"
                ? "LIVE MODE — REAL ACCOUNT ACTIVE"
                : "LIVE MODE — REAL EXECUTION NOT ALLOWED"
            : "RUNTIME MODE UNKNOWN";

    return {
        currentMode,
        accountAccess,
        liveExecution,
        dataFreshness: freshnessSource,
        currentContext,
        paperModeContext: currentMode === "PAPER",
    };
};

/* =================================================
   buildAccountRuntimeProps
   Coalesces the canonical /api/bot/status snapshot
   into the props expected by AccountRuntimeOverview
   and the AccountStatusPage. Optional tradeSettings
   / governance can be merged to mirror the Dashboard
   default resolution, but they are not required.
================================================= */
export const buildAccountRuntimeProps = (botStatus, extra = {}) => {
    const snapshot = botStatus || {};
    const {
        tradeSettings = {},
        governance = {},
        position: externalPosition,
        wsMarketData,
    } = extra;

    const position = externalPosition ?? firstAvailable(
        getPositionSide(snapshot.actual_position),
        getPositionSide(snapshot.position),
        getPositionSide(wsMarketData?.position),
    );

    const lastUpdate = normalizeTimestamp(firstAvailable(
        snapshot.last_update,
        snapshot.timestamp,
    ));

    return {
        accountRuntime: snapshot.accountRuntime,
        exchange: firstAvailable(
            snapshot.exchange,
            tradeSettings.exchange,
        ),
        selectedMode: firstAvailable(
            tradeSettings.mode,
            snapshot.selectedMode,
            governance?.mode,
        ),
        executionMode: firstAvailable(
            snapshot.executionMode,
            snapshot.execution_mode,
            "SIMULATION",
        ),
        realOrderAllowed: firstAvailable(
            snapshot.realOrderAllowed,
            snapshot.real_order_allowed,
            false,
        ) === true,
        dryRun: firstAvailable(
            snapshot.dryRun,
            true,
        ) !== false,
        safetyReason: snapshot.safetyReason,
        allowLive: snapshot.allowLive,
        tradeMode: snapshot.tradeMode,
        accountSource: firstAvailable(
            snapshot.accountSource,
            "NOT_CONNECTED",
        ),
        balanceSource: firstAvailable(
            snapshot.balanceSource,
            "NOT_CONNECTED",
        ),
        positionSource: firstAvailable(
            snapshot.positionSource,
            "NOT_CONNECTED",
        ),
        exchangeAuth: firstAvailable(
            snapshot.exchangeAuth,
            "NOT_VERIFIED",
        ),
        exchangeConnection: firstAvailable(
            snapshot.exchangeConnection,
            "NOT_CONNECTED",
        ),
        apiKeyStatus: firstAvailable(
            snapshot.apiKeyStatus,
            "MISSING",
        ),
        permission: firstAvailable(
            snapshot.permission,
            "NOT_VERIFIED",
        ),
        accountType: firstAvailable(
            snapshot.accountType,
            "UNKNOWN",
        ),
        exchangeAuthReason: snapshot.exchangeAuthReason,
        exchangeConnectionReason: snapshot.exchangeConnectionReason,
        accountReason: snapshot.accountReason,
        balanceReason: snapshot.balanceReason,
        positionReason: snapshot.positionReason,
        accountSourceReason: snapshot.accountSourceReason,
        balanceSourceReason: snapshot.balanceSourceReason,
        positionSourceReason: snapshot.positionSourceReason,
        realAccountConnected: snapshot.realAccountConnected === true,
        realBalance: snapshot.realBalance,
        realEquity: snapshot.realEquity,
        realAvailableBalance: snapshot.realAvailableBalance,
        realPosition: snapshot.realPosition,
        realPositionState: snapshot.realPositionState,
        realAccountLastSync: snapshot.realAccountLastSync,
        realLastSync: snapshot.realLastSync,
        balance: firstAvailable(
            snapshot.balance,
            wsMarketData?.balance,
        ),
        equity: firstAvailable(
            snapshot.equity,
            wsMarketData?.equity,
        ),
        availableBalance: firstAvailable(
            wsMarketData?.availableBalance,
            wsMarketData?.available_balance,
            snapshot.availableBalance,
            snapshot.available_balance,
        ),
        position,
        pnl: firstAvailable(
            snapshot.pnl,
            wsMarketData?.pnl,
            wsMarketData?.unrealizedPnL,
        ),
        lastUpdate,
    };
};
