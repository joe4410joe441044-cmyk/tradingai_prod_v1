import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./MarketIntelligenceStatusLayer.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".mi-status-test-"));
    const output = join(temporary, "MarketIntelligenceStatusLayer.mjs");
    const engineUrl = pathToFileURL(join(directory, "../../features/market-intelligence/replay/replayEngine.js")).href;
    const providerStub = "data:text/javascript,export const useMarketIntelligence=()=>globalThis.__MI_STATUS_CONTEXT__";
    const code = transformed.code
        .replace('from "../../features/market-intelligence/replay/replayEngine.js";', `from "${engineUrl}";`)
        .replace('from "../../state/market-intelligence/MarketIntelligenceProvider.jsx";', `from "${providerStub}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=status`);
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
const textOf = (node) => {
    const children = node?.props?.children;
    if (Array.isArray(children)) return children.map((child) => typeof child === "object" ? textOf(child) : String(child ?? "")).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("page status distinguishes empty, loading, ready, partial, unavailable, and error", async () => {
    const { default: Status } = await loadModule();
    const render = (replayEngine) => {
        globalThis.__MI_STATUS_CONTEXT__ = { replayEngine, applyReplayCommand: () => {} };
        const nodes = descendants(Status());
        return { nodes, text: nodes.map(textOf).join(" ") };
    };
    assert.match(render({ machine: { state: "IDLE" }, dataset: null }).text, /No replay selected/);
    assert.match(render({ machine: { state: "LOADING" }, dataset: {} }).text, /Replay is loading/);
    assert.match(render({ machine: { state: "REPLAY_READY" }, dataset: {}, projection: { currentEvent: {}, dataQuality: "VALID" } }).text, /Replay ready/);
    assert.match(render({ machine: { state: "REPLAY_READY" }, dataset: {}, projection: { currentEvent: {}, dataQuality: "PARTIAL" } }).text, /partial data/);
    assert.match(render({ machine: { state: "REPLAY_READY" }, dataset: {}, projection: { currentEvent: null } }).text, /data unavailable/);
    const error = render({ machine: { state: "ERROR" }, engineError: { message: "Malformed replay." } });
    assert.match(error.text, /Malformed replay/);
    assert.equal(error.nodes.some(({ props }) => props?.role === "alert"), true);
});

test("retry is explicit and dispatches only the replay retry command", async () => {
    const { default: Status } = await loadModule();
    const commands = [];
    globalThis.__MI_STATUS_CONTEXT__ = {
        replayEngine: { machine: { state: "ERROR" }, engineError: { message: "Failed." } },
        applyReplayCommand: (command) => commands.push(command),
    };
    const nodes = descendants(Status());
    const retry = nodes.find(({ type, props }) => type === "button" && textOf({ props }) === "RETRY");
    retry.props.onClick();
    assert.deepEqual(commands, [{ type: "RETRY" }]);
});
