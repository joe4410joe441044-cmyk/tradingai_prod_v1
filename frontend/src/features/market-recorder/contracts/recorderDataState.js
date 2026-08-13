export const DATA_STATE = Object.freeze({
    IDLE: "idle",
    LOADING: "loading",
    SUCCESS: "success",
    EMPTY: "empty",
    ERROR: "error",
    UNAVAILABLE: "unavailable",
});

export const DATA_STATE_VALUES = new Set(Object.values(DATA_STATE));

export function createIdleDataState() {
    return {
        status: DATA_STATE.IDLE,
        data: null,
        error: null,
        updatedAt: null,
        isLoading: false,
        isSuccess: false,
        isEmpty: false,
        isError: false,
        isUnavailable: false,
    };
}

export function createLoadingDataState() {
    return {
        status: DATA_STATE.LOADING,
        data: null,
        error: null,
        updatedAt: null,
        isLoading: true,
        isSuccess: false,
        isEmpty: false,
        isError: false,
        isUnavailable: false,
    };
}

export function createSuccessDataState(data) {
    return {
        status: DATA_STATE.SUCCESS,
        data,
        error: null,
        updatedAt: Date.now(),
        isLoading: false,
        isSuccess: true,
        isEmpty: false,
        isError: false,
        isUnavailable: false,
    };
}

export function createEmptyDataState() {
    return {
        status: DATA_STATE.EMPTY,
        data: null,
        error: null,
        updatedAt: Date.now(),
        isLoading: false,
        isSuccess: false,
        isEmpty: true,
        isError: false,
        isUnavailable: false,
    };
}

export function createErrorDataState(error) {
    return {
        status: DATA_STATE.ERROR,
        data: null,
        error: error ?? null,
        updatedAt: Date.now(),
        isLoading: false,
        isSuccess: false,
        isEmpty: false,
        isError: true,
        isUnavailable: false,
    };
}

export function createUnavailableDataState() {
    return {
        status: DATA_STATE.UNAVAILABLE,
        data: null,
        error: null,
        updatedAt: Date.now(),
        isLoading: false,
        isSuccess: false,
        isEmpty: false,
        isError: false,
        isUnavailable: true,
    };
}

export function isValidDataState(state) {
    return typeof state === "string" && DATA_STATE_VALUES.has(state);
}
