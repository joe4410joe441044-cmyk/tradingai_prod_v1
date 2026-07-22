import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./AIIntelligenceWorkspace.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".ai-intelligence-test-"));
    const output = join(temporary, "AIIntelligenceWorkspace.mjs");
    try {
        await writeFile(output, transformed.code);
        return await import(`${pathToFileURL(output).href}?test=ai-intelligence`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    return textOf(node.props?.children);
};
const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    return [node, ...descendants(node.props?.children)];
};

test("AI intelligence workspace renders final decision and the specified skeleton sections", async () => {
    const { default: AIIntelligenceWorkspace } = await loadModule();
    const finalDecision = { type: "section", props: { children: "AI FINAL DECISION" } };
    const workspace = AIIntelligenceWorkspace({ finalDecision });
    const text = textOf(workspace);
    for (const expected of ["AI INTELLIGENCE", "Real-time Market Recognition & AI Decision Engine", "AI FINAL DECISION",
        "Detector Summary", "Feature Snapshot", "Strategy", "AI Review", "Governance", "EXECUTION / POSITION"])
        assert.match(text, new RegExp(expected));
    const skeletons = descendants(workspace).filter(({ props }) => props?.className
        ?.split(" ").includes("mi-ai-intelligence__section"));
    assert.equal(skeletons.length, 6);
    assert.equal(skeletons.filter(({ props }) => props["aria-label"] === "EXECUTION / POSITION").length, 1);
    assert.equal(skeletons.some(({ props }) => props["aria-label"] === "Execution" || props["aria-label"] === "Position"), false);
});
