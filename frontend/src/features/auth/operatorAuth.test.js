import assert from "node:assert/strict";
import test from "node:test";

import {
    OPERATOR_AUTH_STATE,
    authenticatedControlRequest,
    authErrorMessage,
    getOperatorAuthStatus,
    isAuthErrorStatus,
    setOperatorAuthStatus,
    subscribeOperatorAuthStatus,
} from "./operatorAuth.js";

test("operator auth store notifies subscribers and exposes the current status", () => {
    const seen = [];
    const unsubscribe = subscribeOperatorAuthStatus((status) => seen.push(status));

    setOperatorAuthStatus(OPERATOR_AUTH_STATE.AUTHENTICATED);
    assert.equal(getOperatorAuthStatus(), OPERATOR_AUTH_STATE.AUTHENTICATED);
    assert.deepEqual(seen, [OPERATOR_AUTH_STATE.AUTHENTICATED]);

    setOperatorAuthStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
    assert.equal(getOperatorAuthStatus(), OPERATOR_AUTH_STATE.UNAUTHENTICATED);
    assert.deepEqual(seen, [
        OPERATOR_AUTH_STATE.AUTHENTICATED,
        OPERATOR_AUTH_STATE.UNAUTHENTICATED,
    ]);

    unsubscribe();
    setOperatorAuthStatus(OPERATOR_AUTH_STATE.AUTHENTICATED);
    assert.equal(seen.length, 2);
});

test("auth error classification maps 401 and 403 to authentication/authorization", () => {
    assert.equal(isAuthErrorStatus(401), true);
    assert.equal(isAuthErrorStatus(403), true);
    assert.equal(isAuthErrorStatus(409), false);
    assert.equal(isAuthErrorStatus(200), false);
    assert.match(authErrorMessage(401), /authentication/i);
    assert.match(authErrorMessage(403), /authorization/i);
});

test("authenticated control request attaches CSRF header and credentials on POST", async () => {
    const originalFetch = globalThis.fetch;
    const originalDocument = globalThis.document;
    const calls = [];
    globalThis.document = { cookie: "tradingai_csrf=csrf-token-123" };
    globalThis.fetch = async (url, options) => {
        calls.push({ url, options });
        return new Response("{}", { status: 200 });
    };

    try {
        await authenticatedControlRequest("/api/bot/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
        });

        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, "/api/bot/start");
        assert.equal(calls[0].options.method, "POST");
        assert.equal(calls[0].options.credentials, "same-origin");
        assert.equal(
            calls[0].options.headers["X-TradingAI-CSRF"],
            "csrf-token-123",
        );
        assert.equal(
            calls[0].options.headers["Content-Type"],
            "application/json",
        );
    } finally {
        globalThis.fetch = originalFetch;
        globalThis.document = originalDocument;
    }
});

test("authenticated control request omits CSRF header on GET", async () => {
    const originalFetch = globalThis.fetch;
    const originalDocument = globalThis.document;
    const calls = [];
    globalThis.document = { cookie: "tradingai_csrf=csrf-token-123" };
    globalThis.fetch = async (url, options) => {
        calls.push({ url, options });
        return new Response("{}", { status: 200 });
    };

    try {
        await authenticatedControlRequest("/api/bot/status", {
            method: "GET",
        });

        assert.equal(calls.length, 1);
        assert.equal(
            Object.prototype.hasOwnProperty.call(
                calls[0].options.headers,
                "X-TradingAI-CSRF",
            ),
            false,
        );
        assert.equal(calls[0].options.credentials, "same-origin");
    } finally {
        globalThis.fetch = originalFetch;
        globalThis.document = originalDocument;
    }
});
