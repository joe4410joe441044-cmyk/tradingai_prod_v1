import { getReplayRange, sortReplayEvents } from "./replayUtils.js";
import { REPLAY_MARKER_TYPES } from "./replayConstants.js";
import { validateReplayEvent, validateReplayMarker } from "./replayValidation.js";

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

const markerPayload = (event) => event?.payload && typeof event.payload === "object"
    && !Array.isArray(event.payload) ? event.payload : {};
const markerType = (value) => {
    const normalized = typeof value === "string" ? value.trim().toUpperCase().replaceAll(" ", "_") : "";
    if (["BUY", "LONG"].includes(normalized)) return "BUY";
    if (["SELL", "SHORT"].includes(normalized)) return "SELL";
    if (normalized === "ENTRY") return "ENTRY";
    if (normalized === "EXIT") return "EXIT";
    if (normalized === "REDUCE_ONLY") return "REDUCE_ONLY";
    if (normalized === "FLATTEN") return "FLATTEN";
    if (["ORDER_FAILED", "ORDER_ERROR"].includes(normalized)) return "ORDER_FAILED";
    if (["GOVERNANCE_BLOCK", "BLOCKED"].includes(normalized)) return "GOVERNANCE_BLOCK";
    return "UNKNOWN";
};
const markerSide = (value) => {
    const normalized = typeof value === "string" ? value.trim().toUpperCase() : "";
    if (["BUY", "LONG"].includes(normalized)) return "BUY";
    if (["SELL", "SHORT"].includes(normalized)) return "SELL";
    return null;
};
const latestPayloadValue = (events, fields, accept = () => true) => {
    for (let index = events.length - 1; index >= 0; index -= 1) {
        const payload = markerPayload(events[index]);
        for (const field of fields) {
            if (Object.hasOwn(payload, field) && accept(payload[field])) return payload[field];
        }
    }
    return null;
};
const markerQuality = (events) => events.reduce((worst, event) => (
    QUALITY_PRIORITY[event.dataQuality] > QUALITY_PRIORITY[worst] ? event.dataQuality : worst
), "VALID");
const isBlockedEvent = (event) => event.eventType === "GOVERNANCE_DECISION"
    && /BLOCK|REJECT|DENIED/.test(String(markerPayload(event).outcome ?? "").toUpperCase());

export function projectReplayMarkers(visibleEvents) {
    const orderedEvents = sortReplayEvents(Array.isArray(visibleEvents) ? visibleEvents : []);
    return groupEventsByReference(orderedEvents, "markerId").map(({ markerId, events }) => {
        const latest = events.at(-1);
        const explicitType = latestPayloadValue(events, ["markerType"], (value) => typeof value === "string");
        const derivedType = latest.eventType === "POSITION_OPENED" ? "ENTRY"
            : latest.eventType === "POSITION_CLOSED" ? "EXIT"
                : events.some((event) => event.eventType === "EXECUTION_REJECTED") ? "ORDER_FAILED"
                    : events.some(isBlockedEvent) ? "GOVERNANCE_BLOCK" : "UNKNOWN";
        const type = explicitType === null ? derivedType : markerType(explicitType);
        const price = latestPayloadValue(events, ["price", "entryPrice", "exitPrice"], Number.isFinite);
        const quantity = latestPayloadValue(events, ["quantity"], Number.isFinite);
        const sideValue = latestPayloadValue(events, ["side"], (value) => typeof value === "string");
        const reason = latestPayloadValue(events, ["reason", "blockReason"], (value) => typeof value === "string");
        const orderId = latestPayloadValue(events, ["orderId", "clientOrderId"], (value) => typeof value === "string");
        const reduceOnly = events.some((event) => markerPayload(event).reduceOnly === true) || type === "REDUCE_ONLY";
        const flatten = events.some((event) => markerPayload(event).flatten === true) || type === "FLATTEN";
        const blocked = events.some((event) => markerPayload(event).blocked === true || isBlockedEvent(event))
            || type === "GOVERNANCE_BLOCK";
        const failed = events.some((event) => markerPayload(event).failed === true
            || event.eventType === "EXECUTION_REJECTED") || type === "ORDER_FAILED";
        const marker = {
            id: markerId,
            markerId,
            type,
            timestamp: latest.timestamp,
            sequence: latest.sequence,
            price,
            quantity,
            side: markerSide(sideValue),
            reason,
            orderId,
            reduceOnly,
            flatten,
            blocked,
            failed,
            source: latest.source,
            eventType: latest.eventType,
            dataQuality: markerQuality(events),
            eventId: latest.id,
            tradeId: latestPayloadValue(events, ["tradeId"], (value) => typeof value === "string"),
            decisionId: latest.decisionId ?? null,
            positionId: latest.positionId ?? null,
            stationId: latest.stationId ?? null,
        };
        return validateReplayMarker(marker).valid ? marker : null;
    }).filter(Boolean);
}

const summarizeMarkers = (markers) => {
    const byType = Object.fromEntries(REPLAY_MARKER_TYPES.map((type) => [type, 0]));
    for (const marker of markers) byType[marker.type] += 1;
    return {
        total: markers.length,
        byType,
        buy: byType.BUY,
        sell: byType.SELL,
        entry: byType.ENTRY,
        exit: byType.EXIT,
        reduceOnly: markers.filter((marker) => marker.reduceOnly).length,
        flatten: markers.filter((marker) => marker.flatten).length,
        failed: markers.filter((marker) => marker.failed).length,
        blocked: markers.filter((marker) => marker.blocked).length,
        unknown: byType.UNKNOWN,
    };
};

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
    const markers = projectReplayMarkers(visibleEvents);
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
            count: markers.length,
            summary: summarizeMarkers(markers),
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
