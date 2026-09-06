import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const reactStub = `data:text/javascript,${encodeURIComponent([
    "export const useState=(value)=>{",
    "let current=typeof value==='function'?value():value;",
    "return [current,(next)=>{current=typeof next==='function'?next(current):next}];",
    "};",
].join(""))}`;

const loadModule = async () => {
    const source = new URL("./ReplayInvestigationPanel.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".replay-investigation-test-"));
    const output = join(temporary, "ReplayInvestigationPanel.mjs");
    try {
        await writeFile(output, transformed.code.replace('from "react";', `from "${reactStub}";`));
        return await import(`${pathToFileURL(output).href}?test=replay-investigation`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const descendants = (node) => {
    if (node === null || node === undefined || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};

const textOf = (node) => {
    if (node === null || node === undefined) return "";
    const children = node?.props?.children;
    if (Array.isArray(children)) return children.map((child) => (
        typeof child === "object" ? textOf(child) : String(child ?? "")
    )).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("ReplayInvestigationPanel is collapsed by default and hides replay children", async () => {
    const { default: ReplayInvestigationPanel } = await loadModule();
    const panel = ReplayInvestigationPanel({ children: "REPLAY CHILD" });
    const nodes = descendants(panel);
    assert.equal(textOf(nodes.find(({ props }) => props?.id === "mi-replay-investigation-title")), "REPLAY / INVESTIGATION");
    const toggle = nodes.find(({ type }) => type === "button");
    assert.equal(toggle.props["aria-expanded"], false);
    assert.equal(nodes.some((node) => textOf(node) === "REPLAY CHILD"), false);
});

test("ReplayInvestigationPanel renders replay children when not collapsed", async () => {
    const { default: ReplayInvestigationPanel } = await loadModule();
    const panel = ReplayInvestigationPanel({ children: "REPLAY CHILD", defaultCollapsed: false });
    const nodes = descendants(panel);
    const toggle = nodes.find(({ type }) => type === "button");
    assert.equal(toggle.props["aria-expanded"], true);
    assert.equal(nodes.some((node) => textOf(node) === "REPLAY CHILD"), true);
});

test("ReplayInvestigationView gates content by expanded state and wires the toggle", async () => {
    const { ReplayInvestigationView } = await loadModule();
    const collapsed = ReplayInvestigationView({ expanded: false, children: "REPLAY CHILD" });
    assert.equal(descendants(collapsed).some((node) => textOf(node) === "REPLAY CHILD"), false);
    const expanded = ReplayInvestigationView({ expanded: true, children: "REPLAY CHILD" });
    assert.equal(descendants(expanded).some((node) => textOf(node) === "REPLAY CHILD"), true);
    let toggled = false;
    const wired = ReplayInvestigationView({ expanded: false, onToggle: () => { toggled = true; }, children: "REPLAY CHILD" });
    descendants(wired).find(({ type }) => type === "button").props.onClick();
    assert.equal(toggled, true);
});
