import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

const loadDrawer = async () => {
    const source = new URL("./AiHelpDrawer.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const temporary = await mkdtemp(join(directory, ".drawer-behavior-test-"));
    const output = join(temporary, "AiHelpDrawer.mjs");
    const react = join(temporary, "react.mjs");
    try {
        await writeFile(react, [
            "export const useEffect=()=>{};",
            "export const useRef=()=>({current:null});",
        ].join("\n"));
        const code = transformed.code
            .replace('from "react";', `from "${pathToFileURL(react).href}";`);
        await writeFile(output, code);
        return (await import(`${pathToFileURL(output).href}?test=drawer`)).default;
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const descendants = (node) => {
    if (node == null || node === false || node === true) return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};

const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};

test("drawer renders nothing when closed (default)", async () => {
    const AiHelpDrawer = await loadDrawer();
    const closed = AiHelpDrawer({
        id: "drawer",
        side: "right",
        open: false,
        title: "Supervisor ガイド",
        onClose: () => {},
        children: "guide content",
    });
    assert.equal(closed, null);
});

test("drawer renders its overlay, dialog, title, and close control when open", async () => {
    const AiHelpDrawer = await loadDrawer();
    const open = AiHelpDrawer({
        id: "drawer",
        side: "right",
        open: true,
        title: "Supervisor ガイド",
        onClose: () => {},
        children: "guide content",
    });
    const nodes = descendants(open);
    const text = textOf(open);
    assert.match(text, /Supervisor ガイド/);
    assert.match(text, /guide content/);
    assert.ok(nodes.some((node) => node.props?.role === "dialog"));
    assert.ok(nodes.some((node) => node.props?.["aria-modal"] === "true"));
    assert.ok(nodes.some((node) => node.props?.["onClick"]));
    assert.ok(nodes.some((node) => String(node.props?.className || "").includes("ai-help-overlay--right")));
});

test("drawer by default is closed so underlying chat content is not displaced", async () => {
    const AiHelpDrawer = await loadDrawer();
    const result = AiHelpDrawer({
        open: false,
        title: "どのAIに聞く？",
        children: "which ai",
    });
    assert.equal(result, null);
});
