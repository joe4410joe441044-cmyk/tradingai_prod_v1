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
    const modelUrl = new URL("./appNavigationModel.js", import.meta.url).href;
    const reactStub = `data:text/javascript,${encodeURIComponent([
        "export const useEffect=(effect)=>effect();",
        "export const useRef=(value)=>({current:value});",
        "export const useState=(value)=>{",
        "let current=typeof value==='function'?value():value;",
        "return [current,(next)=>{current=typeof next==='function'?next(current):next}];",
        "};",
    ].join(""))}`;
    try {
        await writeFile(output, transformed.code
            .replace('from "react";', `from "${reactStub}";`)
            .replace('from "./appNavigationModel";', `from "${modelUrl}";`));
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

test("navigation switches all pages, exposes active state, and calls no trading API", async () => {
    const listeners = new Map();
    let fetchCalls = 0;
    globalThis.fetch = () => { fetchCalls += 1; };
    globalThis.window = {
        location: { pathname: "/" },
        history: {
            pushState: (_state, _title, path) => {
                globalThis.window.location.pathname = path;
                historyPaths.push(path);
            },
            replaceState: (_state, _title, path) => { globalThis.window.location.pathname = path; },
        },
        addEventListener: (type, listener) => listeners.set(type, listener),
        removeEventListener: (type) => listeners.delete(type),
    };
    const historyPaths = [];
    const { default: AppNavigation } = await loadModule();
    const paths = [];
    let nodes = descendants(AppNavigation({ currentPath: "/", onPathChange: (path) => paths.push(path) }));
    let buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[0].props["aria-current"], "page");
    assert.equal(buttons[1].props["aria-current"], undefined);
    assert.equal(buttons[2].props["aria-current"], undefined);
    assert.equal(buttons[3].props["aria-current"], undefined);
    buttons[1].props.onClick();
    assert.equal(paths.at(-1), "/market-intelligence");

    nodes = descendants(AppNavigation({ currentPath: "/market-intelligence", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[1].props["aria-current"], "page");
    assert.match(buttons[1].props.className, /--active/);
    buttons[2].props.onClick();
    assert.equal(paths.at(-1), "/ai-advisor");

    nodes = descendants(AppNavigation({ currentPath: "/ai-advisor", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons.length, 7);
    assert.equal(buttons[0].props["aria-current"], undefined);
    assert.equal(buttons[1].props["aria-current"], undefined);
    assert.equal(buttons[2].props["aria-current"], "page");
    assert.match(buttons[2].props.className, /--active/);
    assert.equal(buttons[3].props["aria-current"], undefined);
    assert.equal(buttons[4].props["aria-current"], undefined);
    assert.equal(buttons[5].props["aria-current"], undefined);
    buttons[3].props.onClick();
    assert.equal(paths.at(-1), "/money-management");

    nodes = descendants(AppNavigation({ currentPath: "/money-management", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[3].props["aria-current"], "page");
    assert.match(buttons[3].props.className, /--active/);
    assert.equal(buttons[4].props["aria-current"], undefined);
    buttons[4].props.onClick();
    assert.equal(paths.at(-1), "/market-recorder");

    nodes = descendants(AppNavigation({ currentPath: "/market-recorder", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[4].props["aria-current"], "page");
    assert.match(buttons[4].props.className, /--active/);
    assert.equal(buttons[5].props["aria-current"], undefined);
    buttons[5].props.onClick();
    assert.equal(paths.at(-1), "/supervisor");
    assert.equal(historyPaths.at(-1), "/supervisor");

    nodes = descendants(AppNavigation({ currentPath: "/supervisor", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[5].props["aria-current"], "page");
    assert.match(buttons[5].props.className, /--active/);
    buttons[6].props.onClick();
    assert.equal(paths.at(-1), "/account-status");

    nodes = descendants(AppNavigation({ currentPath: "/account-status", onPathChange: (path) => paths.push(path) }));
    buttons = nodes.filter(({ type }) => type === "button");
    assert.equal(buttons[6].props["aria-current"], "page");
    assert.match(buttons[6].props.className, /--active/);

    globalThis.window.location.pathname = "/ai-advisor";
    listeners.get("popstate")();
    assert.equal(paths.at(-1), "/ai-advisor");
    globalThis.window.location.pathname = "/supervisor";
    listeners.get("popstate")();
    assert.equal(paths.at(-1), "/supervisor");

    globalThis.window.location.pathname = "/unknown";
    listeners.get("popstate")();
    assert.equal(paths.at(-1), "/");
    assert.equal(globalThis.window.location.pathname, "/");

    buttons[0].props.onClick();
    assert.equal(paths.at(-1), "/");
    assert.equal(fetchCalls, 0);
    assert.equal(nodes.some(({ type }) => type === "nav"), true);
});

test("navigation labels and paths remain unique and preserve existing items", async () => {
    globalThis.window = {
        location: { pathname: "/" },
        history: { pushState() {}, replaceState() {} },
        addEventListener() {},
        removeEventListener() {},
    };
    const { default: AppNavigation } = await loadModule();
    const nodes = descendants(AppNavigation({ currentPath: "/not-an-app-path", onPathChange() {} }));
    const buttons = nodes.filter(({ type }) => type === "button");
    const labels = buttons.map((button) => button.props.children);
    const paths = [];
    globalThis.window.history.pushState = (_state, _title, path) => paths.push(path);
    buttons.forEach((button) => button.props.onClick());

    assert.deepEqual(labels, [
        "DASHBOARD", "MARKET INTELLIGENCE", "AI ADVISOR",
        "MONEY MANAGEMENT", "MARKET RECORDER", "SUPERVISOR",
        "ACCOUNT STATUS",
    ]);
    assert.equal(new Set(labels).size, labels.length);
    assert.equal(new Set(paths).size, paths.length);
    assert.equal(new Set(labels).has("ACCOUNT STATUS"), true);
    assert.equal(new Set(paths).has("/account-status"), true);
    assert.equal(paths.at(-1), "/account-status");
});

test("tabs reorder left and right without changing identity or routes", async () => {
    globalThis.window = {
        location: { pathname: "/money-management" },
        history: { pushState() {}, replaceState() {} },
        addEventListener() {},
        removeEventListener() {},
        setTimeout: (callback) => callback(),
    };
    const { NavigationTabs } = await loadModule();
    const { reorderNavigationItems } = await import("./appNavigationModel.js");
    const defaults = [
        { label: "DASHBOARD", path: "/" },
        { label: "MARKET INTELLIGENCE", path: "/market-intelligence" },
        { label: "AI ADVISOR", path: "/ai-advisor" },
        { label: "MONEY MANAGEMENT", path: "/money-management" },
        { label: "MARKET RECORDER", path: "/market-recorder" },
        { label: "SUPERVISOR", path: "/supervisor" },
    ];

    const movedLeft = reorderNavigationItems(
        defaults,
        "/money-management",
        "/market-intelligence",
    );
    assert.deepEqual(movedLeft.map(({ label }) => label), [
        "DASHBOARD", "MONEY MANAGEMENT", "MARKET INTELLIGENCE",
        "AI ADVISOR", "MARKET RECORDER", "SUPERVISOR",
    ]);
    const movedRight = reorderNavigationItems(
        movedLeft,
        "/money-management",
        "/market-recorder",
    );
    assert.deepEqual(movedRight.map(({ label }) => label), [
        "DASHBOARD", "MARKET INTELLIGENCE", "AI ADVISOR",
        "MARKET RECORDER", "MONEY MANAGEMENT", "SUPERVISOR",
    ]);
    assert.deepEqual(
        movedRight.map(({ path }) => path).sort(),
        defaults.map(({ path }) => path).sort(),
    );

    const navigated = [];
    const buttons = descendants(NavigationTabs({
        currentPath: "/money-management",
        draggedPath: null,
        items: movedRight,
        navigate: (_event, path) => navigated.push(path),
        onDragEnd() {},
        onDragEnter() {},
        onDragOver() {},
        onDragStart() {},
        onDrop() {},
    })).filter(({ type }) => type === "button");
    const moneyManagement = buttons.find(
        ({ props }) => props.children === "MONEY MANAGEMENT",
    );
    assert.equal(moneyManagement.props["aria-current"], "page");
    assert.match(moneyManagement.props.className, /--active/);
    moneyManagement.props.onClick({});
    assert.equal(navigated.at(-1), "/money-management");
    assert.equal(buttons.every(({ props }) => props.draggable === "true"), true);
});

test("drag handlers suppress navigation and automatically persist path order", async () => {
    const timers = [];
    const writes = [];
    globalThis.window = {
        location: { pathname: "/" },
        history: { pushState() {}, replaceState() {} },
        addEventListener() {},
        removeEventListener() {},
        localStorage: {
            getItem: () => null,
            setItem: (key, value) => writes.push([key, value]),
        },
        setTimeout: (callback) => timers.push(callback),
    };
    const { default: AppNavigation } = await loadModule();
    const paths = [];
    const buttons = descendants(AppNavigation({
        currentPath: "/",
        onPathChange: (path) => paths.push(path),
    })).filter(({ type }) => type === "button");
    const transfer = {
        effectAllowed: null,
        dropEffect: null,
        setData(type, value) {
            assert.equal(type, "text/plain");
            assert.equal(value, "/money-management");
        },
    };
    buttons[3].props.onDragStart({ dataTransfer: transfer });
    assert.equal(transfer.effectAllowed, "move");
    let prevented = false;
    let stopped = false;
    buttons[3].props.onClick({
        preventDefault: () => { prevented = true; },
        stopPropagation: () => { stopped = true; },
    });
    assert.equal(prevented, true);
    assert.equal(stopped, true);
    assert.notEqual(paths.at(-1), "/money-management");
    buttons[1].props.onDragEnter();
    buttons[1].props.onDragOver({
        dataTransfer: transfer,
        preventDefault() {},
    });
    assert.equal(transfer.dropEffect, "move");
    assert.deepEqual(writes, [[
        "tradingai.navigation.tabOrder.v1",
        JSON.stringify([
            "/", "/money-management", "/market-intelligence",
            "/ai-advisor", "/market-recorder", "/supervisor",
            "/account-status",
        ]),
    ]]);
    buttons[1].props.onDrop({ preventDefault() {} });
    buttons[3].props.onDragEnd();
    assert.equal(timers.length, 1);

    const source = await readFile(
        new URL("./AppNavigation.jsx", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(source, /fetch\(|axios|sessionStorage|\/api\//);
});

test("saved order restores canonical tabs, routes, and active identity", async () => {
    globalThis.window = {
        location: { pathname: "/money-management" },
        history: { pushState() {}, replaceState() {} },
        addEventListener() {},
        removeEventListener() {},
        localStorage: {
            getItem: () => JSON.stringify([
                "/", "/money-management", "/market-intelligence",
                "/ai-advisor", "/market-recorder", "/supervisor",
            ]),
            setItem() {},
        },
    };
    const { default: AppNavigation } = await loadModule();
    const navigated = [];
    globalThis.window.history.pushState = (_state, _title, path) => {
        navigated.push(path);
    };
    const buttons = descendants(AppNavigation({
        currentPath: "/money-management",
        onPathChange() {},
    })).filter(({ type }) => type === "button");

    assert.deepEqual(buttons.map(({ props }) => props.children), [
        "DASHBOARD", "MONEY MANAGEMENT", "MARKET INTELLIGENCE",
        "AI ADVISOR", "MARKET RECORDER", "SUPERVISOR",
        "ACCOUNT STATUS",
    ]);
    assert.equal(buttons[1].props["aria-current"], "page");
    buttons[1].props.onClick();
    assert.equal(navigated.length, 0);
    buttons[2].props.onClick();
    assert.equal(navigated.at(-1), "/market-intelligence");
});

test("restore ignores invalid, unknown, and duplicate paths and appends current tabs", async () => {
    const {
        loadNavigationItems,
        restoreNavigationItems,
    } = await import("./appNavigationModel.js");
    const canonical = [
        { label: "A", path: "/a" },
        { label: "B", path: "/b" },
        { label: "C", path: "/c" },
        { label: "NEW", path: "/new" },
    ];

    assert.deepEqual(
        restoreNavigationItems(
            canonical,
            JSON.stringify(["/c", "/unknown", "/c", "/a"]),
        ).map(({ path }) => path),
        ["/c", "/a", "/b", "/new"],
    );
    assert.deepEqual(
        restoreNavigationItems(canonical, "not json").map(({ path }) => path),
        ["/a", "/b", "/c", "/new"],
    );
    assert.deepEqual(
        restoreNavigationItems(canonical, JSON.stringify({ path: "/c" }))
            .map(({ path }) => path),
        ["/a", "/b", "/c", "/new"],
    );
    assert.deepEqual(
        loadNavigationItems(canonical, null).map(({ path }) => path),
        ["/a", "/b", "/c", "/new"],
    );
});

test("storage read and write failures keep navigation reorderable", async () => {
    const {
        loadNavigationItems,
        reorderAndPersistNavigationItems,
    } = await import("./appNavigationModel.js");
    const canonical = [
        { label: "A", path: "/a" },
        { label: "B", path: "/b" },
        { label: "C", path: "/c" },
    ];
    const readFailure = {
        getItem() { throw new Error("blocked"); },
    };
    const writeFailure = {
        setItem() { throw new Error("quota"); },
    };

    assert.deepEqual(loadNavigationItems(canonical, readFailure), canonical);
    assert.deepEqual(
        reorderAndPersistNavigationItems(
            canonical,
            "/c",
            "/a",
            writeFailure,
        ).map(({ path }) => path),
        ["/c", "/a", "/b"],
    );
});
