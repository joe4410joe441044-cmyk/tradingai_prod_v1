import { getReplayRange, sortReplayEvents } from "./replayUtils.js";
import { validateReplayEvent } from "./replayValidation.js";

const QUALITY_PRIORITY = Object.freeze({
    VALID: 0,
    UNKNOWN: 1,
    PARTIAL: 2,
    STALE: 3,
    INVALID: 4,
});

const POSITION_EVENT_TYPES = new Set([
    "POSITION_OPENED",
    "POSITION_UPDATED",
    "POSITION_CLOSED",
]);
const DECISION_EVENT_TYPES = new Set([
    "STRATEGY_DECISION",
    "AI_DECISION",
    "GOVERNANCE_DECISION",
    "ORDER_SUBMITTED",
    "ORDER_ACKNOWLEDGED",
    "EXECUTION_REJECTED",
]);
const EXECUTION_EVENT_TYPES = new Set([
    "ORDER_SUBMITTED",
    "ORDER_ACKNOWLEDGED",
    "EXECUTION_REJECTED",
]);

const toEpoch = (timestamp) => {
    if (typeof timestamp === "number") {
        return Number.isFinite(timestamp) ? timestamp : null;
    }
    if (typeof timestamp !== "string" || timestamp.trim() === "") {
        return null;
    }
    const epoch = Date.parse(timestamp);
    return Number.isFinite(epoch) ? epoch : null;
};

const emptyPositionContext = () => ({
    positionId: null,
    status: null,
    openedEvent: null,
    latestUpdateEvent: null,
    closedEvent: null,
    isOpen: false,
    isClosed: false,
});

const emptyDecisionContext = () => ({
    decisionId: null,
    strategyDecision: null,
    aiDecision: null,
    governanceDecision: null,
    executionEvent: null,
});

function projectPositionContext(visibleEvents) {
    const latest = visibleEvents.findLast(
        (event) => event.positionId && POSITION_EVENT_TYPES.has(event.eventType),
    );
    if (!latest) return emptyPositionContext();

    const events = visibleEvents.filter((event) => event.positionId === latest.positionId);
    const openedEvent = events.findLast((event) => event.eventType === "POSITION_OPENED") ?? null;
    const latestUpdateEvent = events.findLast(
        (event) => event.eventType === "POSITION_UPDATED",
    ) ?? null;
    const closedEvent = events.findLast((event) => event.eventType === "POSITION_CLOSED") ?? null;

    return {
        positionId: latest.positionId,
        status: closedEvent ? "CLOSED" : openedEvent ? "OPEN" : null,
        openedEvent,
        latestUpdateEvent,
        closedEvent,
        isOpen: Boolean(openedEvent && !closedEvent),
        isClosed: Boolean(closedEvent),
    };
}

function projectDecisionContext(visibleEvents) {
    const latest = visibleEvents.findLast(
        (event) => event.decisionId && DECISION_EVENT_TYPES.has(event.eventType),
    );
    if (!latest) return emptyDecisionContext();

    const events = visibleEvents.filter((event) => event.decisionId === latest.decisionId);
    return {
        decisionId: latest.decisionId,
        strategyDecision: events.findLast(
            (event) => event.eventType === "STRATEGY_DECISION",
        ) ?? null,
        aiDecision: events.findLast((event) => event.eventType === "AI_DECISION") ?? null,
        governanceDecision: events.findLast(
            (event) => event.eventType === "GOVERNANCE_DECISION",
        ) ?? null,
        executionEvent: events.findLast(
            (event) => EXECUTION_EVENT_TYPES.has(event.eventType),
        ) ?? null,
    };
}

function groupEventsByReference(visibleEvents, referenceName) {
    const groups = new Map();
    for (const event of visibleEvents) {
        const id = event[referenceName];
        if (!id) continue;
        if (!groups.has(id)) groups.set(id, []);
        groups.get(id).push(event);
    }
    return [...groups].map(([id, events]) => ({ [referenceName]: id, events }));
}

function calculateProgress(range, cursorEpoch) {
    if (!range || cursorEpoch === null) return 0;
    const start = toEpoch(range.startedAt);
    const end = toEpoch(range.endedAt);
    if (start === null || end === null) return 0;
    if (cursorEpoch <= start) return 0;
    if (cursorEpoch >= end) return 1;
    if (end <= start) return cursorEpoch >= end ? 1 : 0;
    return Math.min(1, Math.max(0, (cursorEpoch - start) / (end - start)));
}

function aggregateDataQuality(visibleEvents) {
    if (visibleEvents.length === 0) return "UNKNOWN";
    return visibleEvents.reduce((worst, event) => (
        QUALITY_PRIORITY[event.dataQuality] > QUALITY_PRIORITY[worst]
            ? event.dataQuality
            : worst
    ), "VALID");
}

export function projectReplayState(dataset, replayCursor) {
    const cursorEpoch = toEpoch(replayCursor);
    const sourceEvents = dataset !== null
        && typeof dataset === "object"
        && !Array.isArray(dataset)
        && Array.isArray(dataset.events)
        ? dataset.events
        : [];
    const events = sortReplayEvents(sourceEvents.filter(
        (event) => validateReplayEvent(event).valid,
    ));
    const eventRange = getReplayRange(events);
    const declaredStart = toEpoch(dataset?.startedAt);
    const declaredEnd = toEpoch(dataset?.endedAt);
    const range = declaredStart !== null && declaredEnd !== null
        ? { startedAt: dataset.startedAt, endedAt: dataset.endedAt }
        : eventRange;
    const visibleEvents = cursorEpoch === null
        ? []
        : events.filter((event) => toEpoch(event.timestamp) <= cursorEpoch);
    const currentIndex = visibleEvents.length - 1;
    const currentEvent = currentIndex >= 0 ? visibleEvents[currentIndex] : null;
    const previousEvent = currentIndex > 0 ? visibleEvents[currentIndex - 1] : null;
    const nextEvent = currentEvent
        ? events[currentIndex + 1] ?? null
        : events[0] ?? null;
    const markers = groupEventsByReference(visibleEvents, "markerId");
    const stations = groupEventsByReference(visibleEvents, "stationId");
    const latestMarkerEvent = visibleEvents.findLast((event) => event.markerId) ?? null;
    const latestStationEvent = visibleEvents.findLast((event) => event.stationId) ?? null;
    const startEpoch = toEpoch(range?.startedAt);
    const endEpoch = toEpoch(range?.endedAt);

    return {
        replayCursor,
        range,
        progress: calculateProgress(range, cursorEpoch),
        currentEvent,
        previousEvent,
        nextEvent,
        visibleEvents,
        positionContext: projectPositionContext(visibleEvents),
        decisionContext: projectDecisionContext(visibleEvents),
        markerContext: {
            markers,
            selectedCandidate: null,
            latestMarker: latestMarkerEvent
                ? markers.find((marker) => marker.markerId === latestMarkerEvent.markerId) ?? null
                : null,
        },
        stationContext: {
            stations,
            latestStation: latestStationEvent
                ? stations.find((station) => station.stationId === latestStationEvent.stationId) ?? null
                : null,
        },
        timeline: events.map((event, index) => ({
            id: event.id,
            timestamp: event.timestamp,
            sequence: event.sequence,
            eventType: event.eventType,
            source: event.source,
            positionId: event.positionId,
            decisionId: event.decisionId,
            markerId: event.markerId,
            stationId: event.stationId,
            dataQuality: event.dataQuality,
            isPast: currentIndex >= 0 && index < currentIndex,
            isCurrent: currentIndex >= 0 && index === currentIndex,
            isFuture: currentIndex < 0 || index > currentIndex,
        })),
        isAtStart: cursorEpoch !== null && startEpoch !== null && cursorEpoch <= startEpoch,
        isAtEnd: cursorEpoch !== null && endEpoch !== null && cursorEpoch >= endEpoch,
        dataQuality: aggregateDataQuality(visibleEvents),
    };
}
