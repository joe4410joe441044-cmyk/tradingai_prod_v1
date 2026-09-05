import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { transformWithOxc } from "vite";

import {
    beginAdvisorRequest,
    completeAdvisorRequest,
    failAdvisorRequest,
    initialAdvisorConversationState,
    validateAdvisorPrompt,
} from "../../features/ai-advisor/conversation/advisorConversationModel.js";

const directory = dirname(fileURLToPath(import.meta.url));
const conversationSource = () =>
    readFile(new URL("./AdvisorConversation.jsx", import.meta.url), "utf8");

test("message renders untrusted response only as plain text", async () => {
    const source = new URL("./AdvisorConversation.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const temporary = await mkdtemp(join(directory, ".advisor-conversation-test-"));
    const output = join(temporary, "AdvisorConversation.mjs");
    try {
        const code = transformed.code
            .replace(
                'from "../../features/ai-advisor/conversation/advisorAuth.js";',
                'from "../../features/ai-advisor/conversation/advisorAuth.js";',
            );
        await writeFile(output, code);
        // Keep this security property inspectable without a DOM implementation.
        assert.doesNotMatch(code, /dangerouslySetInnerHTML|innerHTML/);
        assert.match(code, /message\.content/);
        assert.match(code, /autoComplete:\s*"off"/);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
});

test("conversation source has no persistence, logging, endpoint, or trading controls", async () => {
    const source = await conversationSource();
    for (const forbidden of [
        "localStorage", "sessionStorage", "indexedDB", "console.",
        "fetch(", "WebSocket", "api.openai.com", "botStart", "botStop",
        "providerOverride", "modelOverride", "clipboard",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
});

test("advisor availability is re-evaluated when the operator auth status changes", async () => {
    const source = await conversationSource();
    assert.match(source, /subscribeOperatorAuthStatus/);
    assert.match(source, /getOperatorAuthStatus/);
    assert.match(source, /\[client, operatorStatus\]/);
    assert.match(source, /client\.getStatus\(\{ signal: controller\.signal \}\)/);
});

test("logout or session-expiry invalidates advisor availability immediately", async () => {
    const source = await conversationSource();
    assert.match(source, /OPERATOR_AUTH_STATE\.UNAUTHENTICATED/);
    assert.match(source, /OPERATOR_AUTH_STATE\.SESSION_EXPIRED/);
    assert.match(source, /setAvailability\("AUTHENTICATION_REQUIRED"\)/);
    assert.match(source, /setConversation\(initialAdvisorConversationState\)/);
    assert.match(source, /setPrompt\(""\)/);
    assert.match(source, /const sendDisabled = !authReady \|\| !validation\.valid \|\| sending/);
});

test("Clear resets the authorized current conversation after server clear", async () => {
    const source = await conversationSource();
    assert.match(source, /const clear = useCallback\(\(\) => \{\s*if \(sending\) return;/s);
    assert.match(source, /setPrompt\(""\)/);
    assert.match(source, /client\.clearCurrentConversation\(\)/);
    assert.match(source, /initialAdvisorConversationState/);
    assert.doesNotMatch(source, /clearAdvisorConversation/);
    assert.match(source, /onHistoryChange\?\.\(conversation\.archivedExchanges\)/);
});

test("Browser Gateway send path validates prompts and prevents duplicate requests", async () => {
    const source = await conversationSource();
    assert.match(source, /createAdvisorBrowserGatewayClient\(\)/);
    assert.equal(source.match(/client\.requestAdvice\(/g)?.length, 1);
    assert.match(source, /if \(sendDisabled \|\| controllerRef\.current !== null\) return/);
    assert.match(source, /const sendDisabled = !authReady \|\| !validation\.valid \|\| sending/);
    assert.equal(validateAdvisorPrompt("").valid, false);
    assert.equal(validateAdvisorPrompt("   ").valid, false);

    const pending = beginAdvisorRequest(initialAdvisorConversationState, {
        requestId: "request-1",
        userMessageId: "user-1",
        assistantMessageId: "assistant-1",
        content: "Explain risk",
        createdAt: "2026-07-28T00:00:00Z",
    });
    assert.equal(
        beginAdvisorRequest(pending, {
            requestId: "request-2",
            userMessageId: "user-2",
            assistantMessageId: "assistant-2",
            content: "Duplicate",
            createdAt: "2026-07-28T00:00:01Z",
        }),
        pending,
    );
});

test("successful grounded responses are retained for safe conversation rendering", async () => {
    const source = await conversationSource();
    const pending = beginAdvisorRequest(initialAdvisorConversationState, {
        requestId: "request-1",
        userMessageId: "user-1",
        assistantMessageId: "assistant-1",
        content: "Explain risk",
        createdAt: "2026-07-28T00:00:00Z",
    });
    const groundedResponse = Object.freeze({
        summary: "Risk is normal.",
        citations: Object.freeze([]),
    });
    const completed = completeAdvisorRequest(
        pending,
        "request-1",
        groundedResponse.summary,
        groundedResponse,
    );
    const assistant = completed.messages.at(-1);

    assert.equal(assistant.content, "Risk is normal.");
    assert.equal(assistant.groundedResponse, groundedResponse);
    assert.match(source, /<AdvisorGroundedResponse response=\{message\.groundedResponse\} \/>/);
});

test("safe failure codes never expose raw exception details", async () => {
    const source = await conversationSource();
    const pending = beginAdvisorRequest(initialAdvisorConversationState, {
        requestId: "request-1",
        userMessageId: "user-1",
        assistantMessageId: "assistant-1",
        content: "Explain risk",
        createdAt: "2026-07-28T00:00:00Z",
    });
    const failed = failAdvisorRequest(
        pending,
        "request-1",
        "raw HTTP body with stack trace",
    );

    assert.equal(
        failed.messages.at(-1).content,
        "The advisor request could not be completed.",
    );
    assert.doesNotMatch(failed.messages.at(-1).content, /HTTP|stack trace/);
    assert.match(source, /typeof error\?\.code === "string"/);
    assert.doesNotMatch(source, /error\?\.message|error\.message|error\?\.stack|error\.stack/);
});

test("cancel and unmount abort requests while timeout remains distinct", async () => {
    const source = await conversationSource();
    assert.match(source, /const cancel = useCallback\(\(\) => \{\s*controllerRef\.current\?\.abort\(\)/s);
    assert.match(source, /mountedRef\.current = false;\s*controllerRef\.current\?\.abort\(\)/s);
    assert.match(source, /cancelled = true;\s*controller\.abort\(\)/s);
    assert.match(source, /signal: controller\.signal/);

    const createPending = () => beginAdvisorRequest(
        initialAdvisorConversationState,
        {
            requestId: "request-1",
            userMessageId: "user-1",
            assistantMessageId: "assistant-1",
            content: "Explain risk",
            createdAt: "2026-07-28T00:00:00Z",
        },
    );
    const cancelled = failAdvisorRequest(createPending(), "request-1", "CANCELLED");
    const timedOut = failAdvisorRequest(createPending(), "request-1", "TIMED_OUT");
    assert.equal(cancelled.messages.at(-1).status, "CANCELLED");
    assert.equal(cancelled.messages.at(-1).content, "The request was cancelled.");
    assert.equal(timedOut.messages.at(-1).status, "TIMED_OUT");
    assert.equal(timedOut.messages.at(-1).content, "The request timed out. You may try again.");
});

test("human-facing labels use bilingual English（日本語） notation", async () => {
    const source = await conversationSource();
    for (const label of [
        "Prompt Input（質問入力）",
        "Ask TradingAI...（TradingAIについて質問してください）",
        "READ ONLY（読み取り専用）",
        "No execution（実行なし）",
        "No config changes（設定変更なし）",
        ">Send（送信）<",
        ">Cancel（キャンセル）<",
        ">Clear（クリア）<",
        "Ask TradingAI a question.（TradingAIについて質問してください。）",
    ]) {
        assert.ok(source.includes(label), `expected bilingual label: ${label}`);
    }
});
