export const OPERATION_PREPARATION_OPTIONS = Object.freeze({
    tradingModes: ["PAPER", "LIVE"],
    selectionModes: ["MANUAL", "AUTO"],
    symbols: ["XRPUSDTM", "BTCUSDTM", "ETHUSDTM"],
    riskPerTrade: [0.1, 0.25, 0.5, 0.75, 1],
    maxExposure: [10, 20, 30, 40, 50],
    maxDrawdown: [5, 7, 10],
    requestedLeverage: [1, 2, 3, 4, 5],
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
    requestedLeverage: 3,
    loopOnStart: false,
    autoTradeOnStart: false,
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
} = {}) => {
    const selectionRuntime = normalizeReadiness(
        autoMarketState,
        ["READY", "RUNNING", "AVAILABLE"],
    );
    const selectedRuntimeSymbol = selectionMode === "AUTO"
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
    const readinessValues = [
        emergencyReadiness,
        positionState,
        orderAuthority,
        selectionReadiness,
        mmReadiness,
        governanceReadiness,
        executionReadiness,
    ];
    const reviewReadiness = deriveReviewReadiness(readinessValues);

    return {
        reviewReadiness,
        readinessValues,
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
    };
};
