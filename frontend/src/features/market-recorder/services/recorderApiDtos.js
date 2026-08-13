import {
    createRecorderError,
    RECORDER_ERROR_CODE,
} from "../contracts/recorderError.js";
import { RECORDER_STATUS_STATE } from "../contracts/recorderContracts.js";

export const ARCHIVE_DTO_STATUS = Object.freeze({
    RECORDING: "recording",
    COMPLETED: "completed",
    FAILED: "failed",
});

const RECORDER_DTO_STATUS_VALUES = new Set(["RUNNING", "running", "RECORDING", "recording", "STOPPED", "stopped"]);
const DTO_STATUS_TO_DOMAIN = {
    RUNNING: RECORDER_STATUS_STATE.RUNNING,
    running: RECORDER_STATUS_STATE.RUNNING,
    RECORDING: RECORDER_STATUS_STATE.RUNNING,
    recording: RECORDER_STATUS_STATE.RUNNING,
    STOPPED: RECORDER_STATUS_STATE.STOPPED,
    stopped: RECORDER_STATUS_STATE.STOPPED,
};

const ARCHIVE_DTO_STATUS_VALUES = new Set(Object.values(ARCHIVE_DTO_STATUS));

function safeNumber(value, min) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
        return null;
    }
    if (value < (min ?? -Infinity)) {
        return null;
    }
    return value;
}

function safeBoolean(value) {
    if (typeof value === "boolean") {
        return value;
    }
    return false;
}

function safeString(value, allowedValues) {
    if (typeof value !== "string" || value.length === 0) {
        return null;
    }
    if (allowedValues && !allowedValues.has(value)) {
        return null;
    }
    if (value.includes("/") || value.includes("\\0") || value.includes("\x00")) {
        return null;
    }
    return value;
}

function safeIsoTimestamp(value) {
    if (typeof value !== "string" || value.length < 10) {
        return null;
    }
    const ms = Date.parse(value);
    if (!Number.isFinite(ms)) {
        return null;
    }
    return value;
}

function safeNonNegativeBytes(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
        return null;
    }
    return value;
}

function safeNonNegativeCount(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || !Number.isInteger(value)) {
        return null;
    }
    return value;
}

function safeStringArray(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter(function (v) { return typeof v === "string" && v.length > 0 && !v.includes("\x00"); })
        .map(function (v) {
            if (v.startsWith("/")) {
                var parts = v.split("/");
                return parts[parts.length - 1] || v;
            }
            return v;
        });
}

export function validateCommonResponse(response) {
    if (response === null || typeof response !== "object") {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: expected object",
            { retryable: false, source: "client" },
        );
    }
    if (response.ok !== true) {
        var errorMsg = "recorder_api_rejected";
        if (response.error && typeof response.error === "string") {
            errorMsg = "recorder_api_rejected: " + response.error;
        }
        throw createRecorderError(
            RECORDER_ERROR_CODE.SERVER,
            errorMsg,
            { retryable: false, source: "server" },
        );
    }
    if (!Object.prototype.hasOwnProperty.call(response, "data")) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: missing data",
            { retryable: false, source: "client" },
        );
    }
    return response.data;
}

function isPlainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function validateHealthDto(data) {
    if (!isPlainObject(data)) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: health data not object",
            { retryable: false, source: "client" },
        );
    }
    return data;
}

export function validateStatusDto(data) {
    if (!isPlainObject(data)) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: status data not object",
            { retryable: false, source: "client" },
        );
    }
    return data;
}

export function validateStorageDto(data) {
    if (!isPlainObject(data)) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: storage data not object",
            { retryable: false, source: "client" },
        );
    }
    return data;
}

export function validateArchivesDto(data) {
    if (!isPlainObject(data)) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: archives data not object",
            { retryable: false, source: "client" },
        );
    }
    if (!Array.isArray(data.entries)) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: entries not array",
            { retryable: false, source: "client" },
        );
    }
    return data;
}

export function validateControlDto(data) {
    if (!isPlainObject(data)) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: control data not object",
            { retryable: false, source: "client" },
        );
    }
    var legacy = typeof data.status === "string" && data.status.length > 0;
    var stateMachine = (
        typeof data.operation_id === "string" && data.operation_id.length > 0
        && typeof data.operation === "string" && data.operation.length > 0
        && typeof data.result === "string" && data.result.length > 0
    );
    if (!legacy && !stateMachine) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.PARSE,
            "recorder_api_invalid_response: control identity missing",
            { retryable: false, source: "client" },
        );
    }
    return data;
}

export function normalizeHealthDomain(dtoData) {
    return {
        status: safeString(dtoData.status),
        contractVersion: safeString(dtoData.contract_version),
        uptimeSeconds: safeNumber(dtoData.uptime_seconds, 0),
    };
}

export function normalizeStatusDomain(dtoData) {
    var status = RECORDER_STATUS_STATE.UNAVAILABLE;
    if (typeof dtoData.status === "string" && RECORDER_DTO_STATUS_VALUES.has(dtoData.status)) {
        status = DTO_STATUS_TO_DOMAIN[dtoData.status];
    }

    var activeFiles = safeStringArray(dtoData.active_files);

    return {
        status: status,
        uptimeSeconds: safeNumber(dtoData.uptime_seconds, 0),
        activeFiles: activeFiles,
        activeFileCount: activeFiles.length,
        connectionState: safeString(dtoData.connection_state),
        pid: safeNonNegativeCount(dtoData.pid),
        subscribedStreams: safeStringArray(dtoData.subscribed_streams),
        messagesReceived: safeNonNegativeCount(dtoData.messages_received),
        bytesReceived: safeNonNegativeBytes(dtoData.bytes_received),
        reconnectCount: safeNonNegativeCount(dtoData.reconnect_count),
        sequenceAnomalyCount: safeNonNegativeCount(dtoData.sequence_anomaly_count),
        lastMessageAt: safeIsoTimestamp(dtoData.last_message_at),
        lastError: typeof dtoData.last_error === "string" ? dtoData.last_error : null,
        processStartedAt: safeIsoTimestamp(dtoData.process_started_at),
        observedAt: safeIsoTimestamp(dtoData.observed_at),
    };
}

export function normalizeStorageDomain(dtoData) {
    return {
        totalBytes: safeNonNegativeBytes(dtoData.total_bytes),
        usedBytes: safeNonNegativeBytes(dtoData.used_bytes),
        freeBytes: safeNonNegativeBytes(dtoData.free_bytes),
        archiveBytes: safeNonNegativeBytes(dtoData.archive_bytes),
        activeBytes: safeNonNegativeBytes(dtoData.active_bytes),
        runtimeBytes: safeNonNegativeBytes(dtoData.runtime_bytes),
        manifestBytes: safeNonNegativeBytes(dtoData.manifest_bytes),
        usagePercent: safeNumber(dtoData.usage_percent, 0),
        quarantineCount: safeNonNegativeCount(dtoData.quarantine_count),
        filesystem: safeString(dtoData.filesystem),
        observedAt: safeIsoTimestamp(dtoData.observed_at),
    };
}

export function normalizeControlDomain(dtoData) {
    var status = safeString(dtoData.status);
    var result = safeString(dtoData.result);
    var successful = (
        result === "completed"
        || result === "success"
        || status === "started"
        || status === "stopped"
    );
    return {
        status: status,
        operationId: safeString(dtoData.operation_id),
        operation: safeString(dtoData.operation),
        result: result,
        previousState: safeString(dtoData.previous_state),
        currentState: safeString(dtoData.current_state),
        requestedAt: safeIsoTimestamp(dtoData.requested_at),
        completedAt: safeIsoTimestamp(dtoData.completed_at),
        plan: isPlainObject(dtoData.plan) || typeof dtoData.plan === "string"
            ? dtoData.plan : null,
        eventCount: safeNonNegativeCount(dtoData.event_count),
        message: typeof dtoData.message === "string" ? dtoData.message : null,
        successful: successful,
    };
}

export function normalizeArchiveEntryDomain(dtoEntry) {
    if (dtoEntry === null || typeof dtoEntry !== "object") {
        return null;
    }

    var verificationStatus = ARCHIVE_DTO_STATUS.COMPLETED;
    if (typeof dtoEntry.verification_status === "string" && ARCHIVE_DTO_STATUS_VALUES.has(dtoEntry.verification_status)) {
        verificationStatus = dtoEntry.verification_status;
    }

    return {
        id: safeString(dtoEntry.id) || ("entry-" + Math.random().toString(36).slice(2, 10)),
        stream: safeString(dtoEntry.stream),
        symbol: safeString(dtoEntry.symbol),
        period: safeString(dtoEntry.period),
        startTime: safeIsoTimestamp(dtoEntry.start_time),
        endTime: safeIsoTimestamp(dtoEntry.end_time),
        recordCount: safeNonNegativeCount(dtoEntry.record_count),
        compressedBytes: safeNonNegativeBytes(dtoEntry.compressed_bytes) ?? 0,
        uncompressedBytes: safeNonNegativeBytes(dtoEntry.uncompressed_bytes),
        verificationStatus: verificationStatus,
        manifestStatus: safeString(dtoEntry.manifest_status),
        downloadable: safeBoolean(dtoEntry.downloadable),
        deletionEligible: safeBoolean(dtoEntry.deletion_eligible),
    };
}

export function normalizeArchivesDomain(dtoData) {
    var entries = dtoData.entries.map(function (entry) {
        return normalizeArchiveEntryDomain(entry);
    }).filter(function (entry) {
        return entry !== null;
    });

    return {
        entries: entries,
        page: safeNonNegativeCount(dtoData.page) ?? 1,
        pageSize: safeNonNegativeCount(dtoData.page_size) ?? entries.length,
        totalCount: safeNonNegativeCount(dtoData.total_count) ?? entries.length,
        totalPages: safeNonNegativeCount(dtoData.total_pages) ?? (entries.length > 0 ? 1 : 0),
    };
}
