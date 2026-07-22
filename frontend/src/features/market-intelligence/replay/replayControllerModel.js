import { REPLAY_STATES } from "./replayStateMachine.js";

const S = REPLAY_STATES;
const DASH = "—";

const toEpoch = (timestamp) => {
    if (typeof timestamp === "number") return Number.isFinite(timestamp) ? timestamp : null;
    if (typeof timestamp !== "string" || timestamp.trim() === "") return null;
    const epoch = Date.parse(timestamp);
    return Number.isFinite(epoch) ? epoch : null;
};

const getBounds = (dataset) => {
    if (!dataset || typeof dataset !== "object") return null;
    const eventTimes = Array.isArray(dataset.events)
        ? dataset.events
            .map((event) => ({ value: event?.timestamp, epoch: toEpoch(event?.timestamp) }))
            .filter(({ epoch }) => epoch !== null)
            .sort((left, right) => left.epoch - right.epoch)
        : [];
    const startEpoch = toEpoch(dataset.startedAt);
    const endEpoch = toEpoch(dataset.endedAt);
    const start = startEpoch === null ? eventTimes[0] ?? null : {
        value: dataset.startedAt,
        epoch: startEpoch,
    };
    const end = endEpoch === null ? eventTimes.at(-1) ?? null : {
        value: dataset.endedAt,
        epoch: endEpoch,
    };
    return start && end ? { start, end } : null;
};

const normalizePercent = (percent) => {
    const numeric = typeof percent === "number" ? percent : Number(percent);
    if (!Number.isFinite(numeric)) return null;
    return Math.min(100, Math.max(0, numeric));
};

export function convertSeekPercentToTimestamp(dataset, percent) {
    const bounds = getBounds(dataset);
    const normalized = normalizePercent(percent);
    if (!bounds || normalized === null) return null;
    const epoch = bounds.start.epoch
        + ((bounds.end.epoch - bounds.start.epoch) * normalized) / 100;
    return Number.isFinite(epoch) ? new Date(epoch).toISOString() : null;
}

export function convertTimestampToSeekPercent(dataset, timestamp) {
    const bounds = getBounds(dataset);
    const cursorEpoch = toEpoch(timestamp);
    if (!bounds || cursorEpoch === null) return 0;
    const duration = bounds.end.epoch - bounds.start.epoch;
    if (duration <= 0) return 0;
    return Math.min(100, Math.max(0, ((cursorEpoch - bounds.start.epoch) / duration) * 100));
}

export function buildReplayControllerModel(replayEngine) {
    const engine = replayEngine && typeof replayEngine === "object" ? replayEngine : {};
    const dataset = engine.dataset ?? null;
    const projection = engine.projection ?? {};
    const machineState = engine.machine?.state ?? S.IDLE;
    const hasDataset = dataset !== null;
    const isReadyOrPaused = machineState === S.REPLAY_READY || machineState === S.PAUSED;
    const isNavigable = [S.REPLAY_READY, S.PLAYING, S.PAUSED, S.COMPLETED]
        .includes(machineState);
    const error = engine.engineError ?? engine.machine?.error ?? null;

    return {
        machineState,
        hasDataset,
        datasetSummary: {
            id: dataset?.datasetId ?? DASH,
            symbol: dataset?.symbol ?? DASH,
            exchange: dataset?.exchange ?? DASH,
            tradeMode: dataset?.tradeMode ?? DASH,
        },
        cursor: engine.replayCursor ?? DASH,
        currentEvent: {
            type: projection.currentEvent?.eventType ?? DASH,
            timestamp: projection.currentEvent?.timestamp ?? DASH,
        },
        progressPercent: Number.isFinite(projection.progress)
            ? Math.round(Math.min(1, Math.max(0, projection.progress)) * 100)
            : 0,
        reachedEventCount: Array.isArray(projection.visibleEvents)
            ? projection.visibleEvents.length
            : 0,
        totalEventCount: Array.isArray(dataset?.events) ? dataset.events.length : 0,
        accepted: engine.accepted !== false,
        error,
        rejectionReason: engine.accepted === false
            ? engine.rejectionReason ?? "UNKNOWN_REJECTION"
            : null,
        controls: {
            canLoad: [S.IDLE, S.REPLAY_ERROR, S.REPLAY_READY, S.PAUSED, S.COMPLETED]
                .includes(machineState)
                || (machineState === S.REPLAY_LOADING && !hasDataset),
            canPlay: isReadyOrPaused,
            canPause: machineState === S.PLAYING,
            canStepBackward: hasDataset
                && [S.REPLAY_READY, S.PAUSED, S.COMPLETED].includes(machineState)
                && projection.isAtStart !== true,
            canStepForward: hasDataset && isReadyOrPaused && projection.isAtEnd !== true,
            canJumpStart: hasDataset && isNavigable,
            canJumpEnd: hasDataset && isNavigable,
            canRestart: hasDataset && machineState === S.COMPLETED,
            canReset: machineState !== S.IDLE,
            canRetry: machineState === S.REPLAY_ERROR,
            canSeek: hasDataset && isNavigable && getBounds(dataset) !== null,
        },
    };
}
