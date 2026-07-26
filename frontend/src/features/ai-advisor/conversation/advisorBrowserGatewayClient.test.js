import assert from "node:assert/strict";
import test from "node:test";

import {
    ADVISOR_CONVERSATION_PATH,
    ADVISOR_CONVERSATION_STATUS_PATH,
    createAdvisorBrowserGatewayClient,
} from "./advisorBrowserGatewayClient.js";

const envelope = {
    responseVersion: "1.0",
    requestId: "request-1",
    summary: "Safe answer",
    status: "VALID",
};
const response = (status, body) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
});

test("gateway client sends only prompt with same-origin credentials and fixed header", async () => {
    const calls = [];
    const client = createAdvisorBrowserGatewayClient({
        fetchImpl: async (...args) => {
            calls.push(args);
            return response(200, { status: "SUCCEEDED", advisorResponse: envelope });
        },
    });
    assert.equal((await client.requestAdvice("Hello")).summary, "Safe answer");
    const [path, options] = calls[0];
    assert.equal(path, ADVISOR_CONVERSATION_PATH);
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.headers["X-TradingAI-Client"], "web");
    assert.equal("Authorization" in options.headers, false);
    assert.deepEqual(JSON.parse(options.body), { prompt: "Hello" });
    for (const forbidden of [
        "serviceInput", "permissionContext", "provider", "model", "credential",
    ]) {
        assert.equal(options.body.includes(forbidden), false);
    }
});

test("status uses its fixed same-origin path and validates coarse state", async () => {
    const calls = [];
    const client = createAdvisorBrowserGatewayClient({
        fetchImpl: async (...args) => {
            calls.push(args);
            return response(200, { status: "AVAILABLE" });
        },
    });
    assert.equal(await client.getStatus(), "AVAILABLE");
    assert.equal(calls[0][0], ADVISOR_CONVERSATION_STATUS_PATH);
    assert.equal(calls[0][1].credentials, "same-origin");
});

test("gateway HTTP failures map safely with no retries", async () => {
    const cases = [
        [401, "AUTHENTICATION_REQUIRED", "AUTHENTICATION_REQUIRED"],
        [403, "AUTHORIZATION_DENIED", "ACCESS_DENIED"],
        [429, "RATE_LIMIT_EXCEEDED", "RATE_LIMITED"],
        [429, "CONCURRENCY_LIMIT_EXCEEDED", "CONCURRENCY_LIMITED"],
        [502, "ADVISOR_PARSE_FAILURE", "INVALID_PROVIDER_RESPONSE"],
        [503, "ENDPOINT_DISABLED", "ENDPOINT_UNAVAILABLE"],
        [504, "ENDPOINT_TIMEOUT", "TIMED_OUT"],
    ];
    for (const [status, wireCode, expected] of cases) {
        let calls = 0;
        const client = createAdvisorBrowserGatewayClient({
            fetchImpl: async () => {
                calls += 1;
                return response(status, {
                    errorCode: wireCode,
                    failureCode: wireCode,
                });
            },
        });
        await assert.rejects(client.requestAdvice("Hello"), { code: expected });
        assert.equal(calls, 1);
    }
});

test("abort and timeout are distinct and never retry", async () => {
    const fetchImpl = (_path, { signal }) => new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
        });
    });
    const caller = new AbortController();
    const client = createAdvisorBrowserGatewayClient({ fetchImpl });
    const pending = client.requestAdvice("Hello", { signal: caller.signal });
    caller.abort();
    await assert.rejects(pending, { code: "CANCELLED" });

    const timed = createAdvisorBrowserGatewayClient({ fetchImpl, timeoutMs: 1 });
    await assert.rejects(timed.requestAdvice("Hello"), { code: "TIMED_OUT" });
});

test("missing, fake, path, and URL citations fail closed", async () => {
    const invalid = [
        {
            ...envelope,
            groundedClaims: [{
                claimId: "fact-1",
                claimType: "FACT",
                text: "Unsupported fact",
                citationSourceIds: [],
            }],
            citations: [],
            limitations: [],
        },
        {
            ...envelope,
            groundedClaims: [{
                claimId: "fact-1",
                claimType: "FACT",
                text: "Fake citation",
                citationSourceIds: ["missing"],
            }],
            citations: [],
            limitations: [],
        },
        {
            ...envelope,
            groundedClaims: [],
            citations: [{
                sourceId: "source-1",
                displayTitle: "/private/path",
                version: "1.0",
            }],
            limitations: [],
        },
        {
            ...envelope,
            groundedClaims: [],
            citations: [{
                sourceId: "source-1",
                displayTitle: "https://unapproved.invalid",
                version: "1.0",
            }],
            limitations: [],
        },
    ];
    for (const advisorResponse of invalid) {
        const client = createAdvisorBrowserGatewayClient({
            fetchImpl: async () => response(200, {
                status: "SUCCEEDED",
                advisorResponse,
            }),
        });
        await assert.rejects(client.requestAdvice("Hello"), {
            code: "INVALID_PROVIDER_RESPONSE",
        });
    }
});
