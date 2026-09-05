import assert from "node:assert/strict";
import test from "node:test";

import {
    beginAdvisorRequest,
    clearAdvisorConversation,
    completeAdvisorRequest,
    failAdvisorRequest,
    hydrateConversationFromHistory,
    initialAdvisorConversationState,
    MAX_ADVISOR_PROMPT_BYTES,
    validateAdvisorPrompt,
} from "./advisorConversationModel.js";

const request = (requestId = "request-1") => ({
    requestId,
    userMessageId: `user-${requestId}`,
    assistantMessageId: `assistant-${requestId}`,
    content: "Explain runtime health.",
    createdAt: "2026-07-26T00:00:00Z",
});

test("prompt validation uses UTF-8 bytes and rejects whitespace", () => {
    assert.equal(validateAdvisorPrompt(" \n ").valid, false);
    assert.equal(validateAdvisorPrompt("あ").byteLength, 3);
    assert.equal(validateAdvisorPrompt("a".repeat(MAX_ADVISOR_PROMPT_BYTES)).valid, true);
    assert.equal(validateAdvisorPrompt("あ".repeat(4001)).valid, false);
});

test("one request creates exactly one immutable pending assistant message", () => {
    const started = beginAdvisorRequest(initialAdvisorConversationState, request());
    assert.equal(started.messages.length, 2);
    assert.equal(started.messages[1].status, "PENDING");
    assert.ok(Object.isFrozen(started));
    assert.ok(Object.isFrozen(started.messages));
    assert.strictEqual(beginAdvisorRequest(started, request("request-2")), started);
    assert.strictEqual(beginAdvisorRequest(started, request()), started);
});

test("late, out-of-order, cancelled, and timed-out responses are ignored", () => {
    const started = beginAdvisorRequest(initialAdvisorConversationState, request());
    assert.strictEqual(completeAdvisorRequest(started, "other", "late"), started);
    const cancelled = failAdvisorRequest(started, "request-1", "CANCELLED");
    assert.equal(cancelled.messages[1].status, "CANCELLED");
    assert.strictEqual(completeAdvisorRequest(cancelled, "request-1", "late"), cancelled);

    const timed = failAdvisorRequest(
        beginAdvisorRequest(initialAdvisorConversationState, request("request-2")),
        "request-2",
        "TIMED_OUT",
    );
    assert.equal(timed.messages[1].status, "TIMED_OUT");
    assert.strictEqual(completeAdvisorRequest(timed, "request-2", "late"), timed);
});

test("clear is session-memory only and cannot clear an active request", () => {
    const started = beginAdvisorRequest(initialAdvisorConversationState, request());
    assert.strictEqual(clearAdvisorConversation(started), started);
    const complete = completeAdvisorRequest(started, "request-1", "Safe answer");
    assert.strictEqual(clearAdvisorConversation(complete), initialAdvisorConversationState);
});

const completedExchange = (state, requestId, answer = `Answer ${requestId}`) => (
    completeAdvisorRequest(
        beginAdvisorRequest(state, {
            ...request(requestId),
            content: `Question ${requestId}`,
        }),
        requestId,
        answer,
    )
);

test("first completed question remains current and history stays empty", () => {
    const first = completedExchange(initialAdvisorConversationState, "request-1");
    assert.deepEqual(first.messages.map((message) => message.content), [
        "Question request-1",
        "Answer request-1",
    ]);
    assert.deepEqual(first.archivedExchanges, []);
});

test("submitting a second question archives the completed first exactly once", () => {
    const first = completedExchange(initialAdvisorConversationState, "request-1");
    const second = beginAdvisorRequest(first, {
        ...request("request-2"),
        content: "Question request-2",
    });
    assert.deepEqual(second.messages.map((message) => message.content), [
        "Question request-2",
        "",
    ]);
    assert.equal(second.archivedExchanges.length, 1);
    assert.equal(second.archivedExchanges[0].userMessage.content, "Question request-1");
    assert.equal(second.archivedExchanges[0].assistantMessage.content, "Answer request-1");
    assert.equal(second.archivedExchanges[0].status, "SUCCEEDED");
});

test("third question keeps current-only messages and newest-first history", () => {
    const first = completedExchange(initialAdvisorConversationState, "request-1");
    const second = completedExchange(first, "request-2");
    const third = beginAdvisorRequest(second, {
        ...request("request-3"),
        content: "Question request-3",
    });
    assert.deepEqual(third.messages.map((message) => message.content), [
        "Question request-3",
        "",
    ]);
    assert.deepEqual(
        third.archivedExchanges.map((exchange) => exchange.requestId),
        ["request-2", "request-1"],
    );
    const ids = [
        ...third.messages.map((message) => message.requestId),
        ...third.archivedExchanges.map((exchange) => exchange.requestId),
    ];
    assert.equal(ids.filter((id) => id === "request-1").length, 1);
    assert.equal(ids.filter((id) => id === "request-2").length, 1);
});

test("a failed previous answer archives with FAILED status", () => {
    const failed = failAdvisorRequest(
        beginAdvisorRequest(initialAdvisorConversationState, request("request-1")),
        "request-1",
        "INVALID_PROVIDER_RESPONSE",
    );
    const second = beginAdvisorRequest(failed, request("request-2"));
    assert.equal(second.archivedExchanges.length, 1);
    assert.equal(second.archivedExchanges[0].status, "FAILED");
    assert.equal(
        second.archivedExchanges[0].assistantMessage.content,
        "The advisor returned an invalid response.",
    );
});

test("archived answers preserve human-actionable UNKNOWN details", () => {
    const groundedResponse = {
        groundedClaims: [{ claimId: "unknown-1", claimType: "UNKNOWN" }],
        actionableUnknowns: [{
            unknownId: "unknown-1",
            reason: "現在情報がありません。",
            safeNextStep: "読み取り専用画面で確認してください。",
            decisionImpact: "確認できるまで判断を見送ってください。",
            operationalEffect: "NONE",
        }],
    };
    const first = completeAdvisorRequest(
        beginAdvisorRequest(initialAdvisorConversationState, request("request-1")),
        "request-1",
        "確認できない情報があります。",
        groundedResponse,
    );
    const second = beginAdvisorRequest(first, request("request-2"));
    assert.deepEqual(
        second.archivedExchanges[0].assistantMessage.groundedResponse,
        groundedResponse,
    );
});

const serverHistory = () => ([
    {
        messageId: "m1", role: "USER", content: "Q1",
        createdAt: "2026-01-01T00:00:00Z", requestId: "r1", responseStatus: null,
    },
    {
        messageId: "m2", role: "ADVISOR", content: "A1",
        createdAt: "2026-01-01T00:00:01Z", requestId: "r1", responseStatus: "VALID",
    },
    {
        messageId: "m3", role: "USER", content: "Q2",
        createdAt: "2026-01-02T00:00:00Z", requestId: "r2", responseStatus: null,
    },
    {
        messageId: "m4", role: "ADVISOR", content: "A2",
        createdAt: "2026-01-02T00:00:01Z", requestId: "r2", responseStatus: "VALID",
    },
]);

test("hydrateConversationFromHistory maps server roles and newest-first history", () => {
    const state = hydrateConversationFromHistory(serverHistory());
    assert.deepEqual(state.messages.map((message) => message.content), ["Q2", "A2"]);
    assert.equal(state.messages[0].role, "USER");
    assert.equal(state.messages[1].role, "ASSISTANT");
    assert.equal(state.messages[1].requestId, "r2");
    assert.equal(state.archivedExchanges.length, 1);
    assert.equal(state.archivedExchanges[0].userMessage.content, "Q1");
    assert.equal(state.archivedExchanges[0].assistantMessage.content, "A1");
    assert.equal(state.archivedExchanges[0].status, "SUCCEEDED");
    assert.equal(state.activeRequestId, null);
    assert.ok(Object.isFrozen(state));
});

test("hydrateConversationFromHistory returns initial state for empty history", () => {
    assert.strictEqual(hydrateConversationFromHistory([]), initialAdvisorConversationState);
});
