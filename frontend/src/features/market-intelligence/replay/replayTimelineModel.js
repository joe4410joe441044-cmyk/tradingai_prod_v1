const DASH = "—";
const STATUS = Object.freeze({
    PAST: "past",
    CURRENT: "current",
    FUTURE: "future",
    UNKNOWN: "unknown",
});

const normalizeTimestamp = (timestamp) => {
    const epoch = typeof timestamp === "number" ? timestamp : Date.parse(timestamp);
    if (!Number.isFinite(epoch)) return null;
    return { epoch, label: new Date(epoch).toISOString() };
};

const itemStatus = (item) => {
    if (item?.isCurrent === true) return STATUS.CURRENT;
    if (item?.isPast === true) return STATUS.PAST;
    if (item?.isFuture === true) return STATUS.FUTURE;
    return STATUS.UNKNOWN;
};

const groupStatus = (items) => {
    if (items.some(({ status }) => status === STATUS.CURRENT)) return STATUS.CURRENT;
    if (items.length > 0 && items.every(({ status }) => status === STATUS.PAST)) {
        return STATUS.PAST;
    }
    if (items.some(({ status }) => status === STATUS.FUTURE)) return STATUS.FUTURE;
    return STATUS.UNKNOWN;
};

export function buildReplayTimelineModel(replayEngine) {
    const engine = replayEngine && typeof replayEngine === "object" ? replayEngine : {};
    const projection = engine.projection && typeof engine.projection === "object"
        ? engine.projection
        : {};
    const timeline = Array.isArray(projection.timeline) ? projection.timeline : [];
    const keyOccurrences = new Map();

    const items = timeline.map((item, index) => {
        const value = item && typeof item === "object" ? item : {};
        const timestamp = normalizeTimestamp(value.timestamp);
        const baseId = typeof value.id === "string" && value.id !== ""
            ? value.id
            : `${value.timestamp ?? "invalid"}-${value.sequence ?? "none"}-${value.eventType ?? "unknown"}`;
        const occurrence = keyOccurrences.get(baseId) ?? 0;
        keyOccurrences.set(baseId, occurrence + 1);
        const status = itemStatus(value);
        return {
            id: occurrence === 0 ? baseId : `${baseId}--${occurrence + 1}`,
            eventId: typeof value.id === "string" && value.id !== "" ? value.id : DASH,
            eventType: typeof value.eventType === "string" && value.eventType !== ""
                ? value.eventType
                : "UNKNOWN_EVENT",
            timestamp: value.timestamp ?? null,
            timestampLabel: timestamp?.label ?? DASH,
            sequence: Number.isFinite(value.sequence) ? value.sequence : null,
            sequenceLabel: Number.isFinite(value.sequence) ? `#${value.sequence}` : DASH,
            status,
            statusLabel: status.toUpperCase(),
            dataQuality: typeof value.dataQuality === "string" && value.dataQuality !== ""
                ? value.dataQuality
                : "UNKNOWN",
            source: typeof value.source === "string" && value.source !== ""
                ? value.source
                : DASH,
            rawEvent: item,
            groupKey: timestamp ? `timestamp-${timestamp.epoch}` : `invalid-${index}`,
        };
    });

    const groupMap = new Map();
    for (const item of items) {
        if (!groupMap.has(item.groupKey)) {
            groupMap.set(item.groupKey, {
                id: item.groupKey,
                timestamp: item.timestamp,
                timestampLabel: item.timestampLabel,
                items: [],
            });
        }
        groupMap.get(item.groupKey).items.push(item);
    }
    const groups = [...groupMap.values()].map((group) => ({
        ...group,
        groupStatus: groupStatus(group.items),
        containsCurrent: group.items.some(({ status }) => status === STATUS.CURRENT),
        itemCount: group.items.length,
    }));
    const pastCount = items.filter(({ status }) => status === STATUS.PAST).length;
    const currentCount = items.filter(({ status }) => status === STATUS.CURRENT).length;
    const futureCount = items.filter(({ status }) => status === STATUS.FUTURE).length;
    const currentItem = items.find(({ status }) => status === STATUS.CURRENT) ?? null;

    return {
        items,
        groups,
        summary: {
            totalEvents: items.length,
            pastCount,
            currentCount,
            futureCount,
            reachedCount: pastCount + currentCount,
            groupCount: groups.length,
            currentEvent: currentItem?.eventType ?? DASH,
            replayCursor: engine.replayCursor ?? DASH,
        },
        currentItem,
        currentGroup: groups.find(({ containsCurrent }) => containsCurrent) ?? null,
        isEmpty: items.length === 0,
        hasCurrent: currentItem !== null,
        dataQuality: typeof projection.dataQuality === "string"
            ? projection.dataQuality
            : "UNKNOWN",
    };
}
