export const RECORDER_STATUS_STATE = Object.freeze({
    RUNNING: "RUNNING",
    STOPPED: "STOPPED",
    UNAVAILABLE: "UNAVAILABLE",
});

export const ARCHIVE_STATUS = Object.freeze({
    COMPLETED: "Completed",
    RECORDING: "Recording",
    FAILED: "Failed",
});

export const RECORDER_DATA_SOURCE = Object.freeze({
    MOCK: "mock",
    API: "api",
});

export const RECORDER_DATA_SOURCE_VALUES = new Set(Object.values(RECORDER_DATA_SOURCE));

export const RECORDER_CONTROL_CAPABILITY = Object.freeze({
    UNAVAILABLE: "unavailable",
    DISABLED: "disabled",
    AVAILABLE: "available",
});

export const RECORDER_CONTROL_STATE = Object.freeze({
    IDLE: "idle",
    STARTING: "starting",
    STOPPING: "stopping",
});

export const RECORDER_CONTROL_STATE_VALUES = new Set(Object.values(RECORDER_CONTROL_STATE));
