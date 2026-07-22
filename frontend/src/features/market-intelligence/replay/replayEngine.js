import { projectReplayState } from "./replayProjection.js";
import {
    REPLAY_MACHINE_EVENTS as MACHINE_EVENTS,
    REPLAY_STATES,
    createInitialReplayMachineState,
    transitionReplayState,
} from "./replayStateMachine.js";
import { sortReplayEvents } from "./replayUtils.js";
import { validateReplayDataset, validateReplayEvent } from "./replayValidation.js";

export const REPLAY_ENGINE_COMMANDS = Object.freeze({
    LOAD_DATASET: "LOAD_DATASET",
    LOAD_FAILURE: "LOAD_FAILURE",
    PLAY: "PLAY",
    PAUSE: "PAUSE",
    STEP_FORWARD: "STEP_FORWARD",
    STEP_BACKWARD: "STEP_BACKWARD",
    SEEK: "SEEK",
    JUMP_TO_START: "JUMP_TO_START",
    JUMP_TO_END: "JUMP_TO_END",
    REACH_END: "REACH_END",
    RESTART: "RESTART",
    RESET: "RESET",
    RETRY: "RETRY",
});

const C = REPLAY_ENGINE_COMMANDS;
const M = MACHINE_EVENTS;
const S = REPLAY_STATES;
const KNOWN_COMMANDS = new Set(Object.values(C));
const PLAYBACK_STATES = new Set([S.REPLAY_READY, S.PLAYING, S.PAUSED, S.COMPLETED]);

const toEpoch = (timestamp) => {
    if (typeof timestamp === "number") return Number.isFinite(timestamp) ? timestamp : null;
    if (typeof timestamp !== "string" || timestamp.trim() === "") return null;
    const epoch = Date.parse(timestamp);
    return Number.isFinite(epoch) ? epoch : null;
};

const eventTimestamps = (dataset) => {
    if (!Array.isArray(dataset?.events)) return [];
    const timestamps = sortReplayEvents(dataset.events.filter(
        (event) => validateReplayEvent(event).valid,
    )).map((event) => event.timestamp);
    return timestamps.filter((timestamp, index) => (
        index === 0 || toEpoch(timestamp) !== toEpoch(timestamps[index - 1])
    ));
};

const replayBounds = (dataset) => {
    const timestamps = eventTimestamps(dataset);
    const declaredStart = toEpoch(dataset?.startedAt);
    const declaredEnd = toEpoch(dataset?.endedAt);
    return {
        start: declaredStart === null ? timestamps[0] ?? null : dataset.startedAt,
        end: declaredEnd === null ? timestamps.at(-1) ?? null : dataset.endedAt,
        timestamps,
    };
};

const validationAllowsBoundaryFallback = (validation, dataset) => {
    if (validation.valid) return true;
    const timestamps = eventTimestamps(dataset);
    return timestamps.length > 0 && validation.errors.every((error) => (
        (error.path === "startedAt" || error.path === "endedAt")
        && error.code === "INVALID_TIMESTAMP"
    ));
};

const transition = (machine, type, payload) => (
    transitionReplayState(machine, { type, payload })
);

const completeMachine = (machine) => {
    if (machine.state === S.COMPLETED) return machine;
    const playing = machine.state === S.PLAYING ? machine : transition(machine, M.PLAY);
    return playing.accepted ? transition(playing, M.REACH_END) : playing;
};

const commandTypeOf = (command) => (
    command !== null
    && typeof command === "object"
    && !Array.isArray(command)
    && typeof command.type === "string"
        ? command.type
        : null
);

const rejection = (engineState, reason) => ({
    ...engineState,
    accepted: false,
    rejectionReason: reason,
});

const accepted = (engineState, commandType, updates) => ({
    ...engineState,
    ...updates,
    lastCommand: commandType,
    accepted: true,
    rejectionReason: null,
});

export function createInitialReplayEngineState() {
    return {
        dataset: null,
        replayCursor: null,
        machine: createInitialReplayMachineState(),
        projection: projectReplayState(null, null),
        validation: null,
        engineError: null,
        lastCommand: null,
        accepted: true,
        rejectionReason: null,
    };
}

const loadFailureState = (engineState, commandType, payload, validation = null) => {
    let machine = createInitialReplayMachineState();
    machine = transition(machine, M.SELECT_POSITION);
    machine = transition(machine, M.START_LOADING);
    machine = transition(machine, M.LOAD_FAILURE, payload);
    return accepted(engineState, commandType, {
        dataset: null,
        replayCursor: null,
        machine,
        projection: projectReplayState(null, null),
        validation,
        engineError: machine.error,
    });
};

const seek = (engineState, commandType, requestedTimestamp) => {
    if (!engineState.dataset) return rejection(engineState, "DATASET_NOT_LOADED");
    if (!PLAYBACK_STATES.has(engineState.machine.state)) {
        return rejection(engineState, "COMMAND_NOT_ALLOWED_IN_CURRENT_STATE");
    }
    const requestedEpoch = toEpoch(requestedTimestamp);
    if (requestedEpoch === null) return rejection(engineState, "INVALID_SEEK_TIMESTAMP");
    const bounds = replayBounds(engineState.dataset);
    const startEpoch = toEpoch(bounds.start);
    const endEpoch = toEpoch(bounds.end);
    if (startEpoch === null || endEpoch === null) {
        return rejection(engineState, "REPLAY_RANGE_UNAVAILABLE");
    }
    const clamped = requestedEpoch <= startEpoch
        ? bounds.start
        : requestedEpoch >= endEpoch ? bounds.end : requestedTimestamp;
    const seeking = transition(engineState.machine, M.SEEK);
    if (!seeking.accepted) return rejection(engineState, seeking.rejectionReason);
    const machine = transition(seeking, M.SEEK_COMPLETE);
    return accepted(engineState, commandType, {
        replayCursor: clamped,
        machine,
        projection: projectReplayState(engineState.dataset, clamped),
    });
};

export function canApplyReplayCommand(engineState, command) {
    return applyReplayCommand(engineState, command).accepted;
}

export function applyReplayCommand(engineState, command) {
    if (engineState === null || typeof engineState !== "object" || Array.isArray(engineState)) {
        return rejection(createInitialReplayEngineState(), "INVALID_ENGINE_STATE");
    }
    const commandType = commandTypeOf(command);
    if (commandType === null) return rejection(engineState, "INVALID_COMMAND");
    if (!KNOWN_COMMANDS.has(commandType)) return rejection(engineState, "UNKNOWN_COMMAND");

    if (commandType === C.RESET) {
        return {
            ...createInitialReplayEngineState(),
            machine: transition(engineState.machine, M.RESET),
            lastCommand: C.RESET,
        };
    }

    if (commandType === C.LOAD_DATASET) {
        const dataset = command.payload?.dataset;
        let machine = createInitialReplayMachineState();
        machine = transition(machine, M.SELECT_POSITION);
        machine = transition(machine, M.START_LOADING);
        const validation = validateReplayDataset(dataset);
        if (!validationAllowsBoundaryFallback(validation, dataset)) {
            machine = transition(machine, M.LOAD_FAILURE, {
                code: "INVALID_REPLAY_DATASET",
                message: "Replay dataset validation failed.",
            });
            return accepted(engineState, commandType, {
                dataset: null,
                replayCursor: null,
                machine,
                projection: projectReplayState(null, null),
                validation,
                engineError: machine.error,
            });
        }
        machine = transition(machine, M.LOAD_SUCCESS);
        const bounds = replayBounds(dataset);
        const cursor = bounds.timestamps.length === 0 ? null : bounds.start;
        return accepted(engineState, commandType, {
            dataset,
            replayCursor: cursor,
            machine,
            projection: projectReplayState(dataset, cursor),
            validation,
            engineError: null,
        });
    }

    if (commandType === C.LOAD_FAILURE) {
        return loadFailureState(engineState, commandType, command.payload);
    }

    if (commandType === C.RETRY) {
        const machine = transition(engineState.machine, M.RETRY);
        if (!machine.accepted) return rejection(engineState, machine.rejectionReason);
        return accepted(engineState, commandType, { machine, engineError: null });
    }

    if (commandType === C.PLAY || commandType === C.PAUSE) {
        const machineEvent = commandType === C.PLAY ? M.PLAY : M.PAUSE;
        const machine = transition(engineState.machine, machineEvent);
        if (!machine.accepted) return rejection(engineState, machine.rejectionReason);
        return accepted(engineState, commandType, {
            machine,
            projection: projectReplayState(engineState.dataset, engineState.replayCursor),
        });
    }

    if (commandType === C.SEEK) {
        return seek(engineState, commandType, command.payload?.timestamp);
    }

    if (commandType === C.JUMP_TO_START) {
        if (!engineState.dataset) return rejection(engineState, "DATASET_NOT_LOADED");
        return seek(engineState, commandType, replayBounds(engineState.dataset).start);
    }

    if (commandType === C.JUMP_TO_END || commandType === C.REACH_END) {
        if (!engineState.dataset) return rejection(engineState, "DATASET_NOT_LOADED");
        if (commandType === C.REACH_END && engineState.machine.state !== S.PLAYING) {
            return rejection(engineState, "COMMAND_NOT_ALLOWED_IN_CURRENT_STATE");
        }
        if (commandType === C.JUMP_TO_END && !PLAYBACK_STATES.has(engineState.machine.state)) {
            return rejection(engineState, "COMMAND_NOT_ALLOWED_IN_CURRENT_STATE");
        }
        const end = replayBounds(engineState.dataset).end;
        if (toEpoch(end) === null) return rejection(engineState, "REPLAY_RANGE_UNAVAILABLE");
        const machine = completeMachine(engineState.machine);
        if (!machine.accepted && machine.state !== S.COMPLETED) {
            return rejection(engineState, machine.rejectionReason);
        }
        return accepted(engineState, commandType, {
            replayCursor: end,
            machine,
            projection: projectReplayState(engineState.dataset, end),
        });
    }

    if (commandType === C.RESTART) {
        if (!engineState.dataset) return rejection(engineState, "DATASET_NOT_LOADED");
        const machine = transition(engineState.machine, M.RESTART);
        if (!machine.accepted) return rejection(engineState, machine.rejectionReason);
        const start = replayBounds(engineState.dataset).start;
        return accepted(engineState, commandType, {
            replayCursor: start,
            machine,
            projection: projectReplayState(engineState.dataset, start),
        });
    }

    if (commandType === C.STEP_FORWARD) {
        if (!engineState.dataset) return rejection(engineState, "DATASET_NOT_LOADED");
        if (![S.REPLAY_READY, S.PAUSED].includes(engineState.machine.state)) {
            return rejection(engineState, "COMMAND_NOT_ALLOWED_IN_CURRENT_STATE");
        }
        const currentEpoch = toEpoch(engineState.replayCursor);
        const next = replayBounds(engineState.dataset).timestamps.find(
            (timestamp) => toEpoch(timestamp) > currentEpoch,
        );
        const stepped = transition(engineState.machine, M.STEP);
        if (!stepped.accepted) return rejection(engineState, stepped.rejectionReason);
        if (next === undefined) {
            const machine = completeMachine(stepped);
            return accepted(engineState, commandType, { machine });
        }
        return accepted(engineState, commandType, {
            replayCursor: next,
            machine: stepped,
            projection: projectReplayState(engineState.dataset, next),
        });
    }

    if (commandType === C.STEP_BACKWARD) {
        if (!engineState.dataset) return rejection(engineState, "DATASET_NOT_LOADED");
        if (![S.REPLAY_READY, S.PAUSED, S.COMPLETED].includes(engineState.machine.state)) {
            return rejection(engineState, "COMMAND_NOT_ALLOWED_IN_CURRENT_STATE");
        }
        const currentEpoch = toEpoch(engineState.replayCursor);
        const previous = replayBounds(engineState.dataset).timestamps.findLast(
            (timestamp) => toEpoch(timestamp) < currentEpoch,
        );
        if (previous === undefined) return rejection(engineState, "ALREADY_AT_START");
        const machine = engineState.machine.state === S.COMPLETED
            ? transition(engineState.machine, M.RESTART)
            : transition(engineState.machine, M.STEP);
        if (!machine.accepted) return rejection(engineState, machine.rejectionReason);
        return accepted(engineState, commandType, {
            replayCursor: previous,
            machine,
            projection: projectReplayState(engineState.dataset, previous),
        });
    }

    return rejection(engineState, "UNKNOWN_COMMAND");
}
