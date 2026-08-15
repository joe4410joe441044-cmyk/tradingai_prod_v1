import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const historySource = () => readFile(
    new URL("./AdvisorConversationHistory.jsx", import.meta.url),
    "utf8",
);

test("history provides compact preview and bilingual View/Hide full detail", async () => {
    const source = await historySource();
    for (const label of [
        "Question（質問）",
        "Answer（回答）",
        "Status（状態）",
        "View（表示）",
        "Hide（閉じる）",
    ]) {
        assert.ok(source.includes(label), `expected label: ${label}`);
    }
    assert.match(source, /exchange\.userMessage\.content/);
    assert.match(source, /exchange\.assistantMessage\.content/);
    assert.match(source, /exchange\.assistantMessage\.groundedResponse/);
    assert.match(source, /exchange\.status/);
    assert.match(source, /setExpanded\(\(value\) => !value\)/);
    assert.doesNotMatch(source, /dangerouslySetInnerHTML|innerHTML/);
});

test("history is session-only and adds no persistence or network integration", async () => {
    const source = await historySource();
    for (const forbidden of [
        "localStorage", "sessionStorage", "indexedDB", "fetch(", "axios", "WebSocket",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
});
