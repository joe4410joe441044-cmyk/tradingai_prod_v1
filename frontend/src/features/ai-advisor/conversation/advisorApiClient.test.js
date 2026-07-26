import assert from "node:assert/strict";
import test from "node:test";

import {
    ADVISOR_ADVICE_PATH,
    AdvisorApiError,
    createAdvisorApiClient,
} from "./advisorApiClient.js";

const auth = Object.freeze({
    state: "AVAILABLE",
    getAuthorizationHeader: async () => "Bearer test-only-value",
});
const serviceInput = Object.freeze({ exactBackendContractFixture: true });
const envelope = {
    responseVersion: "1.0",
    requestId: "request-1",
    promptVersion: "1.0",
    receivedAt: "2026-07-26T00:00:00Z",
    status: "VALID",
    summary: "Safe answer",
    facts: [],
    inferences: [],
    unknowns: [],
    warnings: [],
    sourceReferences: [],
    freshnessDisclosures: [],
    safetyDisclosures: [
        "READ_ONLY", "NO_ACTION_EXECUTED", "NO_STATE_CHANGED", "NO_TOOL_USED",
    ],
    forbiddenClaims: [],
    validationWarnings: [],
    primaryRejectionReason: null,
};
const response = (status, body) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
});

test("client uses only the fixed relative path and exact serviceInput wrapper", async () => {
    const calls = [];
    const client = createAdvisorApiClient({
        authProvider: auth,
        fetchImpl: async (...args) => {
            calls.push(args);
            return response(200, { status: "SUCCEEDED", advisorResponse: envelope });
        },
    });
    const result = await client.requestAdvice(serviceInput);
    assert.equal(result.summary, "Safe answer");
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], ADVISOR_ADVICE_PATH);
    assert.deepEqual(JSON.parse(calls[0][1].body), { serviceInput });
    assert.equal(calls[0][1].headers.Authorization, "Bearer test-only-value");
    assert.equal("provider" in calls[0][1], false);
    assert.equal("model" in calls[0][1], false);
});

test("production-style unavailable auth fails closed before fetch", async () => {
    let calls = 0;
    const client = createAdvisorApiClient({
        fetchImpl: async () => { calls += 1; },
    });
    await assert.rejects(client.requestAdvice(serviceInput), {
        code: "AUTHENTICATION_REQUIRED",
    });
    assert.equal(calls, 0);
});

test("HTTP and backend failure codes map to safe frontend categories", async () => {
    const cases = [
        [401, { errorCode: "AUTHENTICATION_REQUIRED" }, "AUTHENTICATION_REQUIRED"],
        [403, { errorCode: "AUTHORIZATION_DENIED" }, "ACCESS_DENIED"],
        [413, { errorCode: "REQUEST_TOO_LARGE" }, "REQUEST_INVALID"],
        [422, { errorCode: "REQUEST_INVALID" }, "REQUEST_INVALID"],
        [429, { errorCode: "RATE_LIMIT_EXCEEDED" }, "RATE_LIMITED"],
        [429, { errorCode: "CONCURRENCY_LIMIT_EXCEEDED" }, "CONCURRENCY_LIMITED"],
        [502, { failureCode: "ADVISOR_PARSE_FAILURE" }, "INVALID_PROVIDER_RESPONSE"],
        [503, { errorCode: "ENDPOINT_DISABLED" }, "ENDPOINT_UNAVAILABLE"],
        [503, { failureCode: "ADVISOR_PROVIDER_FAILURE" }, "PROVIDER_UNAVAILABLE"],
        [504, { errorCode: "ENDPOINT_TIMEOUT" }, "TIMED_OUT"],
        [418, { errorCode: "FUTURE_SAFE_CODE" }, "UNKNOWN_SAFE_FAILURE"],
    ];
    for (const [status, body, code] of cases) {
        const client = createAdvisorApiClient({
            authProvider: auth,
            fetchImpl: async () => response(status, body),
        });
        await assert.rejects(client.requestAdvice(serviceInput), (error) => (
            error instanceof AdvisorApiError && error.code === code
        ));
    }
});

test("malformed successful response is rejected without exposing raw data", async () => {
    const client = createAdvisorApiClient({
        authProvider: auth,
        fetchImpl: async () => response(200, {
            status: "SUCCEEDED",
            advisorResponse: { ...envelope, secret: "must-not-leak" },
        }),
    });
    await assert.rejects(client.requestAdvice(serviceInput), (error) => (
        error.code === "INVALID_PROVIDER_RESPONSE"
        && !error.message.includes("must-not-leak")
    ));
});

test("caller abort and timeout are distinct and neither retries", async () => {
    let abortCalls = 0;
    const abortController = new AbortController();
    const fetchImpl = (_path, { signal }) => new Promise((resolve, reject) => {
        abortCalls += 1;
        signal.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
        });
    });
    const aborted = createAdvisorApiClient({ authProvider: auth, fetchImpl });
    const pendingAbort = aborted.requestAdvice(serviceInput, { signal: abortController.signal });
    abortController.abort();
    await assert.rejects(pendingAbort, { code: "CANCELLED" });
    assert.equal(abortCalls, 0);

    let timeoutCalls = 0;
    const timed = createAdvisorApiClient({
        authProvider: auth,
        fetchImpl: (_path, { signal }) => new Promise((resolve, reject) => {
            timeoutCalls += 1;
            signal.addEventListener("abort", () => {
                const error = new Error("aborted");
                error.name = "AbortError";
                reject(error);
            });
        }),
        timeoutMs: 1,
    });
    await assert.rejects(timed.requestAdvice(serviceInput), { code: "TIMED_OUT" });
    assert.equal(timeoutCalls, 1);
});
