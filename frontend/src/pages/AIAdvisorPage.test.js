import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadPage = async () => {
    const source = new URL("./AIAdvisorPage.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const temporary = await mkdtemp(join(directory, ".ai-advisor-page-test-"));
    const output = join(temporary, "AIAdvisorPage.mjs");
    try {
        await writeFile(output, transformed.code);
        return await import(`${pathToFileURL(output).href}?test=ai-advisor`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};
const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};

test("AI Advisor renders a static, interaction-free platform shell", async () => {
    let fetchCalls = 0;
    globalThis.fetch = () => { fetchCalls += 1; };
    const { default: AIAdvisorPage } = await loadPage();
    const page = AIAdvisorPage();
    const text = textOf(page);
    const nodes = descendants(page);

    assert.match(text, /AI ADVISOR/);
    assert.match(text, /TradingAI Knowledge, Runtime & Development Intelligence/);
    assert.match(text, /Platform Ready/);
    assert.match(text, /AI Provider/);
    assert.match(text, /Not Configured/);
    assert.match(text, /API/);
    assert.match(text, /Disabled/);
    assert.match(text, /Runtime/);
    assert.match(text, /Not Connected/);
    assert.match(text, /Knowledge/);
    assert.match(text, /Not Indexed/);
    for (const heading of [
        "CONVERSATIONS",
        "ADVISOR WORKSPACE",
        "CONTEXT",
        "RUNTIME",
        "KNOWLEDGE",
        "CAPABILITIES",
    ]) {
        assert.match(text, new RegExp(heading));
    }

    const input = nodes.find(({ type }) => type === "input");
    const button = nodes.find(({ type }) => type === "button");
    const statusGroup = nodes.find(({ props }) => (
        props?.["aria-label"] === "AI Advisor system status"
    ));

    assert.equal(input.props.disabled, true);
    assert.equal(input.props["aria-label"], "AI Advisor prompt");
    assert.equal(button.props.disabled, true);
    assert.equal(button.props.type, "button");
    assert.match(textOf(button), /Send/);
    assert.ok(statusGroup);
    assert.equal(fetchCalls, 0);
});

test("AI Advisor source contains no runtime, API, or persistence integration", async () => {
    const source = await readFile(new URL("./AIAdvisorPage.jsx", import.meta.url), "utf8");

    for (const forbidden of [
        "fetch(",
        "axios",
        "WebSocket",
        "startWebSocketRuntime",
        "botStatus",
        "OpenAI",
        "localStorage",
        "sessionStorage",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
});
