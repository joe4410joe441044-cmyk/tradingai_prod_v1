import assert from "node:assert/strict";
import test from "node:test";

import {
    ADVISOR_CONVERSATION_CLEAR_PATH,
    ADVISOR_CONVERSATION_HISTORY_PATH,
    ADVISOR_CONVERSATION_PATH,
    ADVISOR_CONVERSATION_STATUS_PATH,
    ADVISOR_CONVERSATION_STORAGE_KEY,
    createAdvisorBrowserGatewayClient,
} from "./advisorBrowserGatewayClient.js";

function withLocalStorage(values = new Map()) {
    const store = new Map(values);
    const stub = {
        getItem: (key) => (store.has(key) ? store.get(key) : null),
        setItem: (key, value) => store.set(key, value),
        removeItem: (key) => store.delete(key),
    };
    globalThis.localStorage = stub;
    return store;
}

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
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.headers["X-TradingAI-Client"], "web");
    assert.equal(options.headers["Content-Type"], "application/json");
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
    assert.equal(calls[0][1].method, "GET");
    assert.equal(calls[0][1].credentials, "same-origin");
});

test("conversation POST forwards the CSRF token from the cookie", async () => {
    globalThis.document = {
        cookie: "tradingai_csrf=csrf-token-123",
    };
    try {
        const calls = [];
        const client = createAdvisorBrowserGatewayClient({
            fetchImpl: async (...args) => {
                calls.push(args);
                return response(200, { status: "SUCCEEDED", advisorResponse: envelope });
            },
        });
        await client.requestAdvice("Hello");
        const [, options] = calls[0];
        assert.equal(options.headers["X-TradingAI-CSRF"], "csrf-token-123");
    } finally {
        delete globalThis.document;
    }
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

test("parse and network failures expose only safe errors", async () => {
    const unparseable = createAdvisorBrowserGatewayClient({
        fetchImpl: async () => ({
            ok: false,
            status: 502,
            json: async () => {
                throw new SyntaxError("secret upstream response");
            },
        }),
    });
    await assert.rejects(
        unparseable.requestAdvice("Hello"),
        (error) => error.code === "INVALID_PROVIDER_RESPONSE"
            && !error.message.includes("secret upstream response"),
    );

    const networkFailure = createAdvisorBrowserGatewayClient({
        fetchImpl: async () => {
            throw new Error("sensitive network detail");
        },
    });
    await assert.rejects(
        networkFailure.requestAdvice("Hello"),
        (error) => error.code === "ENDPOINT_UNAVAILABLE"
            && error.retryable === true
            && !error.message.includes("sensitive network detail"),
    );
});

test("required response fields are validated at runtime", async () => {
    for (const advisorResponse of [
        { ...envelope, responseVersion: undefined },
        { ...envelope, requestId: undefined },
        { ...envelope, summary: undefined },
        { ...envelope, status: undefined },
    ]) {
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

test("requestAdvice sends the stored conversationId and updates it after response", async () => {
    const calls = [];
    const store = withLocalStorage([[ADVISOR_CONVERSATION_STORAGE_KEY, "conversation-1"]]);
    try {
        const client = createAdvisorBrowserGatewayClient({
            fetchImpl: async (...args) => {
                calls.push(args);
                return response(200, {
                    status: "SUCCEEDED",
                    advisorResponse: envelope,
                    conversationId: "conversation-2",
                });
            },
        });
        const result = await client.requestAdvice("Hello");
        assert.equal(result.conversationId, "conversation-2");
        assert.deepEqual(JSON.parse(calls[0][1].body), {
            prompt: "Hello",
            conversationId: "conversation-1",
        });
        assert.equal(store.get(ADVISOR_CONVERSATION_STORAGE_KEY), "conversation-2");
    } finally {
        delete globalThis.localStorage;
    }
});

test("conversation history validates and returns the authorized messages", async () => {
    const messages = [{
        messageId: "m1",
        role: "USER",
        content: "Q1",
        createdAt: "2026-01-01T00:00:00Z",
    }];
    const client = createAdvisorBrowserGatewayClient({
        fetchImpl: async (...args) => {
            assert.equal(
                args[0],
                `${ADVISOR_CONVERSATION_HISTORY_PATH}?conversationId=conversation-1`,
            );
            assert.equal(args[1].method, "GET");
            assert.equal(args[1].credentials, "same-origin");
            return response(200, {
                status: "SUCCEEDED",
                conversationId: "conversation-1",
                messages,
            });
        },
    });
    const result = await client.getConversationHistory("conversation-1");
    assert.equal(result.conversationId, "conversation-1");
    assert.equal(result.messages[0].content, "Q1");
});

test("loadConversation returns empty without a stored conversation", async () => {
    const client = createAdvisorBrowserGatewayClient({
        fetchImpl: async () => {
            throw new Error("must not issue a fetch");
        },
    });
    const result = await client.loadConversation();
    assert.equal(result.conversationId, null);
    assert.deepEqual(result.messages, []);
});

test("loadConversation loads the stored conversation history", async () => {
    const store = withLocalStorage([[ADVISOR_CONVERSATION_STORAGE_KEY, "conversation-1"]]);
    try {
        const client = createAdvisorBrowserGatewayClient({
            fetchImpl: async (...args) => {
                assert.equal(
                    args[0],
                    `${ADVISOR_CONVERSATION_HISTORY_PATH}?conversationId=conversation-1`,
                );
                return response(200, {
                    status: "SUCCEEDED",
                    conversationId: "conversation-1",
                    messages: [{
                        messageId: "m1",
                        role: "USER",
                        content: "Q1",
                        createdAt: "2026-01-01T00:00:00Z",
                    }],
                });
            },
        });
        const result = await client.loadConversation();
        assert.equal(result.conversationId, "conversation-1");
        assert.equal(result.messages[0].content, "Q1");
    } finally {
        delete globalThis.localStorage;
    }
});

test("clearCurrentConversation posts /clear and resets the stored id", async () => {
    const calls = [];
    const store = withLocalStorage([[ADVISOR_CONVERSATION_STORAGE_KEY, "conversation-1"]]);
    try {
        const client = createAdvisorBrowserGatewayClient({
            fetchImpl: async (...args) => {
                calls.push(args);
                return response(200, {
                    status: "SUCCEEDED",
                    conversationId: "conversation-1",
                    cleared: true,
                });
            },
        });
        const result = await client.clearCurrentConversation();
        assert.equal(result.cleared, true);
        assert.equal(calls[0][0], ADVISOR_CONVERSATION_CLEAR_PATH);
        assert.deepEqual(JSON.parse(calls[0][1].body), { conversationId: "conversation-1" });
        assert.equal(store.has(ADVISOR_CONVERSATION_STORAGE_KEY), false);
    } finally {
        delete globalThis.localStorage;
    }
});

test("conversation history rejects unsafe stored messages", async () => {
    const client = createAdvisorBrowserGatewayClient({
        fetchImpl: async () => response(200, {
            status: "SUCCEEDED",
            conversationId: "conversation-1",
            messages: [{ messageId: "m1", role: "ADVISOR", content: "A1" }],
        }),
    });
    await assert.rejects(client.getConversationHistory("conversation-1"), {
        code: "INVALID_PROVIDER_RESPONSE",
    });
});

test("human-actionable UNKNOWN is validated and retained", async () => {
    const unknownEnvelope = {
        ...envelope,
        status: "VALID_WITH_WARNINGS",
        groundedClaims: [{
            claimId: "unknown-1",
            claimType: "UNKNOWN",
            text: "現在のRisk State",
            citationSourceIds: [],
        }],
        citations: [],
        limitations: [],
        actionableUnknowns: [{
            unknownId: "unknown-1",
            subject: "現在のRisk State",
            reason: "現在情報が提供されていません。",
            missingInformation: "現在の権威あるRisk State",
            safeNextStep: "読み取り専用のRuntime表示で確認してください。",
            decisionImpact: "確認できるまで判断を見送ってください。",
            operationalEffect: "NONE",
        }],
    };
    const client = createAdvisorBrowserGatewayClient({
        fetchImpl: async () => response(200, {
            status: "SUCCEEDED",
            advisorResponse: unknownEnvelope,
        }),
    });
    const result = await client.requestAdvice("現在のRisk Stateは？");
    assert.equal(result.actionableUnknowns[0].operationalEffect, "NONE");
    assert.match(result.actionableUnknowns[0].safeNextStep, /読み取り専用/);
});
