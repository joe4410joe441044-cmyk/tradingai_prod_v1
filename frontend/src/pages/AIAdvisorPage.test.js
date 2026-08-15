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
    const hook = join(temporary, "useAdvisorRuntime.mjs");
    const runtimeStatus = join(temporary, "AdvisorRuntimeStatus.mjs");
    const conversation = join(temporary, "AdvisorConversation.mjs");
    const conversationHistory = join(temporary, "AdvisorConversationHistory.mjs");
    const operatorLogin = join(temporary, "OperatorLogin.mjs");
    const disclosure = join(temporary, "AdvisorDisclosure.mjs");
    const react = join(temporary, "react.mjs");
    try {
        await writeFile(hook, [
            "export default () => ({",
            "data:null,connectionState:'LOADING',loading:true,error:null,",
            "lastSuccessfulAt:null,retry:()=>{}",
            "});",
        ].join(""));
        await writeFile(
            runtimeStatus,
            "export default()=>({type:'section',props:{children:'RUNTIME STATUS Loading runtime status'}});",
        );
        await writeFile(
            conversation,
            "export default()=>({type:'section',props:{children:'Prompt Input Send Cancel Clear Conversation Thread'}});",
        );
        await writeFile(
            conversationHistory,
            "export default()=>({type:'div',props:{children:'No archived conversations.（履歴はありません。）'}});",
        );
        await writeFile(
            operatorLogin,
            "export default()=>({type:'div',props:{children:'Operator authentication'}});",
        );
        await writeFile(
            disclosure,
            "export default({title,children})=>({type:'section',props:{'data-disclosure':title,children:[title,children]}});",
        );
        await writeFile(react, "export const useState=(value)=>[value,()=>{}];");
        const code = transformed.code
            .replace('from "react";', `from "${pathToFileURL(react).href}";`)
            .replace(
                'from "../features/ai-advisor/runtime/useAdvisorRuntime";',
                `from "${pathToFileURL(hook).href}";`,
            )
            .replace(
                'from "../components/ai-advisor/AdvisorRuntimeStatus";',
                `from "${pathToFileURL(runtimeStatus).href}";`,
            )
            .replace(
                'from "../components/ai-advisor/AdvisorConversation";',
                `from "${pathToFileURL(conversation).href}";`,
            )
            .replace(
                'from "../components/ai-advisor/AdvisorConversationHistory";',
                `from "${pathToFileURL(conversationHistory).href}";`,
            )
            .replace(
                'from "../components/auth/OperatorLogin";',
                `from "${pathToFileURL(operatorLogin).href}";`,
            )
            .replace(
                'from "../components/ai-advisor/AdvisorDisclosure";',
                `from "${pathToFileURL(disclosure).href}";`,
            );

        await writeFile(output, code);
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

test("AI Advisor is conversation-first: compact header, no hero, collapsed details", async () => {
    let fetchCalls = 0;
    globalThis.fetch = () => { fetchCalls += 1; };
    const { default: AIAdvisorPage } = await loadPage();
    const page = AIAdvisorPage();
    const text = textOf(page);
    const nodes = descendants(page);

    assert.match(text, /AI Advisor/);
    assert.match(text, /AI Advisor（AIアドバイザー）/);
    assert.match(text, /Operator authentication/);
    assert.match(text, /Connecting/);
    assert.match(text, /Prompt Input Send Cancel Clear Conversation Thread/);

    for (const disclosure of [
        "Conversation History（会話履歴） · 0",
        "System / Runtime Details（システム / ランタイム詳細）",
        "Context & Knowledge（コンテキスト / ナレッジ）",
    ]) {
        assert.ok(
            nodes.some((node) => node.props?.["data-disclosure"] === disclosure),
            `expected disclosure: ${disclosure}`,
        );
    }

    assert.match(text, /RUNTIME STATUS/);
    assert.match(text, /No archived conversations/);
    assert.match(text, /CAPABILITIES/);

    assert.equal(fetchCalls, 0);
});

test("AI Advisor has no large hero title or permanent technical columns", async () => {
    const { default: AIAdvisorPage } = await loadPage();
    const text = textOf(AIAdvisorPage());

    assert.doesNotMatch(text, /TradingAI Intelligent Assistant/);
    for (const removed of [
        "ADVISOR WORKSPACE",
        "CONTEXT & SYSTEM",
    ]) {
        assert.doesNotMatch(text, new RegExp(removed));
    }
});

test("Context & Knowledge describes authoritative per-request grounding", async () => {
    const { default: AIAdvisorPage } = await loadPage();
    const text = textOf(AIAdvisorPage());
    assert.match(text, /Authoritative static grounding/);
    assert.match(text, /Approved and hash-verified per request/);
    assert.match(text, /Shown in answer citations when used/);
    assert.doesNotMatch(text, /Not Indexed|No sources configured/);
});

test("AI Advisor source has no direct fetch, mutation, or persistence integration", async () => {
    const source = await readFile(new URL("./AIAdvisorPage.jsx", import.meta.url), "utf8");

    for (const forbidden of [
        "fetch(",
        "axios",
        "WebSocket",
        "startWebSocketRuntime",
        "botStart",
        "botStop",
        "governance",
        "OpenAI",
        "localStorage",
        "sessionStorage",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
    assert.match(source, /useAdvisorRuntime/);
    assert.match(source, /AdvisorRuntimeStatus/);
    assert.match(source, /AdvisorConversation/);
    assert.match(source, /AdvisorDisclosure/);
});
