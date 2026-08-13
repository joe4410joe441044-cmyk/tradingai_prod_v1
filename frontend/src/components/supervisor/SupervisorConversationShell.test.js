import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorConversationShell.jsx", import.meta.url), "utf8");

test("shell provides bounded session history and SHADOW-only messaging", () => {
    assert.match(source, /MAX_HISTORY = 20/);
    assert.match(source, /SHADOW · 実変更なし/);
    assert.match(source, /sendSupervisorConversation/);
    assert.doesNotMatch(source, /localStorage|sessionStorage|raw JSON/);
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
