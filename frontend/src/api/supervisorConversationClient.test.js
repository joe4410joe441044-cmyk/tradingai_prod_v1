import assert from "node:assert/strict";
import test from "node:test";

import {
    sendSupervisorConversation,
    SupervisorConversationError,
} from "./supervisorConversationClient.js";

const success = {
    mode: "SHADOW",
    operationalEffect: "NONE",
    status: "UNAVAILABLE",
    answer: "Supervisor AI provider is not connected.",
};

test("routes Master and MM independently with bounded typed requests", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push([url, JSON.parse(options.body)]);
        return { ok: true, json: async () => success };
    };
    await sendSupervisorConversation({ agentId: "MASTER_SUPERVISOR", message: "state?", conversationId: "master-1", fetchImpl });
    await sendSupervisorConversation({ agentId: "MM_SUPERVISOR", message: "risk?", conversationId: "mm-1", fetchImpl });
    assert.equal(calls[0][0], "/api/supervisor/conversation/master");
    assert.equal(calls[1][0], "/api/supervisor/conversation/mm");
    assert.equal(calls[0][1].agentId, "MASTER_SUPERVISOR");
    assert.equal(calls[1][1].agentId, "MM_SUPERVISOR");
});

test("rejects responses lacking SHADOW and NONE without rendering raw JSON", async () => {
    const fetchImpl = async () => ({ ok: true, json: async () => ({ mode: "ACTIVE", operationalEffect: "ORDER" }) });
    await assert.rejects(
        sendSupervisorConversation({ agentId: "MASTER_SUPERVISOR", message: "x", conversationId: "x", fetchImpl }),
        (error) => error instanceof SupervisorConversationError && error.code === "INVALID_RESPONSE",
    );
});

test("caller abort is reported as cancellation", async () => {
    const controller = new AbortController();
    const fetchImpl = (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("late raw response")));
    });
    const pending = sendSupervisorConversation({
        agentId: "MASTER_SUPERVISOR", message: "x", conversationId: "x", fetchImpl, signal: controller.signal,
    });
    controller.abort();
    await assert.rejects(pending, (error) => error.code === "CANCELLED");
});
