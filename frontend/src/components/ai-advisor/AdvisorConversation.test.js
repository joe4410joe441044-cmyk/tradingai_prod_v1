import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

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
    const source = await readFile(new URL("./AdvisorConversation.jsx", import.meta.url), "utf8");
    for (const forbidden of [
        "localStorage", "sessionStorage", "indexedDB", "console.",
        "fetch(", "WebSocket", "api.openai.com", "botStart", "botStop",
        "providerOverride", "modelOverride", "clipboard",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
});
