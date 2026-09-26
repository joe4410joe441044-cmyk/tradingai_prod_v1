const present = (value) => value !== null && value !== undefined && value !== "";

export const displayAmsValue = (value) => present(value) ? String(value) : "—";

const EMPTY_AUTO_RUNTIME = {
    mode: "MANUAL", runtimeState: "STOPPED", status: "IDLE",
    reasonCodes: [], lastCycleStatus: null, lastCycleId: null,
};

const uniqueReasons = (values) => values.filter((value, index, list) => value && list.indexOf(value) === index);

export function buildAutoMarketSelectionReasons(model) {
    return {
        historical: uniqueReasons([...(model?.autoRuntime?.reasonCodes || [])]).slice(0, 3),
        current: uniqueReasons([
            ...(model?.switch?.reasonCodes || []),
            ...(model?.reasons || []),
        ]).slice(0, 3),
    };
}

const RESELECT_BLOCKED_SWITCH_STATES = new Set([
    "PREPARING", "SUBSCRIBING", "VALIDATING", "COMMITTING", "CLEANUP", "IN_PROGRESS",
]);

export function deriveReselectControl(status, overrides = {}) {
    const model = buildAutoMarketSelectionModel(status);
    if (model.availability !== "AVAILABLE") {
        return { disabled: true, reason: "SELECTION_UNAVAILABLE" };
    }
    if (model.selectionMode !== "AUTO") {
        return { disabled: true, reason: "NOT_AUTO_MODE" };
    }
    if (!model.activeSymbol) {
        return { disabled: true, reason: "NO_ACTIVE_SYMBOL" };
    }
    const switchState = String(model.switch?.state || "").toUpperCase();
    if (RESELECT_BLOCKED_SWITCH_STATES.has(switchState)) {
        return { disabled: true, reason: "RESELECT_IN_PROGRESS" };
    }
    if (overrides.disabled) {
        return { disabled: true, reason: overrides.reason || "RESELECT_UNAVAILABLE" };
    }
    return { disabled: false, reason: null };
}

export function deriveReselectBlocker(botStatus) {
    const positionOpen = botStatus?.position_active === true || Boolean(botStatus?.position);
    if (positionOpen) return { disabled: true, reason: "POSITION_OPEN" };
    if (botStatus?.pendingOrder === true) return { disabled: true, reason: "PENDING_ORDER" };
    const emergencyActive = botStatus?.emergencyStop === true
        || botStatus?.emergencyLocked === true
        || String(botStatus?.emergencyState || "").toUpperCase() === "LOCKED";
    if (emergencyActive) return { disabled: true, reason: "EMERGENCY_ACTIVE" };
    return { disabled: false, reason: null };
}

export function buildAutoMarketSelectionModel(status, requestedSymbol) {
    if (!status || typeof status !== "object") {
        return {
            availability: "UNAVAILABLE", selectionMode: "UNAVAILABLE",
            activeSymbol: null, requestedSymbol: requestedSymbol || null,
            autoRuntime: { ...EMPTY_AUTO_RUNTIME },
            scanner: { status: "UNAVAILABLE" }, ranking: { status: "UNAVAILABLE" },
            topCandidate: {}, capitalEligibility: { status: "UNAVAILABLE" },
            switch: { state: "UNAVAILABLE", reasonCodes: [] }, reasons: [],
            freshness: { universe: "UNKNOWN", scanner: "UNKNOWN", ranking: "UNKNOWN", mm: "UNKNOWN" },
        };
    }
    return {
        availability: "AVAILABLE",
        selectionMode: status.selectionMode || "UNAVAILABLE",
        // Never fall back to requestedSymbol or topCandidate.
        activeSymbol: status.activeSymbol || null,
        requestedSymbol: requestedSymbol || status.requestedSymbol || null,
        autoRuntime: status.autoRuntime || { ...EMPTY_AUTO_RUNTIME },
        scanner: status.scanner || { status: "UNAVAILABLE" },
        ranking: status.ranking || { status: "UNAVAILABLE" },
        topCandidate: status.topCandidate || {},
        capitalEligibility: status.capitalEligibility || { status: "UNAVAILABLE" },
        switch: status.switch || { state: "UNAVAILABLE", reasonCodes: [] },
        reasons: Array.isArray(status.reasons) ? status.reasons : [],
        freshness: status.freshness || {},
    };
}
