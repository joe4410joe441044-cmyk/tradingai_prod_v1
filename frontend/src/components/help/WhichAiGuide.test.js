import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

const loadGuide = async () => {
    const source = new URL("./WhichAiGuide.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const temporary = await mkdtemp(join(directory, ".which-ai-guide-test-"));
    const output = join(temporary, "WhichAiGuide.mjs");
    const disclosure = join(temporary, "HelpDisclosure.mjs");
    const react = join(temporary, "react.mjs");
    try {
        await writeFile(disclosure, "export default({title,children})=>({type:'section',props:{'data-disclosure':title,children}});");
        await writeFile(react, "export const useState=(value)=>[value,()=>{}];");
        const code = transformed.code
            .replace('from "react";', `from "${pathToFileURL(react).href}";`)
            .replace('from "./HelpDisclosure";', `from "${pathToFileURL(disclosure).href}";`);
        await writeFile(output, code);
        return (await import(`${pathToFileURL(output).href}?test=which-ai`)).default;
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

test("Which AI routes Master, MM, and Advisor without implying any executes", async () => {
    const WhichAiGuide = await loadGuide();
    const text = textOf(
        WhichAiGuide({
            open: true,
            children: null,
            focusSection: null,
        }),
    );
    assert.match(text, /TradingAI全体/);
    assert.match(text, /マスター・スーパーバイザー/);
    assert.match(text, /MMスーパーバイザー/);
    assert.match(text, /AIアドバイザー/);
    assert.match(text, /どのAIも実行できません/);
});

test("Which AI keeps the FULL detail behind a disclosure", async () => {
    const source = await readFile(new URL("./WhichAiGuide.jsx", import.meta.url), "utf8");
    assert.match(source, /HelpDisclosure title="詳しく見る"/);
    assert.match(source, /決定論的なPython \/ Governance \/ Safety/);
});

test("Which AI has no network or persistence integration", async () => {
    const source = await readFile(new URL("./WhichAiGuide.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(source, /fetch\(|axios|WebSocket|localStorage|sessionStorage/);
});
