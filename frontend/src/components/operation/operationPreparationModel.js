export const OPERATION_PREPARATION_OPTIONS = Object.freeze({
    tradingModes: ["PAPER", "LIVE"],
    selectionModes: ["MANUAL", "AUTO"],
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
