import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./AppNavigation.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".navigation-test-"));
    const output = join(temporary, "AppNavigation.mjs");
    const reactStub = "data:text/javascript,export const useEffect=(effect)=>effect()";
    try {
        await writeFile(output, transformed.code.replace('from "react";', `from "${reactStub}";`));
        return await import(`${pathToFileURL(output).href}?test=navigation`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};

test("navigation switches both pages, exposes active state, and calls no trading API", async () => {
    const listeners = new Map();
    let fetchCalls = 0;
    globalThis.fetch = () => { fetchCalls += 1; };
    globalThis.window = {
        location: { pathname: "/" },
        history: {
            pushState: (_state, _title, path) => { globalThis.window.location.pathname = path; },
            replaceState: (_state, _title, path) => { globalThis.window.location.pathname = path; },
        },
        addEventListener: (type, listener) => listeners.set(type, listener),
        removeEventListener: (type) => listeners.delete(type),
    };
    const { default: AppNavigation } = await loadModule();
    const paths = [];
    let nodes = descendants(AppNavigation({ currentPath: "/", onPathChange: (path) => paths.push(path) }));
    let buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[0].props["aria-current"], "page");
    assert.equal(buttons[1].props["aria-current"], undefined);
    buttons[1].props.onClick();
    assert.equal(paths.at(-1), "/market-intelligence");

    nodes = descendants(AppNavigation({ currentPath: "/market-intelligence", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[1].props["aria-current"], "page");
    assert.match(buttons[1].props.className, /--active/);
    buttons[0].props.onClick();
    assert.equal(paths.at(-1), "/");
    assert.equal(fetchCalls, 0);
    assert.equal(nodes.some(({ type }) => type === "nav"), true);
});
