import { compilePositionModules } from "../../test-support/positionModules.js";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

/* =================================================
   C-P6-3 ACCOUNT VIEW — focused display-only switch contract.

   This suite owns the switch itself: its semantic values,
   the user-facing labels, the initial default, the manual
   override behavior and the guarantee that selecting a view
   performs no mutation. Account rendering details live in
   AccountStatusPage.test.js.
================================================= */

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const loadModule = async () => {
    const source = new URL("./AccountStatusPage.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".account-view-test-"));
    const output = join(temporary, "AccountStatusPage.mjs");
    const modelUrl = new URL("../components/runtime/accountRuntimeModel.js", import.meta.url).href;
    const statusMetricStub = moduleUrl(
        "export default (props)=>({type:'div',props:{children:[{type:'span',props:{'data-testid':props.testId,children:props.value}},props.label]}});",
    );
    const paperCapitalStub = moduleUrl(
        "export default (props)=>({type:'div',props:{className:'paper-capital-control','data-testid':'set-paper-capital',children:props.value || 'SET PAPER CAPITAL（ペーパー資金設定）'}});",
    );
    const usePollingStub = moduleUrl(
        "export default()=>({data:{data:null},loading:false,error:false});",
    );
    try {
        await compilePositionModules(temporary);
        await writeFile(output, transformed.code
            .replace('"../components/runtime/CurrentPositionCard.jsx"', '"./CurrentPositionCard.mjs"')
            .replace('"../components/runtime/LastPositionEventCard.jsx"', '"./LastPositionEventCard.mjs"')
            .replace('from "../hooks/usePolling";', `from "${usePollingStub}";`)
            .replace('from "../components/runtime/PaperCapitalControl";', `from "${paperCapitalStub}";`)
            .replace('from "../components/runtime/StatusMetric";', `from "${statusMetricStub}";`)
            .replace('from "../components/runtime/accountRuntimeModel";', `from "${modelUrl}";`));
        return await import(`${pathToFileURL(output).href}?test=account-view`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const walk = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(walk);
    if (typeof node === "string" || typeof node === "number") return [String(node)];
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return walk(node.type(node.props));
    return [node, ...walk(node.props?.children)];
};
const findByTestId = (nodes, id) => nodes.find(node => (
    typeof node === "object" && node.props?.["data-testid"] === id
));
const texts = (nodes) => nodes.filter((node) => typeof node === "string" && node.trim() !== "");

const botStatus = (selectedMode) => ({
    selectedMode,
    executionMode: "SIMULATION",
    realOrderAllowed: false,
    accountRuntime: {
        realAccount: { exchange: "kucoin", connected: false, authenticated: false, permission: "NOT_VERIFIED" },
        paperAccount: { balance: 1000, equity: 1000, availableBalance: 980, positions: [], available: true, source: "PAPER_SIMULATION" },
        positionsByMode: { PAPER: { status: "FLAT", mode: "PAPER", freshness: "FRESH" }, LIVE: { status: "FLAT", mode: "LIVE", freshness: "FRESH" } },
        lastPositionEventsByMode: { PAPER: { event: "NONE", mode: "PAPER" }, LIVE: { event: "NONE", mode: "LIVE" } },
    },
});

let AccountStatusView;

test.before(async () => {
    ({ AccountStatusView } = await loadModule());
});

test("switch exposes semantic values PAPER / LIVE while the second option is labelled REAL", () => {
    const nodes = walk(AccountStatusView({ botStatus: botStatus("PAPER") }));
    const switchNode = findByTestId(nodes, "account-view-switch");
    assert.ok(switchNode, "switch renders");

    const paper = findByTestId(nodes, "account-view-option-paper");
    const real = findByTestId(nodes, "account-view-option-live");
    assert.ok(paper && real, "both options render");

    // User-facing labels: PAPER and REAL (not LIVE).
    assert.equal(texts(walk(paper)).join(""), "PAPER");
    assert.equal(texts(walk(real)).join(""), "REAL");
    assert.equal(texts(walk(real)).join("").includes("LIVE"), false, "the switch must not be labelled LIVE");
    assert.match(texts(nodes).join(" "), /ACCOUNT VIEW（表示口座）/);
});

test("default selection follows selectedMode and falls back to PAPER for invalid values", () => {
    const cases = [
        ["PAPER", "account-view-option-paper"],
        ["LIVE", "account-view-option-live"],
        [undefined, "account-view-option-paper"],
        [null, "account-view-option-paper"],
        ["", "account-view-option-paper"],
        ["BOGUS", "account-view-option-paper"],
    ];
    for (const [selectedMode, expectedTestId] of cases) {
        const nodes = walk(AccountStatusView({ botStatus: botStatus(selectedMode) }));
        assert.equal(findByTestId(nodes, expectedTestId).props["aria-pressed"], true, `${selectedMode}`);
        const other = expectedTestId === "account-view-option-paper"
            ? "account-view-option-live"
            : "account-view-option-paper";
        assert.equal(findByTestId(nodes, other).props["aria-pressed"], false, `${selectedMode}`);
    }
});

test("manual selection is preserved even if selectedMode changes underneath", async () => {
    // Reproduces the mounted-page guarantee with the pure resolver.
    const source = new URL("../components/runtime/accountRuntimeModel.js", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".account-view-resolver-"));
    const output = join(temporary, "accountRuntimeModel.mjs");
    const apiStub = moduleUrl("export const API={botStatus:()=>'/api/bot/status',paperAccountCapital:()=>'/api/bot/paper-account/capital'};");
    try {
        await writeFile(output, transformed.code.replace('from "../../api/index.js";', `from "${apiStub}";`));
        const { resolveAccountView, initialAccountView } = await import(`${pathToFileURL(output).href}?test=account-view-resolver`);
        assert.equal(initialAccountView("PAPER"), "PAPER");
        assert.equal(initialAccountView("LIVE"), "LIVE");
        assert.equal(resolveAccountView("PAPER", "LIVE"), "LIVE");
        assert.equal(resolveAccountView("LIVE", "PAPER"), "PAPER");
        assert.equal(resolveAccountView("LIVE", null), "LIVE");
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
});

test("selecting PAPER / REAL performs no network mutation", async () => {
    const originalFetch = globalThis.fetch;
    const requests = [];
    globalThis.fetch = async (url, options = {}) => {
        requests.push({ url: String(url), method: (options.method ?? "GET").toUpperCase() });
        return { ok: true, json: async () => ({}) };
    };
    try {
        const nodes = walk(AccountStatusView({
            botStatus: botStatus("PAPER"),
            accountView: "PAPER",
            onAccountViewChange: () => {},
        }));
        findByTestId(nodes, "account-view-option-live").props.onClick();
        findByTestId(nodes, "account-view-option-paper").props.onClick();
    } finally {
        globalThis.fetch = originalFetch;
    }
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
        assert.equal(requests.some((request) => request.method === method), false, `${method} on switch`);
    }
    assert.equal(requests.length, 0, "switch is purely client-side");
});

test("a forced view selects the matching account header", () => {
    const paperNodes = walk(AccountStatusView({ botStatus: botStatus("LIVE"), accountView: "PAPER" }));
    assert.equal(findByTestId(paperNodes, "account-view-header").props["data-view"], "PAPER");
    assert.match(texts(paperNodes).join(" "), /PAPER ACCOUNT \/ ペーパー口座/);

    const realNodes = walk(AccountStatusView({ botStatus: botStatus("PAPER"), accountView: "LIVE" }));
    assert.equal(findByTestId(realNodes, "account-view-header").props["data-view"], "LIVE");
    assert.match(texts(realNodes).join(" "), /REAL \/ LIVE ACCOUNT \/ 実口座/);
});
