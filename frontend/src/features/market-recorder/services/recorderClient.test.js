import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

import { recorderClient, resetBaseUrlCache } from "./recorderClient.js";
import { RECORDER_ERROR_CODE } from "../contracts/recorderError.js";

function createMockResponse(body, status, contentType) {
    status = status || 200;
    contentType = contentType || "application/json";
    return {
        ok: status >= 200 && status < 300,
        status: status,
        headers: {
            get: function (name) {
                if (name === "content-type") {
                    return contentType;
                }
                return null;
            },
        },
        json: async function () {
            if (typeof body === "string") {
                return JSON.parse(body);
            }
            return body;
        },
    };
}

function setupMockFetch(responseFactory) {
    var originalFetch = globalThis.fetch;
    globalThis.fetch = async function (url, options) {
        return responseFactory(url, options);
    };
    return function () {
        globalThis.fetch = originalFetch;
    };
}

function setupBaseUrl() {
    var prev = process.env.VITE_RECORDER_API_BASE_URL;
    process.env.VITE_RECORDER_API_BASE_URL = "http://localhost:9999";
    resetBaseUrlCache();
    return function () {
        if (prev === undefined) {
            delete process.env.VITE_RECORDER_API_BASE_URL;
        } else {
            process.env.VITE_RECORDER_API_BASE_URL = prev;
        }
        resetBaseUrlCache();
    };
}

function clearBaseUrl() {
    var prev = process.env.VITE_RECORDER_API_BASE_URL;
    delete process.env.VITE_RECORDER_API_BASE_URL;
    resetBaseUrlCache();
    return function () {
        if (prev !== undefined) {
            process.env.VITE_RECORDER_API_BASE_URL = prev;
        }
        resetBaseUrlCache();
    };
}

function setupBaseUrlValue(value) {
    var prev = process.env.VITE_RECORDER_API_BASE_URL;
    process.env.VITE_RECORDER_API_BASE_URL = value;
    resetBaseUrlCache();
    return function () {
        if (prev === undefined) {
            delete process.env.VITE_RECORDER_API_BASE_URL;
        } else {
            process.env.VITE_RECORDER_API_BASE_URL = prev;
        }
        resetBaseUrlCache();
    };
}

function expectConfigurationErrorForBaseUrl(value) {
    var restoreUrl = setupBaseUrlValue(value);
    var restoreFetch = setupMockFetch(function () {
        return createMockResponse(JSON.stringify(makeStatusResponse()));
    });

    return (async function () {
        try {
            await recorderClient.getStatus();
            assert.fail("Expected configuration error for base URL: " + value);
        } catch (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.NETWORK);
            assert.ok(err.message.includes("configuration_error"));
            assert.equal(err.retryable, false);
            assert.equal(err.source, "client");
        } finally {
            restoreFetch();
            restoreUrl();
        }
    })();
}

function makeHealthResponse() {
    return {
        ok: true,
        data: {
            status: "ok",
            contract_version: "0.1.0",
            uptime_seconds: 12345,
        },
        error: null,
    };
}

function makeStatusResponse() {
    return {
        ok: true,
        data: {
            status: "RUNNING",
            uptime_seconds: 5025,
            active_files: ["BTCUSDT-2026-07-31.jsonl.part"],
            connection_state: "connected",
            pid: 12345,
            subscribed_streams: 5,
            messages_received: 1250000,
            bytes_received: 250000000,
            reconnect_count: 0,
            sequence_anomaly_count: 0,
            last_message_at: "2026-07-31T12:34:56Z",
            last_error: null,
            process_started_at: "2026-07-31T00:00:00Z",
            observed_at: "2026-07-31T12:35:00Z",
        },
        error: null,
    };
}

function makeStorageResponse() {
    return {
        ok: true,
        data: {
            total_bytes: 536870912000,
            used_bytes: 251792850944,
            free_bytes: 285078061056,
            archive_bytes: 13244702720,
            active_bytes: 5242880000,
            manifest_bytes: 20971520,
            usage_percent: 46.9,
            quarantine_count: 0,
            filesystem: "/dev/sda1",
            observed_at: "2026-07-31T12:35:00Z",
        },
        error: null,
    };
}

function makeArchivesResponse() {
    return {
        ok: true,
        data: {
            entries: [
                {
                    id: "arch-001",
                    stream: "btcusdt@trade",
                    symbol: "BTCUSDT",
                    period: "2026-07-31",
                    start_time: "2026-07-31T00:00:00Z",
                    end_time: "2026-07-31T23:59:59Z",
                    record_count: 5000000,
                    compressed_bytes: 257589411,
                    uncompressed_bytes: 1048576000,
                    verification_status: "completed",
                    manifest_status: "complete",
                    downloadable: true,
                    deletion_eligible: true,
                },
            ],
            page: 1,
            page_size: 200,
            total_count: 1,
            total_pages: 1,
        },
        error: null,
    };
}

test("getStatus returns domain model on success", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify(makeStatusResponse()));
    });
    var restoreUrl = setupBaseUrl();

    try {
        var result = await recorderClient.getStatus();
        assert.ok(result !== null);
        assert.equal(result.status, "RUNNING");
        assert.equal(result.uptimeSeconds, 5025);
        assert.ok(Array.isArray(result.activeFiles));
        assert.equal(result.activeFiles[0], "BTCUSDT-2026-07-31.jsonl.part");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getStorage returns domain model on success", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify(makeStorageResponse()));
    });
    var restoreUrl = setupBaseUrl();

    try {
        var result = await recorderClient.getStorage();
        assert.ok(result !== null);
        assert.equal(result.totalBytes, 536870912000);
        assert.equal(result.archiveBytes, 13244702720);
        assert.equal(result.quarantineCount, 0);
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getArchives returns domain model on success", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify(makeArchivesResponse()));
    });
    var restoreUrl = setupBaseUrl();

    try {
        var result = await recorderClient.getArchives({ page: 1, page_size: 10 });
        assert.ok(result !== null);
        assert.ok(Array.isArray(result.entries));
        assert.equal(result.entries.length, 1);
        assert.equal(result.entries[0].id, "arch-001");
        assert.equal(result.entries[0].verificationStatus, "completed");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getStatus handles HTTP 4xx", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse("Not Found", 404, "text/html");
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.ok(err.code === RECORDER_ERROR_CODE.NETWORK || err.code === RECORDER_ERROR_CODE.PARSE);
        assert.equal(err.retryable, false);
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getStatus handles HTTP 5xx", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse("Server Error", 500, "text/plain");
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.ok(err.code === RECORDER_ERROR_CODE.SERVER || err.code === RECORDER_ERROR_CODE.NETWORK || err.code === RECORDER_ERROR_CODE.PARSE);
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getStatus handles invalid JSON", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse("not json{{{", 200, "application/json");
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
        assert.ok(err.message.includes("invalid json"));
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getStatus handles API ok=false", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify({ ok: false, error: "internal error", data: null }));
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.equal(err.code, RECORDER_ERROR_CODE.SERVER);
        assert.ok(err.message.includes("recorder_api_rejected"));
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getStatus handles missing data field", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify({ ok: true }));
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.equal(err.code, RECORDER_ERROR_CODE.PARSE);
        assert.ok(err.message.includes("missing data"));
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("base URL missing throws configuration error", async function () {
    var restoreUrl = clearBaseUrl();
    var restoreFetch = setupMockFetch(function () {
        return createMockResponse(JSON.stringify(makeStatusResponse()));
    });

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.equal(err.code, RECORDER_ERROR_CODE.NETWORK);
        assert.ok(err.message.includes("configuration_error"));
        assert.equal(err.retryable, false);
        assert.equal(err.source, "client");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("network failure produces safe error", async function () {
    var restoreFetch = setupMockFetch(function () {
        throw new Error("connect ECONNREFUSED");
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getStatus();
        assert.fail("Expected error");
    } catch (err) {
        assert.equal(err.code, RECORDER_ERROR_CODE.NETWORK);
        assert.ok(err.message.includes("recorder_api_unavailable"));
        assert.equal(err.retryable, true);
        assert.equal(err.source, "network");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("base URL with query string is fail-closed", async function () {
    await expectConfigurationErrorForBaseUrl("http://localhost:9999?token=secret");
});

test("base URL with fragment is fail-closed", async function () {
    await expectConfigurationErrorForBaseUrl("http://localhost:9999#section");
});

test("base URL with embedded credentials is fail-closed", async function () {
    await expectConfigurationErrorForBaseUrl("http://user:pass@localhost:9999");
});

test("base URL with non-http(s) protocol is fail-closed", async function () {
    await expectConfigurationErrorForBaseUrl("ftp://localhost:9999");
});

test("base URL trailing slash is normalized", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        assert.ok(url.startsWith("http://localhost:9999/api/market-recorder/status"));
        assert.ok(!url.startsWith("http://localhost:9999///api/"));
        return createMockResponse(JSON.stringify(makeStatusResponse()));
    });
    var restoreUrl = setupBaseUrlValue("http://localhost:9999///");

    try {
        var result = await recorderClient.getStatus();
        assert.equal(result.status, "RUNNING");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("base URL with explicit path prefix is preserved", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        assert.ok(url.startsWith("http://localhost:9999/proxy/api/market-recorder/status"));
        return createMockResponse(JSON.stringify(makeStatusResponse()));
    });
    var restoreUrl = setupBaseUrlValue("http://localhost:9999/proxy/");

    try {
        var result = await recorderClient.getStatus();
        assert.equal(result.status, "RUNNING");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getHealth returns domain model on success", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify(makeHealthResponse()));
    });
    var restoreUrl = setupBaseUrl();

    try {
        var result = await recorderClient.getHealth();
        assert.ok(result !== null);
        assert.equal(result.status, "ok");
        assert.equal(result.contractVersion, "0.1.0");
        assert.equal(result.uptimeSeconds, 12345);
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getHealth uses same-origin backend proxy path only", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        assert.ok(url.startsWith("http://localhost:9999/api/market-recorder/health"));
        assert.ok(!url.includes("contabo"));
        assert.ok(!url.includes("market-recorder.example"));
        return createMockResponse(JSON.stringify(makeHealthResponse()));
    });
    var restoreUrl = setupBaseUrl();

    try {
        var result = await recorderClient.getHealth();
        assert.equal(result.status, "ok");
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getHealth handles HTTP 4xx as safe error", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse("Not Found", 404, "text/html");
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getHealth();
        assert.fail("Expected error");
    } catch (err) {
        assert.ok(err.code === RECORDER_ERROR_CODE.NETWORK || err.code === RECORDER_ERROR_CODE.PARSE);
        assert.equal(err.retryable, false);
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getHealth handles invalid envelope", async function () {
    var restoreFetch = setupMockFetch(function (url) {
        return createMockResponse(JSON.stringify({ ok: false, error: "boom", data: null }));
    });
    var restoreUrl = setupBaseUrl();

    try {
        await recorderClient.getHealth();
        assert.fail("Expected error");
    } catch (err) {
        assert.equal(err.code, RECORDER_ERROR_CODE.SERVER);
        assert.ok(err.message.includes("recorder_api_rejected"));
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getHealth abort produces safe abort error", async function () {
    var restoreUrl = setupBaseUrl();
    var restoreFetch = setupMockFetch(function (url, options) {
        return new Promise(function (resolve, reject) {
            options.signal.addEventListener("abort", function () {
                var err = new Error("aborted");
                err.name = "AbortError";
                reject(err);
            });
        });
    });

    try {
        var controller = new AbortController();
        var promise = recorderClient.getHealth({ signal: controller.signal, timeout: 5000 });
        controller.abort();
        await promise.then(
            function () { assert.fail("expected abort error"); },
            function (err) {
                assert.equal(err.code, RECORDER_ERROR_CODE.TIMEOUT);
                assert.ok(err.message.includes("recorder_api_aborted"));
            },
        );
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("getHealth timeout produces safe timeout error", async function () {
    var restoreUrl = setupBaseUrl();
    var restoreFetch = setupMockFetch(function (url, options) {
        return new Promise(function (resolve, reject) {
            options.signal.addEventListener("abort", function () {
                var err = new Error("aborted");
                err.name = "AbortError";
                reject(err);
            });
        });
    });

    try {
        var promise = recorderClient.getHealth({ timeout: 50 });
        await promise.then(
            function () { assert.fail("expected timeout error"); },
            function (err) {
                assert.equal(err.code, RECORDER_ERROR_CODE.TIMEOUT);
                assert.ok(err.message.includes("recorder_api_timeout"));
            },
        );
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("recorderClient functions return promises for read operations", async function () {
    var restoreUrl = setupBaseUrl();
    var callCount = 0;
    var restoreFetch = setupMockFetch(function () {
        callCount++;
        if (callCount === 1) {
            return createMockResponse(JSON.stringify(makeHealthResponse()));
        }
        if (callCount === 2) {
            return createMockResponse(JSON.stringify(makeStatusResponse()));
        }
        if (callCount === 3) {
            return createMockResponse(JSON.stringify(makeStorageResponse()));
        }
        return createMockResponse(JSON.stringify(makeArchivesResponse()));
    });

    try {
        var result = recorderClient.getHealth({ timeout: 5000 });
        assert.ok(result instanceof Promise);
        await result;

        result = recorderClient.getStatus({ timeout: 5000 });
        assert.ok(result instanceof Promise);
        await result;

        result = recorderClient.getStorage({ timeout: 5000 });
        assert.ok(result instanceof Promise);
        await result;

        result = recorderClient.getArchives({}, { timeout: 5000 });
        assert.ok(result instanceof Promise);
        await result;
    } finally {
        restoreFetch();
        restoreUrl();
    }
});

test("start posts live control request and returns structured result", async function () {
    var restoreFetch = setupMockFetch(function (url, options) {
        assert.ok(url.endsWith("/api/market-recorder/start"));
        assert.equal(options.method, "POST");
        assert.deepEqual(JSON.parse(options.body), { dry_run: false });
        return createMockResponse(JSON.stringify({
            ok: true, data: {
                operation_id: "start-1", operation: "start", result: "completed",
                previous_state: "stopped", current_state: "running",
            }, error: null,
        }));
    });
    var restoreUrl = setupBaseUrl();
    try {
        var result = await recorderClient.start();
        assert.equal(result.successful, true);
        assert.equal(result.currentState, "running");
    } finally {
        restoreFetch(); restoreUrl();
    }
});

test("stop preserves structured rejected result for domain handling", async function () {
    var restoreFetch = setupMockFetch(function (url, options) {
        assert.ok(url.endsWith("/api/market-recorder/stop"));
        assert.equal(options.method, "POST");
        return createMockResponse(JSON.stringify({
            ok: true, data: {
                operation_id: "stop-1", operation: "stop", result: "rejected",
                previous_state: "running", current_state: "running",
                message: "invalid_state_transition",
            }, error: null,
        }));
    });
    var restoreUrl = setupBaseUrl();
    try {
        var result = await recorderClient.stop();
        assert.equal(result.successful, false);
        assert.equal(result.result, "rejected");
        assert.equal(result.message, "invalid_state_transition");
    } finally {
        restoreFetch(); restoreUrl();
    }
});

test("download throws not-implemented error", function () {
    assert.throws(
        function () { recorderClient.download("id"); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.NOT_IMPLEMENTED);
            assert.ok(err.message.includes("download"));
            return true;
        },
    );
});

test("delete throws not-implemented error", function () {
    assert.throws(
        function () { recorderClient.delete("id"); },
        function (err) {
            assert.equal(err.code, RECORDER_ERROR_CODE.NOT_IMPLEMENTED);
            assert.ok(err.message.includes("delete"));
            return true;
        },
    );
});

test("recorderClient is frozen", function () {
    assert.throws(
        function () { recorderClient.newMethod = function () {}; },
        TypeError,
    );
});

test("recorderClient supports GET and POST methods - static check", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    assert.match(source, /"GET"/);
    assert.match(source, /"POST"/);
    assert.doesNotMatch(source, /method:\s*"PUT"/);
    assert.doesNotMatch(source, /method:\s*"PATCH"/);
    assert.doesNotMatch(source, /method:\s*"DELETE"/);
});

test("recorderClient does not contain WebSocket", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(source, /new WebSocket/);
    assert.doesNotMatch(source, /EventSource/);
});

test("recorderClient does not contain axios", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(source, /axios/);
});

test("recorderClient does not contain XMLHttpRequest", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(source, /XMLHttpRequest/);
});

test("recorderClient routes through backend proxy paths only", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    assert.match(source, /\/api\/market-recorder\/health/);
    assert.match(source, /\/api\/market-recorder\/status/);
    assert.match(source, /\/api\/market-recorder\/storage/);
    assert.match(source, /\/api\/market-recorder\/archives/);
    assert.doesNotMatch(source, /\/api\/recorder\//);
    assert.doesNotMatch(source, /contabo/i);
});

test("recorderClient does not contain URL credential embedding", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    var getBaseUrlBody = source.slice(
        source.indexOf("function getBaseUrl"),
        source.indexOf("var BASE_URL_RESOLVED"),
    );
    assert.match(getBaseUrlBody, /url\.username/);
    assert.match(getBaseUrlBody, /url\.password/);
    assert.match(getBaseUrlBody, /return null/);
});

test("recorderClient safeFetch has no retry loop", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    var safeFetchBody = source.slice(
        source.indexOf("async function safeFetch"),
        source.indexOf("async function checkResponseAndValidate"),
    );
    assert.doesNotMatch(safeFetchBody, /for\s*\(/);
    assert.doesNotMatch(safeFetchBody, /while\s*\(/);
});

test("safeFetch does not execute more than one fetch per call", async function () {
    var source = await readFile(
        new URL("./recorderClient.js", import.meta.url),
        "utf8",
    );
    var safeFetchBody = source.slice(
        source.indexOf("async function safeFetch"),
        source.indexOf("async function checkResponseAndValidate"),
    );
    var fetchMatches = safeFetchBody.match(/fetch\s*\(/g);
    assert.ok(fetchMatches !== null);
    assert.equal(fetchMatches.length, 1);
});
