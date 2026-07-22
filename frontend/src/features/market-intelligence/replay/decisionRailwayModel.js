const DASH = "—";

const DEFINITIONS = Object.freeze([
    { id: "market-data", title: "Market Data", subtitle: "Raw market inputs" },
    { id: "detectors", title: "Python Detectors", subtitle: "Deterministic market analysis" },
    { id: "feature-builder", title: "Feature Builder", subtitle: "Normalized strategy features" },
    { id: "strategy", title: "Strategy", subtitle: "First decision layer" },
    { id: "ai-review", title: "AI Review", subtitle: "Evidence review and final direction" },
    { id: "governance", title: "Governance", subtitle: "Safety authority" },
    { id: "execution", title: "Execution", subtitle: "Order and position result" },
]);

const STATION_ALIASES = Object.freeze({
    detector: "detectors",
    detectors: "detectors",
    "python-detectors": "detectors",
    "feature-builder": "feature-builder",
    features: "feature-builder",
    "python-strategy": "strategy",
    strategy: "strategy",
    "ai-final-decision": "ai-review",
    ai: "ai-review",
    "ai-review": "ai-review",
    governance: "governance",
    execution: "execution",
});

const EVENT_STATIONS = Object.freeze({
    MARKET_SNAPSHOT: "market-data",
    DETECTOR_SIGNAL: "detectors",
    STRATEGY_DECISION: "strategy",
    AI_DECISION: "ai-review",
    GOVERNANCE_DECISION: "governance",
    ORDER_SUBMITTED: "execution",
    ORDER_ACKNOWLEDGED: "execution",
    EXECUTION_REJECTED: "execution",
    POSITION_OPENED: "execution",
    POSITION_UPDATED: "execution",
    POSITION_CLOSED: "execution",
});

const safeValue = (value) => {
    if (typeof value === "string" && value !== "") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
    return DASH;
};

const timestampLabel = (value) => {
    const epoch = typeof value === "number" ? value : Date.parse(value);
    return Number.isFinite(epoch) ? new Date(epoch).toISOString() : DASH;
};

const direction = (value) => {
    const normalized = typeof value === "string" ? value.toUpperCase() : "";
    if (normalized === "LONG") return "BUY";
    if (normalized === "SHORT") return "SELL";
    return ["BUY", "SELL", "HOLD"].includes(normalized) ? normalized : "UNKNOWN";
};

const eventStation = (event) => (
    STATION_ALIASES[event?.stationId] ?? EVENT_STATIONS[event?.eventType] ?? null
);

const stationEvents = (projection, stationId) => {
    const groups = Array.isArray(projection.stationContext?.stations)
        ? projection.stationContext.stations
        : [];
    const fromContext = groups.flatMap((group) => (
        STATION_ALIASES[group?.stationId] === stationId && Array.isArray(group.events)
            ? group.events
            : []
    ));
    if (stationId !== "market-data") return fromContext;
    const visible = Array.isArray(projection.visibleEvents) ? projection.visibleEvents : [];
    return [...fromContext, ...visible.filter((event) => eventStation(event) === stationId)];
};

const fields = (entries) => entries
    .map(([label, value]) => ({ label, value: safeValue(value) }))
    .filter(({ value }) => value !== DASH)
    .slice(0, 6);

const eventDetails = (id, event, engine, projection) => {
    const payload = event?.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
        ? event.payload
        : {};
    if (id === "market-data") return fields([
        ["Symbol", engine.dataset?.symbol], ["Exchange", engine.dataset?.exchange],
        ["Spread", payload.spread], ["Volatility", payload.volatility],
        ["Buy Pressure", payload.buyPressure], ["Sell Pressure", payload.sellPressure],
        ["Mark Price", payload.markPrice],
    ]);
    if (id === "detectors") return fields([
        ["Signal", payload.signal], ["Iceberg", payload.iceberg], ["Spoofing", payload.spoofing],
        ["Absorption", payload.absorption], ["Fake Pressure", payload.fakePressure],
        ["Momentum", payload.momentum ?? payload.confidence], ["Liquidity", payload.liquidity],
    ]);
    if (id === "feature-builder") return fields([
        ["Feature Count", payload.featureCount], ["Normalized", payload.normalized],
        ["Quality", payload.featureQuality], ["Key Feature", payload.keyFeature],
    ]);
    if (id === "strategy") return fields([
        ["Direction", direction(payload.direction)], ["Confidence", payload.confidence],
        ["Execution Allowed", payload.executionAllowed],
        ["Suppression Reason", payload.suppressionReason], ["Result", payload.result],
    ]);
    if (id === "ai-review") return fields([
        ["Final Direction", direction(payload.direction)], ["Bias", payload.bias],
        ["Momentum", payload.momentum], ["Imbalance", payload.imbalance],
        ["Confidence", payload.confidence], ["Review Reason", payload.reason],
    ]);
    if (id === "governance") return fields([
        ["Execution Enabled", payload.execution_enabled ?? payload.executionEnabled],
        ["Outcome", payload.outcome], ["Block Reason", payload.blockReason],
        ["Safety Mode", payload.safetyMode],
    ]);
    return fields([
        ["Status", payload.status], ["Mode", engine.dataset?.tradeMode], ["Side", payload.side],
        ["Quantity", payload.quantity], ["Price", payload.price ?? payload.entryPrice ?? payload.exitPrice],
        ["Order ID", payload.orderId ?? payload.clientOrderId],
        ["Position", projection.positionContext?.status], ["Reason", payload.reason],
    ]);
};

const explicitStatus = (id, event, strategyDirection) => {
    const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
    const text = [payload.status, payload.result, payload.outcome, payload.reason]
        .filter((value) => typeof value === "string").join(" ").toUpperCase();
    if (event?.eventType === "EXECUTION_REJECTED" || /ERROR|FAILED|FAILURE/.test(text)) {
        return "error";
    }
    if (id === "strategy" && (payload.executionAllowed === false
        || (direction(payload.direction) === "HOLD" && payload.suppressionReason))) return "blocked";
    if (id === "ai-review" && strategyDirection !== "HOLD"
        && direction(payload.direction) === "HOLD") return "blocked";
    if (id === "governance" && (payload.execution_enabled === false
        || payload.executionEnabled === false || /BLOCK|REJECT|DENIED/.test(text))) return "blocked";
    return null;
};

export function buildDecisionRailwayModel(replayEngine) {
    const engine = replayEngine && typeof replayEngine === "object" ? replayEngine : {};
    const projection = engine.projection && typeof engine.projection === "object"
        ? engine.projection
        : {};
    const currentStationId = eventStation(projection.currentEvent);
    const reached = DEFINITIONS.map(({ id }) => stationEvents(projection, id));
    const lastReachedIndex = reached.findLastIndex((events) => events.length > 0);
    const strategyEvent = projection.decisionContext?.strategyDecision ?? reached[3].at(-1) ?? null;
    const aiEvent = projection.decisionContext?.aiDecision ?? reached[4].at(-1) ?? null;
    const governanceEvent = projection.decisionContext?.governanceDecision ?? reached[5].at(-1) ?? null;
    const executionEvent = projection.decisionContext?.executionEvent ?? reached[6].at(-1) ?? null;
    const strategyDirection = direction(strategyEvent?.payload?.direction);
    const aiDirection = direction(aiEvent?.payload?.direction);

    const stations = DEFINITIONS.map((definition, index) => {
        const events = reached[index];
        const event = events.at(-1) ?? null;
        const forced = explicitStatus(definition.id, event, strategyDirection);
        let status = events.length === 0 ? "not_reached" : index < lastReachedIndex ? "completed" : "available";
        if (events.length > 0 && (!event || typeof event !== "object")) status = "unknown";
        if (definition.id === currentStationId && events.length > 0) status = "active";
        if (forced) status = forced;
        const secondaryValues = eventDetails(definition.id, event, engine, projection);
        return {
            ...definition,
            order: index + 1,
            status,
            statusLabel: status.replaceAll("_", " ").toUpperCase(),
            reached: events.length > 0,
            active: status === "active",
            timestamp: event?.timestamp ?? null,
            timestampLabel: timestampLabel(event?.timestamp),
            primaryValue: secondaryValues[0]?.value ?? DASH,
            secondaryValues,
            reason: safeValue(event?.payload?.suppressionReason
                ?? event?.payload?.blockReason ?? event?.payload?.reason),
            eventId: safeValue(event?.id),
            dataQuality: safeValue(event?.dataQuality) === DASH ? "UNKNOWN" : event.dataQuality,
            rawContext: events,
        };
    });

    const governancePayload = governanceEvent?.payload ?? {};
    const governanceResult = governanceEvent
        ? (governancePayload.execution_enabled === false
            || governancePayload.executionEnabled === false
            || /BLOCK|REJECT|DENIED/.test(String(governancePayload.outcome ?? "").toUpperCase())
            ? "BLOCKED" : safeValue(governancePayload.outcome ?? "ALLOWED"))
        : DASH;
    const aiRelation = !strategyEvent || !aiEvent ? DASH
        : strategyDirection === "HOLD" && aiDirection !== "HOLD" ? "CONFLICT"
            : strategyDirection !== "HOLD" && aiDirection === "HOLD" ? "DOWNGRADED_TO_HOLD"
                : strategyDirection === aiDirection ? (aiDirection === "HOLD" ? "AGREED_HOLD" : "ACCEPTED")
                    : "CONFLICT";
    const finalExecution = executionEvent
        ? safeValue(executionEvent.payload?.status ?? executionEvent.eventType)
        : governanceResult === "BLOCKED" ? "NOT SENT" : DASH;

    return {
        stations,
        summary: {
            reachedStations: stations.filter(({ reached: value }) => value).length,
            totalStations: stations.length,
            replayCursor: engine.replayCursor ?? DASH,
        },
        currentStationId,
        finalDecision: {
            strategy: strategyEvent ? strategyDirection : DASH,
            ai: aiEvent ? aiDirection : DASH,
            aiRelation,
            governance: governanceResult,
            execution: finalExecution,
        },
        finalExecution,
        hasData: stations.some(({ reached: value }) => value),
        dataQuality: typeof projection.dataQuality === "string" ? projection.dataQuality : "UNKNOWN",
    };
}
