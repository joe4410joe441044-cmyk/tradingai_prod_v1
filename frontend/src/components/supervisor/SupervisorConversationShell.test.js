import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorConversationShell.jsx", import.meta.url), "utf8");

test("shell provides bounded session history and SHADOW-only messaging", () => {
    assert.match(source, /MAX_HISTORY = 20/);
    assert.match(source, /SHADOW · 実変更なし/);
    assert.match(source, /sendSupervisorConversation/);
    assert.doesNotMatch(source, /sessionStorage|raw JSON/);
});

test("loading cancel error and duplicate-send controls are explicit", () => {
    assert.match(source, /Loading…/);
    assert.match(source, />Cancel</);
    assert.match(source, /role="alert"/);
    assert.match(source, /if \(!message \|\| pending\) return/);
    assert.match(source, /controller\.signal\.aborted/);
});

test("speech transcript only updates editable draft and does not submit", () => {
    assert.match(source, /onTranscript: \(transcript\) => setDraft/);
    assert.match(source, /value={draft}/);
    assert.match(source, /onChange=/);
    assert.doesNotMatch(source, /onTranscript:[^\n]*submit/);
    assert.match(source, /aria-label={`\$\{supervisorName\} microphone`}/);
});

test("current conversation and read-only persisted history UX are explicit", () => {
    assert.match(source, /\+ New Conversation/);
    assert.match(source, /Conversation History/);
    assert.match(source, /Viewing History/);
    assert.match(source, /READ ONLY/);
    assert.match(source, /Back to Current Conversation/);
    assert.match(source, /currentConversationStorageKey\(agentId\)/);
    assert.match(source, /getSupervisorConversationHistory\(agentId\)/);
    assert.match(source, /getSupervisorConversationSession\(agentId/);
    assert.match(source, /if \(pending\) return/);
    assert.match(source, /inputRef\.current\?\.focus/);
    assert.match(source, /viewingHistory \? viewingHistory\.messages/);
});


test("UNKNOWN explanations use the shared human-actionable read-only presentation", () => {
    assert.match(source, /import SupervisorActionableUnknown/);
    assert.match(source, /response\.actionableUnknowns/);
    assert.match(source, /<SupervisorActionableUnknown item=\{item\}/);
});
