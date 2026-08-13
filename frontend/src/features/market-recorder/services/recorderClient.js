import {
    createRecorderError,
    createRecorderNotImplementedError,
    RECORDER_ERROR_CODE,
} from "../contracts/recorderError.js";
import {
    validateCommonResponse,
    validateHealthDto,
    validateStatusDto,
    validateStorageDto,
    validateArchivesDto,
    validateControlDto,
    normalizeHealthDomain,
    normalizeStatusDomain,
    normalizeStorageDomain,
    normalizeArchivesDomain,
    normalizeControlDomain,
} from "./recorderApiDtos.js";
import { buildArchivesQuery } from "./recorderQueryBuilder.js";

function readEnvVar(name) {
    if (typeof import.meta !== "undefined" && import.meta.env && import.meta.env[name]) {
        return import.meta.env[name];
    }
    if (typeof process !== "undefined" && process.env && process.env[name]) {
        return process.env[name];
    }
    return undefined;
}

function getBrowserOrigin() {
    try {
        if (typeof window !== "undefined" && window && window.location) {
            return window.location.origin;
        }
        return null;
    } catch (_e) {
        return null;
    }
}

function getBaseUrl() {
    var base = readEnvVar("VITE_RECORDER_API_BASE_URL");
    if (base === undefined || base === null || typeof base !== "string") {
        return getBrowserOrigin();
    }
    base = base.trim();
    if (base.length === 0) {
        return getBrowserOrigin();
    }

    try {
        var url = new URL(base);
    } catch (_e) {
        return null;
    }

    if (url.protocol !== "http:" && url.protocol !== "https:") {
        return null;
    }

    if (url.hash || url.search) {
        return null;
    }

    if (url.username || url.password) {
        return null;
    }

    var pathname = url.pathname.replace(/\/+$/, "");
    if (pathname) {
        return url.origin + pathname;
    }
    return url.origin.replace(/\/+$/, "");
}

var BASE_URL_RESOLVED = false;
var BASE_URL_CACHED = null;

function resolveBaseUrl() {
    if (!BASE_URL_RESOLVED) {
        BASE_URL_CACHED = getBaseUrl();
        BASE_URL_RESOLVED = true;
    }
    return BASE_URL_CACHED;
}

function resetBaseUrlCache() {
    BASE_URL_RESOLVED = false;
    BASE_URL_CACHED = null;
}

function buildUrl(path, queryString) {
    var base = resolveBaseUrl();
    if (base === null) {
        throw createRecorderError(
            RECORDER_ERROR_CODE.NETWORK,
            "recorder_api_configuration_error: VITE_RECORDER_API_BASE_URL not set",
            { retryable: false, source: "client" },
        );
    }
    var cleanPath = path.startsWith("/") ? path : "/" + path;
    return base + cleanPath + (queryString || "");
}

function assertGetOnly() {
}

var DEFAULT_TIMEOUT_MS = 10000;

function safeAbortError() {
    return createRecorderError(
        RECORDER_ERROR_CODE.TIMEOUT,
        "recorder_api_aborted",
        { retryable: false, source: "client" },
    );
}

function safeTimeoutError() {
    return createRecorderError(
        RECORDER_ERROR_CODE.TIMEOUT,
        "recorder_api_timeout",
        { retryable: true, source: "network" },
    );
}

function safeNetworkError(message) {
    return createRecorderError(
        RECORDER_ERROR_CODE.NETWORK,
        "recorder_api_unavailable: " + (message || "network error"),
        { retryable: true, source: "network" },
    );
}

function safeParseError() {
    return createRecorderError(
        RECORDER_ERROR_CODE.PARSE,
        "recorder_api_invalid_response: invalid json",
        { retryable: false, source: "client" },
    );
}

function safeHttpError(status, body) {
    var msg = "recorder_api_unavailable: HTTP " + status;
    return createRecorderError(
        status >= 500 ? RECORDER_ERROR_CODE.SERVER : RECORDER_ERROR_CODE.NETWORK,
        msg,
        { retryable: status >= 500, source: "server" },
    );
}

async function safeFetch(url, options) {
    var controller = new AbortController();
    var timeoutId;

    if (options && options.signal) {
        options.signal.addEventListener("abort", function () {
            controller.abort();
        });
    }

    var timeout = (options && options.timeout) || DEFAULT_TIMEOUT_MS;
    timeoutId = setTimeout(function () {
        controller.abort();
    }, timeout);

    var method = (options && options.method) || "GET";
    var headers = { "Accept": "application/json" };
    if (method === "POST") {
        headers["Content-Type"] = "application/json";
    }

    try {
        var response = await fetch(url, {
            method: method,
            headers: headers,
            signal: controller.signal,
            body: options && options.body ? JSON.stringify(options.body) : undefined,
        });

        if (!response.ok) {
            throw safeHttpError(response.status);
        }

        var contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            throw safeParseError();
        }

        var data;
        try {
            data = await response.json();
        } catch (_err) {
            throw safeParseError();
        }

        return data;
    } catch (err) {
        if (err && err.code && err.message && Object.prototype.hasOwnProperty.call(err, "retryable")) {
            throw err;
        }
        if (err && err.name === "AbortError") {
            if (options && options.signal && options.signal.aborted) {
                throw safeAbortError();
            }
            throw safeTimeoutError();
        }
        throw safeNetworkError(err ? err.message : "unknown");
    } finally {
        clearTimeout(timeoutId);
    }
}

async function checkResponseAndValidate(responsePromise, dtoValidator, domainNormalizer) {
    var responseData = await responsePromise;
    var dto = validateCommonResponse(responseData);
    var validatedDto = dtoValidator(dto);
    return domainNormalizer(validatedDto);
}

function safePostRequest(url, body, options) {
    return {
        method: "POST",
        body: body,
        signal: options && options.signal,
        timeout: options && options.timeout,
    };
}

export { resetBaseUrlCache };

export var recorderClient = Object.freeze({
    getHealth: function (options) {
        assertGetOnly();
        return checkResponseAndValidate(
            safeFetch(buildUrl("/api/market-recorder/health"), options),
            validateHealthDto,
            normalizeHealthDomain,
        );
    },

    getStatus: function (options) {
        assertGetOnly();
        return checkResponseAndValidate(
            safeFetch(buildUrl("/api/market-recorder/status"), options),
            validateStatusDto,
            normalizeStatusDomain,
        );
    },

    getStorage: function (options) {
        assertGetOnly();
        return checkResponseAndValidate(
            safeFetch(buildUrl("/api/market-recorder/storage"), options),
            validateStorageDto,
            normalizeStorageDomain,
        );
    },

    getArchives: function (query, options) {
        assertGetOnly();
        var queryString = buildArchivesQuery(query);
        return checkResponseAndValidate(
            safeFetch(buildUrl("/api/market-recorder/archives", queryString), options),
            validateArchivesDto,
            normalizeArchivesDomain,
        );
    },

    start: function (options) {
        return checkResponseAndValidate(
            safeFetch(
                buildUrl("/api/market-recorder/start"),
                safePostRequest(null, { dry_run: false }, options),
            ),
            validateControlDto,
            normalizeControlDomain,
        );
    },

    stop: function (options) {
        return checkResponseAndValidate(
            safeFetch(
                buildUrl("/api/market-recorder/stop"),
                safePostRequest(null, { dry_run: false }, options),
            ),
            validateControlDto,
            normalizeControlDomain,
        );
    },

    download: function (_id) {
        throw createRecorderNotImplementedError("download");
    },

    delete: function (_id) {
        throw createRecorderNotImplementedError("delete");
    },
});
