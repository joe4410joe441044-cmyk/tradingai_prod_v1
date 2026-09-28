export const OPERATION_PREPARATION_OPTIONS = Object.freeze({
    tradingModes: ["PAPER", "LIVE"],
    selectionModes: ["MANUAL", "AUTO"],
    // Note: the canonical Market Selection value stays "MANUAL". Only the
    // operator-facing label is presented as "SELECT" (see below) so that Market
    // Selection (which market / symbol) is never confused with Execution
    // Control authority, which legitimately keeps the label "MANUAL".
    symbols: ["XRPUSDTM", "BTCUSDTM", "ETHUSDTM"],
    riskPerTrade: [0.1, 0.25, 0.5, 0.75, 1],
    maxExposure: [10, 20, 30, 40, 50],
    maxDrawdown: [5, 7, 10],
    requestedLeverage: [1, 2, 3, 4, 5, 7, 10],
    positionSize: [0, 25, 50, 75, 100],
    stopLossPercent: [0.25, 0.5, 0.75, 1, 1.5, 2],
    takeProfitPercent: [0.5, 1, 1.5, 2, 3, 5],
    timeframes: ["1m", "5m", "15m", "1h"],
});

// UI presentation only. Market Selection canonical values remain
// AUTO / MANUAL; the operator-facing label for MANUAL is "SELECT" (the
// operator selects the market / symbol). This mapping MUST NOT be applied to
// Execution Control authority, where "MANUAL" means human manual trade
// authority and stays "MANUAL".
export const SELECTION_MODE_DISPLAY_LABELS = Object.freeze({
    AUTO: "AUTO",
    MANUAL: "SELECT",
});

export const selectionModeDisplayLabel = (value) => {
    const key = String(value ?? "").trim().toUpperCase();
    return SELECTION_MODE_DISPLAY_LABELS[key] || value;
};

const supportedValue = (values, candidate, fallback) => (
    values.includes(candidate) ? candidate : fallback
);

export const createOperationPreparationSettings = (config = {}) => ({
    tradingMode: supportedValue(
        OPERATION_PREPARATION_OPTIONS.tradingModes,
        String(config.mode || "").toUpperCase(),
        "PAPER",
    ),
    selectionMode: supportedValue(
        OPERATION_PREPARATION_OPTIONS.selectionModes,
        String(config.selectionMode || "").toUpperCase(),
        "AUTO",
    ),
    manualSymbol: supportedValue(
        OPERATION_PREPARATION_OPTIONS.symbols,
        String(config.symbol || "").toUpperCase(),
        "XRPUSDTM",
    ),
    compounding: false,
    requestedLeverage: config.leverage == null || config.leverage === ""
        ? 3
        : Number(config.leverage),
    positionSize: config.positionSize == null || config.positionSize === "" ? 0 : Number(config.positionSize),
    stopLossPercent: config.sl == null || config.sl === "" ? 1 : Number(config.sl),
    takeProfitPercent: config.tp == null || config.tp === "" ? 2 : Number(config.tp),
    trailingStop: config.trailing === true,
    timeframe: supportedValue(OPERATION_PREPARATION_OPTIONS.timeframes, String(config.timeframe || ""), "1m"),
    loopOnStart: Boolean(config.loopOnStart),
    autoTradeOnStart: Boolean(config.autoTradeOnStart),
});

// SAVE SETTINGS authority boundary: the fields that START consumes and that
// the SAVE SETTINGS button commits. These are the non-MM trade settings; the
// MM fields (risk / exposure / drawdown / compounding) are already owned by
// the separate Money Management configuration authority (auto-persisted).
export const TRADE_SETTINGS_SNAPSHOT_KEYS = Object.freeze([
    "mode",
    "selectionMode",
    "symbol",
    "leverage",
    "positionSize",
    "sl",
    "tp",
    "trailing",
    "timeframe",
    "loopOnStart",
    "autoTradeOnStart",
]);

// Normalize a raw trade-settings object into a comparable SAVE SETTINGS
// snapshot. Missing keys normalize to null so a fresh draft and an empty saved
// revision never compare as "changed" merely because a key is absent.
export const snapshotTradeSettings = (config = {}) => {
    const snapshot = {};
    for (const key of TRADE_SETTINGS_SNAPSHOT_KEYS) {
        const value = config == null ? undefined : config[key];
        snapshot[key] = value === undefined || value === null ? null : value;
    }
    return snapshot;
};

// Draft != Saved only when a committed field actually differs. Coerces to
// string so numeric 5 vs "5" (leverage select) do not produce a spurious
// unsaved state.
export const tradeSettingsDiffer = (left, right) => {
    const a = snapshotTradeSettings(left);
    const b = snapshotTradeSettings(right);
    return TRADE_SETTINGS_SNAPSHOT_KEYS.some((key) => String(a[key]) !== String(b[key]));
};

export const operationPreparationSummary = (settings, selectedSymbol, riskPerTradePercent) => ({
    mode: settings.tradingMode,
    market: settings.selectionMode,
    symbol: settings.selectionMode === "MANUAL"
        ? settings.manualSymbol
        : selectedSymbol || "AUTO SELECT",
    riskPerTrade: Number.isFinite(Number(riskPerTradePercent))
        ? `${Number(riskPerTradePercent).toFixed(2)}%`
        : "UNAVAILABLE",
    requestedLeverage: `${settings.requestedLeverage}x`,
    positionSize: `${settings.positionSize} USDT`,
    stopLoss: `${settings.stopLossPercent}%`,
    takeProfit: `${settings.takeProfitPercent}%`,
    trailingStop: settings.trailingStop ? "ON" : "OFF",
    timeframe: settings.timeframe,
    loop: settings.loopOnStart ? "ON" : "OFF",
    autoTrade: settings.autoTradeOnStart ? "ON" : "OFF",
});

export const normalizeReadiness = (value, readyValues = []) => {
    const normalized = String(value ?? "UNKNOWN").trim().toUpperCase();
    if (readyValues.includes(normalized)) return "READY";
    if (["BLOCKED", "ERROR", "FAILED", "LOCKED"].includes(normalized)) {
        return normalized === "FAILED" || normalized === "LOCKED"
            ? "BLOCKED"
            : normalized;
    }
    if (["WAITING", "PENDING", "PROCESSING", "STARTING"].includes(normalized)) {
        return "WAITING";
    }
    return normalized || "UNKNOWN";
};

export const positionReadiness = (position) => {
    const normalized = String(position ?? "UNKNOWN").trim().toUpperCase();
    if (["FLAT", "NONE", "CLOSED", "NO POSITION"].includes(normalized)) {
        return "FLAT";
    }
    if (["LONG", "SHORT", "OPEN"].includes(normalized)) return "BLOCKED";
    return "UNKNOWN";
};

export const pendingOrderReadiness = (pendingOrder) => {
    if (pendingOrder === false) return "SAFE";
    if (pendingOrder === true) return "BLOCKED";
    return "UNKNOWN";
};

export const pendingOrderAuthorityValue = (status) => {
    const authority = status?.pendingOrderState ?? status?.pending_order_state;
    if (authority && typeof authority === "object") {
        if (authority.known !== true) return null;
        if (typeof authority.pending === "boolean") return authority.pending;
        if (typeof authority.pending_order === "boolean") {
            return authority.pending_order;
        }
        return null;
    }
    return typeof status?.pendingOrder === "boolean"
        ? status.pendingOrder
        : null;
};

const ABSENT_SYMBOL_VALUES = new Set([
    "",
    "UNKNOWN",
    "NOT AVAILABLE",
    "NONE",
    "NULL",
]);
const READY_INTEGRATION_STATES = new Set(["READY", "RUNNING", "AVAILABLE"]);

const validAuthoritySymbol = (value) => {
    if (value === null || value === undefined) return null;
    const text = String(value).trim();
    if (!text || ABSENT_SYMBOL_VALUES.has(text.toUpperCase())) return null;
    return text;
};

// Single Operation display/bootstrap symbol authority. This does NOT create a
// new symbol authority: it only selects from the existing backend read model.
//
// POST-START (BOT RUNNING): the committed canonical runtime symbol
// (botStatus.activeSymbol / autoMarketSelection.activeSymbol) is authoritative.
//
// PRE-START (BOT STOPPED): after a backend restart the canonical runtime symbol
// is reset to null while a fresh, production-ready AUTO candidate may still
// exist. That candidate is the existing pre-start bootstrap authority used for
// Dashboard display, START readiness, the LIVE confirmation symbol, and the
// START payload bootstrap symbol. It never becomes final execution authority:
// after START the runtime AUTO selection / safe-switch remains canonical.
//
// Fails closed to "NOT AVAILABLE" when no valid authority exists.
export const resolveOperationDisplaySymbol = (botStatus = {}) => {
    const canonical = validAuthoritySymbol(botStatus?.activeSymbol)
        || validAuthoritySymbol(botStatus?.autoMarketSelection?.activeSymbol);
    if (canonical) return canonical;

    const running = botStatus?.running === true
        || String(botStatus?.status || "").trim().toUpperCase() === "RUNNING";
    if (running) return "NOT AVAILABLE";

    const integrationStatus = String(
        botStatus?.autoMarketSelection?.productionIntegration?.status || "",
    ).trim().toUpperCase();
    if (!READY_INTEGRATION_STATES.has(integrationStatus)) {
        return "NOT AVAILABLE";
    }

    return validAuthoritySymbol(
        botStatus?.autoMarketSelection?.topCandidate?.symbol,
    ) || "NOT AVAILABLE";
};

// Effective authoritative MM configuration. Both the standalone
// configuration (GET /configuration) and the polled status configuration
// (mmStatus.configuration from GET /status) are already normalized by the
// SAME frontend contract (normalizeMoneyManagementConfiguration). This merge
// prefers the standalone source and falls back to the polled authoritative
// configuration so Final Preparation never blocks on a missing standalone
// request that the polled status already satisfies. It never fabricates
// values and never mutates either source.
export const resolveEffectiveMmConfiguration = (standalone, polled) => {
    if (standalone && typeof standalone === "object" && !Array.isArray(standalone)) {
        return standalone;
    }
    if (polled && typeof polled === "object" && !Array.isArray(polled)) {
        return polled;
    }
    return null;
};

export const savedMmConfigurationReadiness = (configuration) => {
    if (!configuration || typeof configuration !== "object") return "BLOCKED";

    const requiredPositiveFields = [
        "riskPerTradePercent",
        "totalExposurePercent",
        "maximumDrawdownPercent",
        "maximumLeverage",
    ];
    return requiredPositiveFields.every((field) => {
        const value = Number(configuration[field]);
        return Number.isFinite(value) && value > 0;
    }) ? "READY" : "BLOCKED";
};

/* =================================================
   CAPITAL AUTHORITY PRESENTATION
   Presentation only. These helpers never become execution authority: the
   SAVE contract and the START payload are unchanged, and REAL sizing stays
   owned by the backend REAL_LIVE_ACCOUNT authority. They only make the
   Final Preparation / Trade Settings capital rows follow the SAVED trading
   mode so PAPER capital is never presented as LIVE capital.
================================================= */

export const CAPITAL_AUTHORITY_REAL_LIVE_ACCOUNT = "REAL_LIVE_ACCOUNT";
export const CAPITAL_AUTHORITY_PAPER_ACCOUNT = "PAPER_ACCOUNT";
export const REAL_LIVE_ACCOUNT_SOURCE = "KUCOIN_FUTURES_READ_ONLY";

const ABSENT_CAPITAL_VALUES = new Set(["", "UNKNOWN", "NOT AVAILABLE", "NONE", "NULL"]);

const firstCapitalCandidate = (values = []) => values.find((value) => (
    value !== null
    && value !== undefined
    && !(typeof value === "number" && !Number.isFinite(value))
));

const toFiniteNumber = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
};

// Normalize a numeric capital amount for display without leaking binary
// floating-point noise (e.g. 7.91836966 * 0.005 -> 0.0395918483).
export const formatCapitalAmount = (value) => {
    const parsed = toFiniteNumber(value);
    return parsed === null ? null : String(parsed);
};

// The canonical current risk allowance for a mode's capital authority:
// capital * riskPerTradePercent / 100 (mirrors calculate_risk_budget).
export const calculateCurrentRiskBudget = (capital, riskPerTradePercent) => {
    const capitalValue = toFiniteNumber(capital);
    const riskValue = toFiniteNumber(riskPerTradePercent);
    if (capitalValue === null || riskValue === null) return null;
    const budget = (capitalValue * riskValue) / 100;
    if (!Number.isFinite(budget)) return null;
    return String(Number(budget.toFixed(12)));
};

// Canonical read-only LIVE account capital authority. Reuses the existing
// bot-status real-account projection (accountRuntime.realAccount, source
// KUCOIN_FUTURES_READ_ONLY); it never triggers a second exchange request and
// fails closed (available=false) when the snapshot is missing, stale,
// disconnected, or unauthenticated.
export const deriveLiveCapitalAuthority = (botStatus = {}) => {
    const realAccount = botStatus?.accountRuntime?.realAccount;
    const candidate = firstCapitalCandidate([
        botStatus?.realEquity,
        botStatus?.realAvailableBalance,
        botStatus?.realBalance,
        realAccount?.equity,
        realAccount?.availableBalance,
        realAccount?.balance,
    ]);
    const hasValue = toFiniteNumber(candidate) !== null;
    const stale = realAccount?.stale === true;
    const disconnected = realAccount
        ? (realAccount.connected === false || realAccount.authenticated === false)
        : false;
    return Object.freeze({
        source: CAPITAL_AUTHORITY_REAL_LIVE_ACCOUNT,
        exchangeSource: realAccount?.accountSource
            || botStatus?.accountSource
            || REAL_LIVE_ACCOUNT_SOURCE,
        value: hasValue ? candidate : null,
        available: hasValue && !stale && !disconnected,
        stale,
        disconnected,
    });
};

const presentableCapital = (value) => {
    if (value === null || value === undefined) return null;
    const text = String(value);
    if (ABSENT_CAPITAL_VALUES.has(text.trim().toUpperCase())) return null;
    return text;
};

// Mode-specific capital authority projection for the operator display.
// LIVE: AVAILABLE CAPITAL / current risk budget come from the REAL account
// authority; PAPER projection can never win. PAPER: canonical PAPER account
// projection is preserved verbatim. referenceCapital is always reported
// separately so the compounding/reference basis is never confused with
// available capital.
export const deriveCapitalAuthorityPresentation = ({
    mode,
    paperCapitalSource,
    paperAvailableCapital,
    paperRiskBudget,
    referenceCapital,
    riskPerTradePercent,
    liveCapitalAuthority,
} = {}) => {
    const normalizedMode = String(mode || "").trim().toUpperCase();
    if (normalizedMode === "LIVE") {
        const authority = (
            liveCapitalAuthority
            && typeof liveCapitalAuthority === "object"
        ) ? liveCapitalAuthority : {};
        const liveAvailable = authority.available === true;
        const availableCapital = liveAvailable
            ? formatCapitalAmount(authority.value)
            : null;
        const riskBudget = liveAvailable
            ? calculateCurrentRiskBudget(authority.value, riskPerTradePercent)
            : null;
        return Object.freeze({
            mode: "LIVE",
            capitalAuthorityLabel: authority.source || CAPITAL_AUTHORITY_REAL_LIVE_ACCOUNT,
            availableCapital,
            availableCapitalUnavailable: availableCapital === null,
            riskBudget,
            riskBudgetUnavailable: riskBudget === null,
            referenceCapital: presentableCapital(referenceCapital),
            liveCapitalStale: authority.stale === true,
            liveCapitalAvailable: liveAvailable,
        });
    }
    const availableCapital = presentableCapital(paperAvailableCapital);
    const riskBudget = presentableCapital(paperRiskBudget);
    return Object.freeze({
        mode: "PAPER",
        capitalAuthorityLabel: paperCapitalSource || CAPITAL_AUTHORITY_PAPER_ACCOUNT,
        availableCapital,
        availableCapitalUnavailable: availableCapital === null,
        riskBudget,
        riskBudgetUnavailable: riskBudget === null,
        referenceCapital: presentableCapital(referenceCapital),
        liveCapitalStale: false,
        liveCapitalAvailable: false,
    });
};

export const deriveMmReadiness = ({
    executionEntryAllowed,
    recommendedAction,
    riskState,
} = {}) => {
    if (executionEntryAllowed === true) {
        return Object.freeze({ state: "READY", label: "ENTRY ALLOWED" });
    }
    if (executionEntryAllowed === false) {
        if (recommendedAction === "BLOCK_EXECUTION" || riskState === "LOCKED") {
            return Object.freeze({ state: "BLOCKED", label: "BLOCKED" });
        }
        if (recommendedAction === "HOLD_NEW_ENTRIES") {
            return Object.freeze({ state: "WAITING", label: "ON HOLD" });
        }
        return Object.freeze({ state: "WAITING", label: "WAITING" });
    }
    return Object.freeze({ state: "UNKNOWN", label: "UNKNOWN" });
};

const POSITIVE_READINESS = new Set(["READY", "SAFE", "FLAT"]);
const BLOCKING_READINESS = new Set([
    "BLOCKED",
    "ERROR",
    "FAILED",
    "LOCKED",
    "UNAVAILABLE",
    "UNKNOWN",
]);

export const deriveReviewReadiness = (readinessValues = []) => {
    if (readinessValues.some((value) => BLOCKING_READINESS.has(value))) {
        return "BLOCKED";
    }
    if (readinessValues.every((value) => POSITIVE_READINESS.has(value))) {
        return "READY";
    }
    return "WAITING";
};

export const deriveOperationReadiness = ({
    botRunning = false,
    tradingMode,
    dryRun,
    selectionMode,
    autoMarketState,
    displaySymbol,
    emergencyState,
    position,
    pendingOrder,
    governanceStatus,
    realOrderAllowed,
    executionEnabled,
    executionEntryAllowed,
    recommendedAction,
    riskState,
    requestedLeverage,
    maximumLeverage,
    mmConfiguration,
    mmBlockReasons = [],
    mmConfigurationError = false,
    allowLive,
    tradeMode,
    paperBootstrapEligible,
    loopOnStart = false,
    autoTradeOnStart = false,
} = {}) => {
    const selectionRuntime = normalizeReadiness(
        autoMarketState,
        ["READY", "RUNNING", "AVAILABLE"],
    );
    const selectedRuntimeSymbol = selectionMode === "AUTO"
        && selectionRuntime === "READY"
        && displaySymbol
        && !["UNKNOWN", "NOT AVAILABLE"].includes(String(displaySymbol).toUpperCase())
        ? displaySymbol
        : null;
    const selectionReadiness = selectionMode === "MANUAL"
        ? "READY"
        : selectedRuntimeSymbol
            ? "READY"
            : selectionRuntime === "READY" ? "WAITING" : selectionRuntime;
    const emergencyReadiness = normalizeReadiness(emergencyState, ["READY"]);
    const positionState = positionReadiness(position);
    const orderAuthority = pendingOrderReadiness(pendingOrder);
    const governanceReadiness = normalizeReadiness(
        governanceStatus,
        ["READY", "OK", "ALLOWED", "PASS"],
    );
    const executionReadiness = realOrderAllowed || executionEnabled
        ? "BLOCKED"
        : "SAFE";
    const mmEntryReadiness = deriveMmReadiness({
        executionEntryAllowed,
        recommendedAction,
        riskState,
    });
    const mmReadiness = mmEntryReadiness.state;
    const mmReadinessSource = (
        executionEntryAllowed === true || executionEntryAllowed === false
    ) ? "RUNTIME" : "NOT CONNECTED";
    const savedMmReadiness = (
        mmConfigurationError
            ? "BLOCKED"
            : savedMmConfigurationReadiness(mmConfiguration)
    );
    const requestedLeverageValue = Number(requestedLeverage);
    const maximumLeverageValue = Number(maximumLeverage);
    const leverageReadiness = (
        Number.isFinite(requestedLeverageValue)
        && requestedLeverageValue > 0
        && Number.isFinite(maximumLeverageValue)
        && maximumLeverageValue > 0
        && requestedLeverageValue <= maximumLeverageValue
    ) ? "READY" : "BLOCKED";
    const entryExecutionReadiness = executionEnabled === true
        ? "READY"
        : "WAITING";
    const entryReadinessValues = [
        emergencyReadiness,
        positionState,
        orderAuthority,
        selectionReadiness,
        mmReadiness,
        governanceReadiness,
        entryExecutionReadiness,
        leverageReadiness,
    ];
    const entryReadiness = botRunning === true
        ? deriveReviewReadiness(entryReadinessValues)
        : "WAITING";
    const entryReady = entryReadiness === "READY";
    const automationReadinessValues = [
        emergencyReadiness,
        positionState,
        orderAuthority,
        selectionReadiness,
        mmReadiness,
        governanceReadiness,
        leverageReadiness,
    ];
    const automationReadiness = deriveReviewReadiness(
        automationReadinessValues,
    );
    const automationReady = automationReadiness === "READY";

    const normalizedMode = String(tradingMode || "").trim().toUpperCase();
    const normalizedMmBlockReasons = Array.isArray(mmBlockReasons)
        ? mmBlockReasons.map((reason) => String(reason).trim().toUpperCase())
        : [];
    // WF: runtime-only MM metrics unavailability is a PAPER pre-start
    // PRESENTATION hint. It is NOT itself a START gate condition, and it must
    // never block START when the authoritative saved configuration is valid.
    const stoppedPaperRuntimeMetricsOnly = (
        botRunning !== true
        && normalizedMode === "PAPER"
        && dryRun === true
        && realOrderAllowed !== true
        && executionEntryAllowed === false
        && normalizedMmBlockReasons.length === 1
        && normalizedMmBlockReasons[0] === "TRADING_RUNTIME_METRICS_UNAVAILABLE"
    );
    // WF: START MM readiness depends ONLY on a valid authoritative saved
    // configuration. Runtime MM entry guard (mmReadiness) and runtime-only
    // metrics block reasons are ENTRY gates (post-START), never START gates.
    // A valid saved config + a fresh draft is READY; a genuinely invalid,
    // missing, or unavailable saved config fails closed to BLOCKED.
    const startMmReadiness = savedMmReadiness;

    // LIVE pre-start authority: the authoritative gate is the global
    // ALLOW_LIVE + TRADE_MODE permission, never the runtime real-order
    // state. Unknown/missing authority fails closed.
    const liveAuthorityReadiness = (() => {
        if (normalizedMode !== "LIVE") {
            return "NOT_RELEVANT";
        }
        if (allowLive !== true) {
            return "BLOCKED";
        }
        if (String(tradeMode ?? "").trim().toLowerCase() !== "live") {
            return "BLOCKED";
        }
        return "READY";
    })();
    const liveAutomationReadiness = (
        normalizedMode !== "LIVE"
        || (loopOnStart === false && autoTradeOnStart === false)
    ) ? "READY" : "BLOCKED";

    const paperPreStart = (
        botRunning !== true
        && normalizedMode === "PAPER"
        && dryRun === true
        && realOrderAllowed !== true
    );
    const paperBootstrapActive = (
        paperPreStart && paperBootstrapEligible === true
    );
    const startPositionReadiness = (
        paperBootstrapActive && positionState === "UNKNOWN"
    ) ? "READY" : positionState;
    const startOrderReadiness = (
        paperBootstrapActive && orderAuthority === "UNKNOWN"
    ) ? "READY" : orderAuthority;

    // Calculate readiness values for all modes.
    //
    // START gate semantics (Problems 5/6): the START gate answers "may the
    // BOT initialize a fresh runtime?" — it must NOT require runtime-only
    // post-START conditions (governance active, MM entry guard, execution
    // enabled) that cannot exist while the BOT is STOPPED. Those stay in the
    // ENTRY gate (entryReadinessValues) and remain fail-closed after start.
    const paperStartReadinessValues = [
        emergencyReadiness,
        startPositionReadiness,
        startOrderReadiness,
        selectionReadiness,
        startMmReadiness,
        executionReadiness,
        leverageReadiness,
    ];
    const startedStartReadinessValues = [
        emergencyReadiness,
        positionState,
        orderAuthority,
        selectionReadiness,
        startMmReadiness,
        executionReadiness,
        leverageReadiness,
    ];
    let startReadinessValues = paperPreStart
        ? paperStartReadinessValues
        : startedStartReadinessValues;
    if (normalizedMode === "LIVE") {
        startReadinessValues = [
            emergencyReadiness,
            positionState,
            orderAuthority,
            selectionReadiness,
            startMmReadiness,
            executionReadiness,
            leverageReadiness,
            liveAuthorityReadiness,
            liveAutomationReadiness,
        ];
    }
    if (normalizedMode !== "PAPER" && normalizedMode !== "LIVE") {
        startReadinessValues = [
            ...startReadinessValues,
            "BLOCKED",
        ];
    }
    let startReadiness = deriveReviewReadiness(startReadinessValues);
    let startReady = startReadiness === "READY";

    return {
        reviewReadiness: startReadiness,
        readinessValues: startReadinessValues,
        startReadiness,
        startReadinessValues,
        startReady,
        liveAuthorityReadiness,
        liveAutomationReadiness,
        entryReadiness,
        entryReadinessValues,
        entryReady,
        automationReadiness,
        automationReadinessValues,
        automationReady,
        selectionRuntime,
        selectedRuntimeSymbol,
        selectionReadiness,
        emergencyReadiness,
        positionState,
        orderAuthority,
        governanceReadiness,
        executionReadiness,
        mmEntryReadiness,
        mmReadiness,
        mmReadinessSource,
        savedMmReadiness,
        startMmReadiness,
        stoppedPaperRuntimeMetricsOnly,
        entryExecutionReadiness,
        leverageReadiness,
    };
};
