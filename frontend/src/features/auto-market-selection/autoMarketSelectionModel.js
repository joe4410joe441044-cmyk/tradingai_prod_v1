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
