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

export function sortReplayEvents(events) {
    if (!Array.isArray(events)) {
        return [];
    }

    return events
        .map((event, index) => ({ event, index }))
        .sort((left, right) => {
            const leftTimestamp = toEpoch(left.event?.timestamp) ?? Number.POSITIVE_INFINITY;
            const rightTimestamp = toEpoch(right.event?.timestamp) ?? Number.POSITIVE_INFINITY;

            return leftTimestamp - rightTimestamp
                || (left.event?.sequence ?? Number.POSITIVE_INFINITY)
                    - (right.event?.sequence ?? Number.POSITIVE_INFINITY)
                || left.index - right.index;
        })
        .map(({ event }) => event);
}

export function findReplayEventById(events, eventId) {
    if (!Array.isArray(events) || eventId === null || eventId === undefined) {
        return null;
    }

    return events.find((event) => event?.id === eventId) ?? null;
}

export function findReplayEventAtOrBefore(events, replayCursor) {
    const cursor = toEpoch(replayCursor);
    if (cursor === null) {
        return null;
    }

    return sortReplayEvents(events).reduce((match, event) => {
        const timestamp = toEpoch(event?.timestamp);
        return timestamp !== null && timestamp <= cursor ? event : match;
    }, null);
}

export function findReplayEventAtOrAfter(events, replayCursor) {
    const cursor = toEpoch(replayCursor);
    if (cursor === null) {
        return null;
    }

    return sortReplayEvents(events).find((event) => {
        const timestamp = toEpoch(event?.timestamp);
        return timestamp !== null && timestamp >= cursor;
    }) ?? null;
}

export function getReplayRange(events) {
    const validEvents = sortReplayEvents(events).filter(
        (event) => toEpoch(event?.timestamp) !== null,
    );

    if (validEvents.length === 0) {
        return null;
    }

    return {
        startedAt: validEvents[0].timestamp,
        endedAt: validEvents[validEvents.length - 1].timestamp,
    };
}
