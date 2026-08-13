const UNITS = ["B", "KB", "MB", "GB", "TB"];

const PLACEHOLDER_UNAVAILABLE = "--";

export function formatBytes(bytes) {
    if (bytes === null || bytes === undefined || typeof bytes !== "number") {
        return PLACEHOLDER_UNAVAILABLE;
    }
    if (!Number.isFinite(bytes)) {
        return PLACEHOLDER_UNAVAILABLE;
    }
    if (bytes < 0) {
        return PLACEHOLDER_UNAVAILABLE;
    }
    if (bytes === 0) {
        return "0 B";
    }

    let unitIndex = 0;
    let value = bytes;
    while (value >= 1024 && unitIndex < UNITS.length - 1) {
        value /= 1024;
        unitIndex++;
    }

    const decimals = unitIndex === 0 ? 0 : 2;
    return `${value.toFixed(decimals)} ${UNITS[unitIndex]}`;
}

export function formatDuration(totalSeconds) {
    if (totalSeconds === null || totalSeconds === undefined || typeof totalSeconds !== "number") {
        return PLACEHOLDER_UNAVAILABLE;
    }
    if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
        return PLACEHOLDER_UNAVAILABLE;
    }

    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = Math.floor(totalSeconds % 60);

    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

export function formatUtcDate(isoTimestamp) {
    if (typeof isoTimestamp !== "string" || isoTimestamp.length < 10) {
        return PLACEHOLDER_UNAVAILABLE;
    }

    const ms = Date.parse(isoTimestamp);
    if (!Number.isFinite(ms)) {
        return PLACEHOLDER_UNAVAILABLE;
    }

    const d = new Date(ms);
    const year = d.getUTCFullYear();
    const month = String(d.getUTCMonth() + 1).padStart(2, "0");
    const day = String(d.getUTCDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

export function formatRecorderStatus(status) {
    if (typeof status !== "string") {
        return PLACEHOLDER_UNAVAILABLE;
    }
    const normalized = status.toUpperCase().trim();
    if (normalized === "RUNNING" || normalized === "RECORDING") {
        return "RUNNING";
    }
    if (normalized === "STOPPED") {
        return "STOPPED";
    }
    return PLACEHOLDER_UNAVAILABLE;
}
