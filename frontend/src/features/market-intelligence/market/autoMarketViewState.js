const upper = (value) => typeof value === "string" ? value.toUpperCase() : null;

const MARKET_FAILURE_STATES = new Set(["INVALID", "STALE", "UNAVAILABLE"]);
const SWITCH_CONNECTING_STATES = new Set(["SUBSCRIBING", "VALIDATING"]);
const SWITCHING_STATES = new Set([
    "IN_PROGRESS", "PREPARING", "COMMITTING", "CLEANUP",
]);
const CYCLE_FAILURE_STATES = new Set([
    "FAILED", "NO_ELIGIBLE_MARKET", "NO_RANKABLE_MARKET", "SWITCH_BLOCKED",
]);

export function projectAutoMarketViewState({
    contextMode,
    marketModel,
    selectionStatus,
}) {
    if (contextMode !== "LIVE") return null;

    const marketState = upper(marketModel?.status) ?? "WAITING";
    if (upper(selectionStatus?.selectionMode) !== "AUTO") return marketState;

    const lifecycleState = upper(selectionStatus?.autoRuntime?.runtimeState);
    const cycleState = upper(selectionStatus?.autoRuntime?.status);
    const switchState = upper(selectionStatus?.switch?.state);

    if (lifecycleState === "FAILED" || lifecycleState === "BLOCKED")
        return lifecycleState;
    if (switchState === "FAILED") return "FAILED";
    if (CYCLE_FAILURE_STATES.has(cycleState)) return cycleState;
    if (MARKET_FAILURE_STATES.has(marketState)) return marketState;
    if (SWITCH_CONNECTING_STATES.has(switchState)) return "CONNECTING";
    if (SWITCHING_STATES.has(switchState) || cycleState === "SWITCHING")
        return "SWITCHING";
    if (lifecycleState === "RUNNING_CYCLE" || cycleState === "EVALUATING")
        return "SELECTING";

    const activeSymbol = upper(selectionStatus?.activeSymbol);
    const marketSymbol = upper(marketModel?.context?.normalizedSymbol);
    if (!activeSymbol)
        return lifecycleState === "READY" ? "SELECTING" : marketState;
    if (marketState === "READY")
        return marketSymbol === activeSymbol ? "READY" : "WAITING";

    return marketState;
}
