const DASH = "—";

const display = (value) => {
    if (typeof value === "string" && value !== "") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
    return DASH;
};

const timestamp = (value) => {
    const epoch = typeof value === "number" ? value : Date.parse(value);
    return Number.isFinite(epoch) ? new Date(epoch).toISOString() : DASH;
};

const payloadOf = (event) => event?.payload && typeof event.payload === "object"
    && !Array.isArray(event.payload) ? event.payload : {};

const positionItem = (event, phase) => {
    if (!event || typeof event !== "object" || Array.isArray(event)) return null;
    const payload = payloadOf(event);
    return {
        id: display(event.id),
        phase,
        eventType: display(event.eventType),
        timestamp: timestamp(event.timestamp),
        sequence: Number.isInteger(event.sequence) ? event.sequence : null,
        side: display(payload.side),
        price: display(payload.price ?? payload.entryPrice ?? payload.exitPrice ?? payload.markPrice),
        quantity: display(payload.quantity),
        unrealizedPnl: display(payload.unrealizedPnl),
        realizedPnl: display(payload.realizedPnl),
        reason: display(payload.reason),
        dataQuality: display(event.dataQuality) === DASH ? "UNKNOWN" : event.dataQuality,
    };
};

export function buildReplayPositionTimelineModel(replayEngine) {
    const context = replayEngine?.projection?.positionContext;
    const items = [
        positionItem(context?.openedEvent, "OPEN"),
        positionItem(context?.latestUpdateEvent, "UPDATE"),
        positionItem(context?.closedEvent, "CLOSE"),
    ].filter(Boolean);
    return {
        positionId: display(context?.positionId),
        status: display(context?.status),
        items,
        count: items.length,
        isEmpty: items.length === 0,
        replayCursor: display(replayEngine?.replayCursor),
    };
}
