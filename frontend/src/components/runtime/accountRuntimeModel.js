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
    const paperUnrealizedPnl = paperAvailable
        ? paperAccount.unrealizedPnl
        : null;
    const paperRealizedPnl = paperAvailable
        ? paperAccount.realizedPnl
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
    const realWalletBalanceRaw = realExchangeMatches
        ? realAccount.walletBalance
        : null;
    const realUnrealizedPnlRaw = realExchangeMatches
        ? realAccount.unrealizedPnl
        : null;
    const realRealizedPnlTodayRaw = realExchangeMatches
        ? realAccount.realizedPnlToday
        : null;
    const realTotalPnlTodayRaw = realExchangeMatches
        ? realAccount.totalPnlToday
        : null;
    const realMarginUsedRaw = realExchangeMatches
        ? realAccount.marginUsed
        : null;
    const realMarginAvailableRaw = realExchangeMatches
        ? realAccount.marginAvailable
        : null;
    const realMarginRatioRaw = realExchangeMatches
        ? realAccount.marginRatio
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
    const realUnrealizedPnlValue = realConnected || realLoading || realStale
        ? displayRuntimeValue(realUnrealizedPnlRaw, {
            formatter: formatPnl,
            loading: realLoading,
            stale: realStale,
        })
        : realUnavailable;
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
        paperUnrealizedPnl,
        paperRealizedPnl,
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
        realWalletBalanceRaw,
        realUnrealizedPnlRaw,
        realRealizedPnlTodayRaw,
        realTotalPnlTodayRaw,
        realMarginUsedRaw,
        realMarginAvailableRaw,
        realMarginRatioRaw,
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
        realUnrealizedPnlValue,
        realPositionValue,
        displayedReason,
    };
};

/* =================================================
   ACCOUNT FINANCIAL STATUS — read-only projection.

   The 3x3 Account Financial Status grid is driven by
   authoritative backend / exchange fields only.

   Only fields with a real canonical source produce a
   numeric value. Missing / ambiguous / undefined fields
   surface as UNAVAILABLE — never as a fabricated zero.
   This module performs no arithmetic and never invents a
   derived figure that is not already an authoritative
   backend field.

   Order is the authoritative UI priority:
     ROW 1 assets -> ROW 2 pnl -> ROW 3 margin.
================================================= */

export const ACCOUNT_FINANCIAL_UNIT = "USDT";

export const ACCOUNT_FINANCIAL_METRICS = [
    { key: "equity", label: "EQUITY", jpLabel: "純資産", icon: "equity", category: "asset" },
    { key: "availableBalance", label: "AVAILABLE BALANCE", jpLabel: "利用可能額", icon: "availableBalance", category: "asset" },
    { key: "walletBalance", label: "WALLET BALANCE", jpLabel: "ウォレット残高", icon: "walletBalance", category: "asset" },
    { key: "unrealizedPnl", label: "UNREALIZED PNL", jpLabel: "含み損益", icon: "unrealizedPnl", category: "pnl" },
    { key: "realizedPnlToday", label: "REALIZED PNL TODAY", jpLabel: "本日実現損益", icon: "realizedPnlToday", category: "pnl" },
    { key: "totalPnlToday", label: "TOTAL PNL TODAY", jpLabel: "本日総損益", icon: "totalPnlToday", category: "pnl" },
    { key: "marginUsed", label: "MARGIN USED", jpLabel: "使用証拠金", icon: "marginUsed", category: "margin" },
    { key: "marginAvailable", label: "MARGIN AVAILABLE", jpLabel: "利用可能証拠金", icon: "marginAvailable", category: "margin" },
    { key: "marginRatio", label: "MARGIN RATIO", jpLabel: "証拠金率", icon: "marginRatio", category: "margin", percent: true },
];

/* PAPER view keeps the same 3x3 grid slots (so switching never reflows the
   layout) but relabels/remaps the cells that have a canonical paper meaning.
   MARGIN cells have no authoritative paper equivalent and remain UNAVAILABLE
   (rendered as "—"), never a fabricated zero. */
export const PAPER_FINANCIAL_METRICS = [
    { key: "equity", label: "EQUITY", jpLabel: "純資産", icon: "equity", category: "asset" },
    { key: "availableBalance", label: "AVAILABLE BALANCE", jpLabel: "利用可能額", icon: "availableBalance", category: "asset" },
    { key: "walletBalance", label: "BALANCE", jpLabel: "残高", icon: "walletBalance", category: "asset" },
    { key: "unrealizedPnl", label: "UNREALIZED PNL", jpLabel: "含み損益", icon: "unrealizedPnl", category: "pnl" },
    { key: "realizedPnlToday", label: "REALIZED PNL", jpLabel: "確定損益", icon: "realizedPnlToday", category: "pnl" },
    { key: "totalPnlToday", label: "TOTAL PNL", jpLabel: "総損益", icon: "totalPnlToday", category: "pnl" },
    { key: "marginUsed", label: "MARGIN USED", jpLabel: "使用証拠金", icon: "marginUsed", category: "margin" },
    { key: "marginAvailable", label: "MARGIN AVAILABLE", jpLabel: "利用可能証拠金", icon: "marginAvailable", category: "margin" },
    { key: "marginRatio", label: "MARGIN RATIO", jpLabel: "証拠金率", icon: "marginRatio", category: "margin", percent: true },
];

const isFiniteNumber = (value) => (
    typeof value === "number" && Number.isFinite(value)
);

const pnlTone = (value) => {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue) || numericValue === 0) {
        return "neutral";
    }
    return numericValue > 0 ? "positive" : "negative";
};

/* PAPER financial projection. Reads canonical paperAccount fields only; it
   never borrows a REAL field and never invents a paper margin/leverage figure. */
const derivePaperFinancialMetrics = (derived = {}) => {
    const { paperAccount, paperAvailable } = derived;
    const account = paperAccount && typeof paperAccount === "object"
        ? paperAccount
        : {};
    const available = paperAvailable !== false;

    const rawByKey = {
        equity: account.equity,
        availableBalance: account.availableBalance,
        walletBalance: account.balance,
        unrealizedPnl: account.unrealizedPnl,
        realizedPnlToday: account.realizedPnl,
        totalPnlToday: account.totalPnl,
        marginUsed: null,
        marginAvailable: null,
        marginRatio: null,
    };

    return PAPER_FINANCIAL_METRICS.map((def) => {
        let value = null;
        let unit = null;
        let state = null;

        if (!available || def.category === "margin") {
            state = "UNAVAILABLE";
        } else if (isFiniteNumber(rawByKey[def.key])) {
            value = def.category === "pnl"
                ? formatPnl(rawByKey[def.key])
                : formatAmount(rawByKey[def.key]);
            unit = def.percent ? "%" : ACCOUNT_FINANCIAL_UNIT;
        } else {
            state = "UNAVAILABLE";
        }

        const tone = def.category === "pnl"
            ? pnlTone(rawByKey[def.key])
            : "neutral";

        return {
            ...def,
            value,
            unit,
            state,
            tone,
        };
    });
};

export const deriveFinancialMetrics = (derived = {}, accountView = "LIVE") => {
    if (String(accountView).toUpperCase() === "PAPER") {
        return derivePaperFinancialMetrics(derived);
    }

    const {
        realLoading,
        realStale,
        realConnected,
        realEquityRaw,
        realAvailableRaw,
        realWalletBalanceRaw,
        realUnrealizedPnlRaw,
        realRealizedPnlTodayRaw,
        realTotalPnlTodayRaw,
        realMarginUsedRaw,
        realMarginAvailableRaw,
        realMarginRatioRaw,
    } = derived;

    const rawByKey = {
        equity: realEquityRaw,
        availableBalance: realAvailableRaw,
        walletBalance: realWalletBalanceRaw,
        unrealizedPnl: realUnrealizedPnlRaw,
        realizedPnlToday: realRealizedPnlTodayRaw,
        totalPnlToday: realTotalPnlTodayRaw,
        marginUsed: realMarginUsedRaw,
        marginAvailable: realMarginAvailableRaw,
        marginRatio: realMarginRatioRaw,
    };

    return ACCOUNT_FINANCIAL_METRICS.map((def) => {
        let value = null;
        let unit = null;
        let state = null;

        if (realLoading) {
            state = "REFRESHING";
        } else if (realStale) {
            state = "STALE";
        } else if (
            realConnected
            && isFiniteNumber(rawByKey[def.key])
        ) {
            value = def.category === "pnl"
                ? formatPnl(rawByKey[def.key])
                : formatAmount(rawByKey[def.key]);
            unit = def.percent ? "%" : ACCOUNT_FINANCIAL_UNIT;
        } else {
            state = "UNAVAILABLE";
        }

        const tone = def.category === "pnl"
            ? pnlTone(rawByKey[def.key])
            : "neutral";

        return {
            ...def,
            value,
            unit,
            state,
            tone,
        };
    });
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

/* =================================================
   Account View (display-only) helpers.

   accountView is a pure presentation selector:
     "PAPER" -> paper account view (UI label PAPER)
     "LIVE"  -> real/live account view (UI label REAL)

   The initial view follows selectedMode where valid. A manual
   selection is preserved across polling refreshes because the
   caller keeps the manual value and it always wins.
================================================= */
export const initialAccountView = (selectedMode) => (
    String(selectedMode ?? "").trim().toUpperCase() === "LIVE" ? "LIVE" : "PAPER"
);

export const resolveAccountView = (selectedMode, manualView) => (
    manualView === "PAPER" || manualView === "LIVE"
        ? manualView
        : initialAccountView(selectedMode)
);

/* Position cards consume the C-P6 dual mode projections.
   - When dual projections exist, the requested view is selected and there is
     NEVER a cross-mode fallback: an absent key yields an unavailable ({}) card.
   - Legacy fallback (single currentPosition / lastPositionEvent) is allowed
     only when the legacy projection already belongs to the requested view, so
     PAPER data can never leak into REAL and vice versa.
   - Called without a view, the legacy projection is returned unchanged for
     backward compatibility with existing consumers. */
export const derivePositionCards = (accountRuntime, accountView) => {
    const runtime = accountRuntime && typeof accountRuntime === "object"
        ? accountRuntime
        : {};
    const view = accountView === "PAPER" || accountView === "LIVE"
        ? accountView
        : undefined;

    if (!view) {
        return {
            currentPosition: runtime.currentPosition ?? {},
            lastPositionEvent: runtime.lastPositionEvent ?? {},
        };
    }

    const byMode = runtime.positionsByMode;
    const eventsByMode = runtime.lastPositionEventsByMode;
    const hasDualProjection = (byMode && typeof byMode === "object")
        || (eventsByMode && typeof eventsByMode === "object");

    if (hasDualProjection) {
        const position = byMode && typeof byMode === "object" ? byMode[view] : undefined;
        const event = eventsByMode && typeof eventsByMode === "object"
            ? eventsByMode[view]
            : undefined;
        return {
            currentPosition: position && typeof position === "object" ? position : {},
            lastPositionEvent: event && typeof event === "object" ? event : {},
        };
    }

    const legacyPosition = runtime.currentPosition;
    const legacyEvent = runtime.lastPositionEvent;
    return {
        currentPosition: legacyPosition && legacyPosition.mode === view ? legacyPosition : {},
        lastPositionEvent: legacyEvent && legacyEvent.mode === view ? legacyEvent : {},
    };
};
export const positionNumber = (value, pnl = false) => isFiniteNumber(value)
    ? value.toLocaleString("en-US", { minimumFractionDigits: pnl ? 2 : 0, maximumFractionDigits: pnl ? 2 : 10 })
    : "—";
export const positionQuantity = (position) => `${positionNumber(position.quantity)} ${
    position.quantityUnit === "coin" ? "coin" : position.quantityUnit === "contract" ? "contracts" : "UNIT UNKNOWN"
}`;
export const positionTime = (value) => {
    if (!isFiniteNumber(value)) return "—";
    const date = new Date(value * 1000); // Canonical timestamps are Unix seconds.
    return Number.isFinite(date.getTime()) ? `${date.toISOString().replace("T", " ").slice(0, 19)} UTC` : "—";
};
export const positionHolding = (value) => {
    if (!isFiniteNumber(value) || value < 0) return "—";
    if (value < 1000) return `${Math.round(value)} ms`;
    if (value < 60000) return `${(value / 1000).toFixed(1)} sec`;
    if (value < 3600000) return `${Math.floor(value / 60000)}m ${Math.floor(value / 1000) % 60}s`;
    return `${Math.floor(value / 3600000)}h ${String(Math.floor(value / 60000) % 60).padStart(2, "0")}m`;
};
export const positionState = (position) => {
    if (position.freshness === "STALE" || position.status === "STALE") return "UNKNOWN / STALE";
    if (position.reason === "MULTIPLE_POSITIONS") return "MULTIPLE POSITIONS";
    return ["OPEN", "FLAT"].includes(position.status) ? position.status : "UNKNOWN";
};
