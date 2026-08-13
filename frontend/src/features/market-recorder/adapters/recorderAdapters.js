import { RECORDER_STATUS_STATE, ARCHIVE_STATUS } from "../contracts/recorderContracts.js";
import { ARCHIVE_DTO_STATUS } from "../services/recorderApiDtos.js";
import {
    formatBytes,
    formatDuration,
    formatUtcDate,
} from "../formatters/recorderFormatters.js";

function splitFormattedBytes(formatted) {
    if (formatted === "--" || formatted === null) {
        return { value: null, unit: null };
    }
    var lastSpace = formatted.lastIndexOf(" ");
    if (lastSpace === -1) {
        return { value: formatted, unit: null };
    }
    return {
        value: formatted.slice(0, lastSpace),
        unit: formatted.slice(lastSpace + 1),
    };
}

var VERIFICATION_TO_ARCHIVE_STATUS = {};
VERIFICATION_TO_ARCHIVE_STATUS[ARCHIVE_DTO_STATUS.COMPLETED] = ARCHIVE_STATUS.COMPLETED;
VERIFICATION_TO_ARCHIVE_STATUS[ARCHIVE_DTO_STATUS.RECORDING] = ARCHIVE_STATUS.RECORDING;
VERIFICATION_TO_ARCHIVE_STATUS[ARCHIVE_DTO_STATUS.FAILED] = ARCHIVE_STATUS.FAILED;

export function toRecorderStatusViewModel(domain) {
    if (domain === null || domain === undefined) {
        return {
            status: RECORDER_STATUS_STATE.UNAVAILABLE,
            recordingTime: null,
            currentFile: null,
            exchange: null,
            symbols: null,
            eventFamilies: null,
            eventsPerSecond: null,
            currentFileSize: null,
            reconnectCount: null,
            lastError: null,
            connectionState: null,
            messagesReceived: null,
            bytesReceived: null,
            sequenceAnomalyCount: null,
            lastMessageAt: null,
        };
    }

    var status = Object.values(RECORDER_STATUS_STATE).includes(domain.status)
        ? domain.status
        : RECORDER_STATUS_STATE.UNAVAILABLE;

    var recordingTime = null;
    if (status === RECORDER_STATUS_STATE.RUNNING
            && typeof domain.uptimeSeconds === "number"
            && Number.isFinite(domain.uptimeSeconds)
            && domain.uptimeSeconds >= 0) {
        recordingTime = formatDuration(domain.uptimeSeconds);
    }

    var currentFile = null;
    if (Array.isArray(domain.activeFiles) && domain.activeFiles.length > 0) {
        var raw = domain.activeFiles[0];
        if (typeof raw === "string") {
            if (raw.startsWith("/")) {
                var parts = raw.split("/");
                currentFile = parts[parts.length - 1] || raw;
            } else {
                currentFile = raw;
            }
        }
    }

    var exchange = null;

    var symbols = null;
    var eventFamilies = null;
    if (Array.isArray(domain.subscribedStreams) && domain.subscribedStreams.length > 0) {
        eventFamilies = Array.from(new Set(domain.subscribedStreams)).sort().join(", ");
    }

    var eventsPerSecond = null;

    var currentFileSize = null;

    var reconnectCount = null;
    if (typeof domain.reconnectCount === "number" && Number.isFinite(domain.reconnectCount) && domain.reconnectCount >= 0) {
        reconnectCount = domain.reconnectCount;
    }

    var lastError = null;
    if (typeof domain.lastError === "string" && domain.lastError.length > 0) {
        lastError = domain.lastError;
    }

    var connectionState = null;
    if (typeof domain.connectionState === "string" && domain.connectionState.length > 0) {
        connectionState = domain.connectionState;
    }

    return {
        status: status,
        recordingTime: recordingTime,
        currentFile: currentFile,
        exchange: exchange,
        symbols: symbols,
        eventFamilies: eventFamilies,
        eventsPerSecond: eventsPerSecond,
        currentFileSize: currentFileSize,
        reconnectCount: reconnectCount,
        lastError: lastError,
        connectionState: connectionState,
        messagesReceived: typeof domain.messagesReceived === "number"
            ? domain.messagesReceived : null,
        bytesReceived: typeof domain.bytesReceived === "number"
            ? formatBytes(domain.bytesReceived) : null,
        sequenceAnomalyCount: typeof domain.sequenceAnomalyCount === "number"
            ? domain.sequenceAnomalyCount : null,
        lastMessageAt: domain.lastMessageAt || null,
    };
}

export function toRecorderStorageViewModel(domain) {
    if (domain === null || domain === undefined) {
        return {
            total: null,
            totalUnit: null,
            used: null,
            usedUnit: null,
            free: null,
            freeUnit: null,
            recorderSize: null,
            recorderSizeUnit: null,
            usagePercent: null,
            runtimeSize: null,
            runtimeSizeUnit: null,
            activeRecordingSize: null,
            activeRecordingSizeUnit: null,
        };
    }

    var totalParts = splitFormattedBytes(formatBytes(domain.totalBytes));
    var usedParts = splitFormattedBytes(formatBytes(domain.usedBytes));
    var freeParts = splitFormattedBytes(formatBytes(domain.freeBytes));
    var recorderParts = splitFormattedBytes(formatBytes(domain.archiveBytes));

    var usagePercent = null;
    if (typeof domain.usagePercent === "number" && Number.isFinite(domain.usagePercent) && domain.usagePercent >= 0 && domain.usagePercent <= 100) {
        usagePercent = domain.usagePercent;
    }

    var runtimeParts = splitFormattedBytes(formatBytes(domain.runtimeBytes));
    var activeParts = splitFormattedBytes(formatBytes(domain.activeBytes));

    return {
        total: totalParts.value,
        totalUnit: totalParts.unit,
        used: usedParts.value,
        usedUnit: usedParts.unit,
        free: freeParts.value,
        freeUnit: freeParts.unit,
        recorderSize: recorderParts.value,
        recorderSizeUnit: recorderParts.unit,
        usagePercent: usagePercent,
        runtimeSize: runtimeParts.value,
        runtimeSizeUnit: runtimeParts.unit,
        activeRecordingSize: activeParts.value,
        activeRecordingSizeUnit: activeParts.unit,
    };
}

export function toRecorderArchiveViewModel(domain, index) {
    if (domain === null || domain === undefined) {
        return {
            id: null,
            date: null,
            file: null,
            compressedSize: null,
            status: ARCHIVE_STATUS.COMPLETED,
            downloadable: false,
            deletionEligible: false,
        };
    }

    var archiveStatus = VERIFICATION_TO_ARCHIVE_STATUS[domain.verificationStatus] || ARCHIVE_STATUS.COMPLETED;

    var date = formatUtcDate(domain.startTime);

    var file = null;
    if (typeof domain.symbol === "string" && domain.symbol.length > 0) {
        var datePart = date !== "--" ? date : "unknown";
        file = domain.symbol + "-" + datePart + ".jsonl.gz";
    }

    var compressedSize = null;
    if (typeof domain.compressedBytes === "number" && Number.isFinite(domain.compressedBytes) && domain.compressedBytes >= 0) {
        compressedSize = formatBytes(domain.compressedBytes);
    }

    var downloadable = domain.downloadable === true && archiveStatus === ARCHIVE_STATUS.COMPLETED;
    var deletionEligible = domain.deletionEligible === true;

    return {
        id: domain.id ?? (typeof index === "number" ? String(index) : null),
        date: date,
        file: file,
        compressedSize: compressedSize,
        status: archiveStatus,
        downloadable: downloadable,
        deletionEligible: deletionEligible,
    };
}

export function toRecorderArchivesViewModel(domainList) {
    if (!Array.isArray(domainList) || domainList.length === 0) {
        return [];
    }
    return domainList.map(function (item, index) {
        return toRecorderArchiveViewModel(item, index);
    });
}
