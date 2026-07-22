import {
    REPLAY_DATA_QUALITY,
    REPLAY_EVENT_SOURCES,
    REPLAY_EVENT_TYPES,
    REPLAY_MARKER_SIDES,
    REPLAY_MARKER_TYPES,
} from "./replayConstants.js";

const EVENT_FIELDS = [
    "id",
    "timestamp",
    "sequence",
    "eventType",
    "source",
    "positionId",
    "decisionId",
    "markerId",
    "stationId",
    "payload",
    "dataQuality",
];

const DATASET_FIELDS = [
    "datasetId",
    "symbol",
    "exchange",
    "tradeMode",
    "startedAt",
    "endedAt",
    "events",
    "metadata",
];

const MARKER_FIELDS = [
    "id", "markerId", "type", "timestamp", "sequence", "price", "quantity",
    "side", "reason", "orderId", "reduceOnly", "flatten", "blocked", "failed",
    "source", "eventType", "dataQuality",
];

const isRecord = (value) => (
    value !== null
    && typeof value === "object"
    && !Array.isArray(value)
);

const isValidTimestamp = (value) => {
    if (typeof value === "number") {
        return Number.isFinite(value);
    }

    return typeof value === "string"
        && value.trim() !== ""
        && Number.isFinite(Date.parse(value));
};

const error = (path, code, message) => ({ path, code, message });

export function validateReplayEvent(event) {
    const errors = [];

    if (!isRecord(event)) {
        return {
            valid: false,
            errors: [error("event", "INVALID_TYPE", "Replay event must be an object.")],
        };
    }

    for (const field of EVENT_FIELDS) {
        if (!Object.hasOwn(event, field)) {
            errors.push(error(field, "REQUIRED", `${field} is required.`));
        }
    }

    if (Object.hasOwn(event, "id") && (typeof event.id !== "string" || event.id === "")) {
        errors.push(error("id", "INVALID_VALUE", "id must be a non-empty string."));
    }
    if (Object.hasOwn(event, "timestamp") && !isValidTimestamp(event.timestamp)) {
        errors.push(error("timestamp", "INVALID_TIMESTAMP", "timestamp must be valid."));
    }
    if (Object.hasOwn(event, "sequence")
        && (!Number.isInteger(event.sequence) || event.sequence < 0)) {
        errors.push(error("sequence", "INVALID_VALUE", "sequence must be a non-negative integer."));
    }
    if (Object.hasOwn(event, "eventType") && !REPLAY_EVENT_TYPES.includes(event.eventType)) {
        errors.push(error("eventType", "UNKNOWN_VALUE", "eventType is not supported."));
    }
    if (Object.hasOwn(event, "source") && !REPLAY_EVENT_SOURCES.includes(event.source)) {
        errors.push(error("source", "UNKNOWN_VALUE", "source is not supported."));
    }
    if (Object.hasOwn(event, "payload") && !isRecord(event.payload)) {
        errors.push(error("payload", "INVALID_TYPE", "payload must be an object."));
    }
    if (Object.hasOwn(event, "dataQuality")
        && !REPLAY_DATA_QUALITY.includes(event.dataQuality)) {
        errors.push(error("dataQuality", "UNKNOWN_VALUE", "dataQuality is not supported."));
    }

    return { valid: errors.length === 0, errors };
}

export function validateReplayMarker(marker) {
    const errors = [];
    if (!isRecord(marker)) {
        return { valid: false, errors: [error("marker", "INVALID_TYPE", "Replay marker must be an object.")] };
    }
    for (const field of MARKER_FIELDS) {
        if (!Object.hasOwn(marker, field)) errors.push(error(field, "REQUIRED", `${field} is required.`));
    }
    for (const field of ["id", "markerId"]) {
        if (Object.hasOwn(marker, field) && (typeof marker[field] !== "string" || marker[field] === "")) {
            errors.push(error(field, "INVALID_VALUE", `${field} must be a non-empty string.`));
        }
    }
    if (Object.hasOwn(marker, "type") && !REPLAY_MARKER_TYPES.includes(marker.type)) {
        errors.push(error("type", "UNKNOWN_VALUE", "type is not supported."));
    }
    if (Object.hasOwn(marker, "timestamp") && !isValidTimestamp(marker.timestamp)) {
        errors.push(error("timestamp", "INVALID_TIMESTAMP", "timestamp must be valid."));
    }
    if (Object.hasOwn(marker, "sequence") && (!Number.isInteger(marker.sequence) || marker.sequence < 0)) {
        errors.push(error("sequence", "INVALID_VALUE", "sequence must be a non-negative integer."));
    }
    for (const field of ["price", "quantity"]) {
        if (Object.hasOwn(marker, field) && marker[field] !== null
            && (typeof marker[field] !== "number" || !Number.isFinite(marker[field]))) {
            errors.push(error(field, "INVALID_VALUE", `${field} must be a finite number or null.`));
        }
    }
    if (Object.hasOwn(marker, "side") && marker.side !== null && !REPLAY_MARKER_SIDES.includes(marker.side)) {
        errors.push(error("side", "UNKNOWN_VALUE", "side must be BUY, SELL, or null."));
    }
    for (const field of ["reason", "orderId"]) {
        if (Object.hasOwn(marker, field) && marker[field] !== null && typeof marker[field] !== "string") {
            errors.push(error(field, "INVALID_TYPE", `${field} must be a string or null.`));
        }
    }
    for (const field of ["reduceOnly", "flatten", "blocked", "failed"]) {
        if (Object.hasOwn(marker, field) && typeof marker[field] !== "boolean") {
            errors.push(error(field, "INVALID_TYPE", `${field} must be a boolean.`));
        }
    }
    if (Object.hasOwn(marker, "source") && !REPLAY_EVENT_SOURCES.includes(marker.source)) {
        errors.push(error("source", "UNKNOWN_VALUE", "source is not supported."));
    }
    if (Object.hasOwn(marker, "eventType") && !REPLAY_EVENT_TYPES.includes(marker.eventType)) {
        errors.push(error("eventType", "UNKNOWN_VALUE", "eventType is not supported."));
    }
    if (Object.hasOwn(marker, "dataQuality") && !REPLAY_DATA_QUALITY.includes(marker.dataQuality)) {
        errors.push(error("dataQuality", "UNKNOWN_VALUE", "dataQuality is not supported."));
    }
    return { valid: errors.length === 0, errors };
}

export function validateReplayDataset(dataset) {
    const errors = [];

    if (!isRecord(dataset)) {
        return {
            valid: false,
            errors: [error("dataset", "INVALID_TYPE", "Replay dataset must be an object.")],
        };
    }

    for (const field of DATASET_FIELDS) {
        if (!Object.hasOwn(dataset, field)) {
            errors.push(error(field, "REQUIRED", `${field} is required.`));
        }
    }

    for (const field of ["datasetId", "symbol", "exchange", "tradeMode"]) {
        if (Object.hasOwn(dataset, field)
            && (typeof dataset[field] !== "string" || dataset[field] === "")) {
            errors.push(error(field, "INVALID_VALUE", `${field} must be a non-empty string.`));
        }
    }
    for (const field of ["startedAt", "endedAt"]) {
        if (Object.hasOwn(dataset, field) && !isValidTimestamp(dataset[field])) {
            errors.push(error(field, "INVALID_TIMESTAMP", `${field} must be valid.`));
        }
    }
    if (Object.hasOwn(dataset, "metadata") && !isRecord(dataset.metadata)) {
        errors.push(error("metadata", "INVALID_TYPE", "metadata must be an object."));
    }

    if (!Array.isArray(dataset.events)) {
        errors.push(error("events", "INVALID_TYPE", "events must be an array."));
        return { valid: false, errors };
    }

    const eventIds = new Set();
    const sequences = new Set();

    dataset.events.forEach((eventValue, index) => {
        const result = validateReplayEvent(eventValue);

        for (const eventError of result.errors) {
            errors.push({ ...eventError, path: `events[${index}].${eventError.path}` });
        }

        if (!isRecord(eventValue)) {
            return;
        }
        if (eventIds.has(eventValue.id)) {
            errors.push(error(
                `events[${index}].id`,
                "DUPLICATE_ID",
                `Replay event id ${eventValue.id} is duplicated.`,
            ));
        } else {
            eventIds.add(eventValue.id);
        }
        if (sequences.has(eventValue.sequence)) {
            errors.push(error(
                `events[${index}].sequence`,
                "DUPLICATE_SEQUENCE",
                `Replay event sequence ${eventValue.sequence} is duplicated.`,
            ));
        } else {
            sequences.add(eventValue.sequence);
        }
    });

    return { valid: errors.length === 0, errors };
}
