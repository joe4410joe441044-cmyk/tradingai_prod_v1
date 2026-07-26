import assert from "node:assert/strict";
import test from "node:test";

import {
    beginAdvisorRequest,
    clearAdvisorConversation,
    completeAdvisorRequest,
    failAdvisorRequest,
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
