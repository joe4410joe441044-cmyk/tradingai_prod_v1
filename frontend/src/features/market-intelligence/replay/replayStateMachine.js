export const REPLAY_STATES = Object.freeze({
    IDLE: "IDLE",
    POSITION_SELECTED: "POSITION_SELECTED",
    REPLAY_LOADING: "REPLAY_LOADING",
    REPLAY_READY: "REPLAY_READY",
    PLAYING: "PLAYING",
    PAUSED: "PAUSED",
    SEEKING: "SEEKING",
    COMPLETED: "COMPLETED",
    REPLAY_ERROR: "REPLAY_ERROR",
});

export const REPLAY_MACHINE_EVENTS = Object.freeze({
    SELECT_POSITION: "SELECT_POSITION",
    START_LOADING: "START_LOADING",
    LOAD_SUCCESS: "LOAD_SUCCESS",
    LOAD_FAILURE: "LOAD_FAILURE",
    PLAY: "PLAY",
    PAUSE: "PAUSE",
    SEEK: "SEEK",
    SEEK_COMPLETE: "SEEK_COMPLETE",
    STEP: "STEP",
    REACH_END: "REACH_END",
    RESTART: "RESTART",
    RESET: "RESET",
    RETRY: "RETRY",
});

const S = REPLAY_STATES;
const E = REPLAY_MACHINE_EVENTS;
const KNOWN_STATES = new Set(Object.values(S));
const KNOWN_EVENTS = new Set(Object.values(E));
const DEFAULT_ERROR = Object.freeze({
    code: "REPLAY_LOAD_FAILED",
    message: "Replay loading failed.",
});

const TRANSITIONS = Object.freeze({
    [S.IDLE]: Object.freeze({
        [E.SELECT_POSITION]: S.POSITION_SELECTED,
    }),
    [S.POSITION_SELECTED]: Object.freeze({
        [E.START_LOADING]: S.REPLAY_LOADING,
    }),
    [S.REPLAY_LOADING]: Object.freeze({
        [E.LOAD_SUCCESS]: S.REPLAY_READY,
        [E.LOAD_FAILURE]: S.REPLAY_ERROR,
    }),
    [S.REPLAY_READY]: Object.freeze({
        [E.PLAY]: S.PLAYING,
        [E.SEEK]: S.SEEKING,
        [E.STEP]: S.REPLAY_READY,
    }),
    [S.PLAYING]: Object.freeze({
        [E.PAUSE]: S.PAUSED,
        [E.SEEK]: S.SEEKING,
        [E.REACH_END]: S.COMPLETED,
        [E.LOAD_FAILURE]: S.REPLAY_ERROR,
    }),
    [S.PAUSED]: Object.freeze({
        [E.PLAY]: S.PLAYING,
        [E.SEEK]: S.SEEKING,
        [E.STEP]: S.PAUSED,
    }),
    [S.SEEKING]: Object.freeze({
        [E.SEEK_COMPLETE]: S.REPLAY_READY,
    }),
    [S.COMPLETED]: Object.freeze({
        [E.RESTART]: S.REPLAY_READY,
        [E.SEEK]: S.SEEKING,
    }),
    [S.REPLAY_ERROR]: Object.freeze({
        [E.RETRY]: S.REPLAY_LOADING,
    }),
});

export function createInitialReplayMachineState() {
    return {
        state: S.IDLE,
        resumeState: null,
        error: null,
        transitionCount: 0,
        lastEvent: null,
    };
}

const eventTypeOf = (event) => (
    event !== null
    && typeof event === "object"
    && !Array.isArray(event)
    && typeof event.type === "string"
        ? event.type
        : null
);

const isValidMachineState = (machineState) => (
    machineState !== null
    && typeof machineState === "object"
    && !Array.isArray(machineState)
    && KNOWN_STATES.has(machineState.state)
    && Number.isInteger(machineState.transitionCount)
    && machineState.transitionCount >= 0
);

export function canTransitionReplayState(machineState, event) {
    if (!isValidMachineState(machineState)) return false;
    const eventType = eventTypeOf(event);
    if (!KNOWN_EVENTS.has(eventType)) return false;
    if (eventType === E.RESET) return true;
    return Object.hasOwn(TRANSITIONS[machineState.state], eventType);
}

const rejection = (machineState, reason) => ({
    ...machineState,
    accepted: false,
    rejectionReason: reason,
});

const normalizeError = (payload) => {
    const value = payload !== null && typeof payload === "object" && !Array.isArray(payload)
        ? payload
        : {};
    return {
        code: typeof value.code === "string" && value.code.trim() !== ""
            ? value.code
            : DEFAULT_ERROR.code,
        message: typeof value.message === "string" && value.message.trim() !== ""
            ? value.message
            : DEFAULT_ERROR.message,
    };
};

export function transitionReplayState(machineState, event) {
    if (!isValidMachineState(machineState)) {
        return rejection(
            createInitialReplayMachineState(),
            "INVALID_MACHINE_STATE",
        );
    }

    const eventType = eventTypeOf(event);
    if (eventType === null) return rejection(machineState, "INVALID_EVENT");
    if (!KNOWN_EVENTS.has(eventType)) return rejection(machineState, "UNKNOWN_EVENT");
    if (!canTransitionReplayState(machineState, event)) {
        return rejection(machineState, "EVENT_NOT_ALLOWED_IN_CURRENT_STATE");
    }

    if (eventType === E.RESET) {
        return {
            ...createInitialReplayMachineState(),
            lastEvent: E.RESET,
            accepted: true,
            rejectionReason: null,
        };
    }

    let nextState = TRANSITIONS[machineState.state][eventType];
    let resumeState = null;
    let error = machineState.error ?? null;

    if (eventType === E.SEEK) {
        resumeState = machineState.state;
    } else if (eventType === E.SEEK_COMPLETE) {
        if (machineState.resumeState === S.PAUSED) nextState = S.PAUSED;
        if (machineState.resumeState === S.PLAYING) nextState = S.PAUSED;
        if (machineState.resumeState === S.COMPLETED) nextState = S.COMPLETED;
    }

    if (eventType === E.LOAD_FAILURE) {
        error = normalizeError(event.payload);
    }
    if ([E.LOAD_SUCCESS, E.RETRY, E.RESTART].includes(eventType)) {
        error = null;
    }

    return {
        state: nextState,
        resumeState,
        error,
        transitionCount: machineState.transitionCount + 1,
        lastEvent: eventType,
        accepted: true,
        rejectionReason: null,
    };
}
