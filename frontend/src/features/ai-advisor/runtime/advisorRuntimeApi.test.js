import assert from "node:assert/strict";
import test from "node:test";

globalThis.window = {
    location: {
        protocol: "http:",
        host: "localhost",
    },
};

const {
    AdvisorRuntimeApiError,
    fetchAdvisorRuntime,
} = await import("./advisorRuntimeApi.js");

const response = (body, { ok = true, status = 200 } = {}) => ({
    ok,
    status,
    json: async () => body,
});

test("runtime API performs GET and forwards an AbortSignal", async () => {
    const calls = [];
    const result = await fetchAdvisorRuntime({
        signal: new AbortController().signal,
        now: () => 1234,
        fetchImpl: async (url, options) => {
            calls.push({ url, options });
            return response({ bot: {} });
        },
    });

    assert.equal(calls[0].url, "/api/ai-advisor/conversation/runtime");
    assert.equal(calls[0].options.headers["X-TradingAI-Client"], "web");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.method, "GET");
    assert.ok(calls[0].options.signal instanceof AbortSignal);
    assert.equal(result.receivedAt, 1234);
});

test("runtime API preserves the safe backend error contract", async () => {
    await assert.rejects(
        () => fetchAdvisorRuntime({
            fetchImpl: async () => response({
                error: {
                    code: "ADVISOR_RUNTIME_UNAVAILABLE",
                    message: "Runtime status is unavailable.",
                    retryable: true,
                    requestId: "request-1",
                    occurredAt: "2026-07-25T10:00:00Z",
                    stack: "hidden",
                },
            }, { ok: false, status: 500 }),
        }),
        (error) => {
            assert.ok(error instanceof AdvisorRuntimeApiError);
            assert.equal(error.code, "ADVISOR_RUNTIME_UNAVAILABLE");
            assert.equal(error.retryable, true);
            assert.equal(error.requestId, "request-1");
            assert.equal(error.httpStatus, 500);
            assert.doesNotMatch(`${error.message}\n${error.stack}`, /hidden/);
            return true;
        },
    );
});

test("runtime API maps the browser gateway errorCode contract", async () => {
    await assert.rejects(
        () => fetchAdvisorRuntime({
            fetchImpl: async () => response({
                errorCode: "AUTHENTICATION_REQUIRED",
                safeMessage: "Authentication required.",
                retryable: false,
            }, { ok: false, status: 401 }),
        }),
        (error) => {
            assert.ok(error instanceof AdvisorRuntimeApiError);
            assert.equal(error.code, "AUTHENTICATION_REQUIRED");
            assert.equal(error.retryable, false);
            assert.equal(error.httpStatus, 401);
            assert.equal(error.message, "Authentication required.");
            return true;
        },
    );
});

test("runtime API distinguishes request timeout", async () => {
    await assert.rejects(
        () => fetchAdvisorRuntime({
            timeoutMs: 5,
            fetchImpl: (_url, { signal }) => new Promise((resolve, reject) => {
                signal.addEventListener("abort", () => {
                    reject(new DOMException("aborted", "AbortError"));
                });
            }),
        }),
        (error) => {
            assert.equal(error.code, "REQUEST_TIMEOUT");
            assert.equal(error.retryable, true);
            return true;
        },
    );
});

test("non-JSON and HTML errors are reduced to a safe generic contract", async () => {
    await assert.rejects(
        () => fetchAdvisorRuntime({
            fetchImpl: async () => ({
                ok: false,
                status: 502,
                json: async () => {
                    throw new SyntaxError("<html>proxy detail</html>");
                },
            }),
        }),
        (error) => {
            assert.equal(error.code, "ADVISOR_RUNTIME_REQUEST_FAILED");
            assert.equal(error.message, "Runtime status is unavailable.");
            assert.equal(error.httpStatus, 502);
            assert.doesNotMatch(error.message, /html|proxy detail/i);
            return true;
        },
    );
});
