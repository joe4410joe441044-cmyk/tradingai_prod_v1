export const RECORDER_ERROR_CODE = Object.freeze({
    UNKNOWN: "RECORDER_UNKNOWN",
    NETWORK: "RECORDER_NETWORK",
    TIMEOUT: "RECORDER_TIMEOUT",
    SERVER: "RECORDER_SERVER",
    NOT_IMPLEMENTED: "RECORDER_NOT_IMPLEMENTED",
    PARSE: "RECORDER_PARSE",
    UNSUPPORTED_SOURCE: "RECORDER_UNSUPPORTED_SOURCE",
    CONTROL_DISABLED: "RECORDER_CONTROL_DISABLED",
    CONTROL_UNAUTHENTICATED: "RECORDER_CONTROL_UNAUTHENTICATED",
    CONTROL_CONFLICT: "RECORDER_CONTROL_CONFLICT",
    CONTROL_RATE_LIMITED: "RECORDER_CONTROL_RATE_LIMITED",
});

export function createRecorderError(code, message, { retryable, source } = {}) {
    return Object.freeze({
        code: code ?? RECORDER_ERROR_CODE.UNKNOWN,
        message: String(message ?? "An unexpected error occurred"),
        retryable: Boolean(retryable),
        source: source ?? null,
    });
}

export function createRecorderNotImplementedError(operation) {
    return createRecorderError(
        RECORDER_ERROR_CODE.NOT_IMPLEMENTED,
        `${operation}: Not implemented`,
        { retryable: false, source: "client" },
    );
}

export function createRecorderUnsupportedSourceError(source) {
    return createRecorderError(
        RECORDER_ERROR_CODE.UNSUPPORTED_SOURCE,
        `Data source not supported: ${source}`,
        { retryable: false, source: "client" },
    );
}

export function isRecorderError(value) {
    return (
        value !== null
        && typeof value === "object"
        && Object.prototype.hasOwnProperty.call(value, "code")
        && Object.prototype.hasOwnProperty.call(value, "message")
        && Object.prototype.hasOwnProperty.call(value, "retryable")
        && Object.prototype.hasOwnProperty.call(value, "source")
    );
}
