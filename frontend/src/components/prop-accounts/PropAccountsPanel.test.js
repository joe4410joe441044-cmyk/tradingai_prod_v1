import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const jsxRuntimeStub = moduleUrl([
    "export const Fragment=Symbol('Fragment');",
    "export const jsx=(type,props,key)=>({type,key,props:props||{}});",
    "export const jsxs=jsx;",
].join(""));
const reactStub = moduleUrl([
    "export const useEffect=()=>{};export const useRef=(value)=>({current:value});",
    "export const useMemo=(factory)=>factory();",
    "export const useState=(value)=>[value,()=>{}];",
].join(""));

async function loadComponent() {
    const dependencyRoot = process.env.TRADINGAI_FRONTEND_NODE_MODULES;
    assert.ok(dependencyRoot, "TRADINGAI_FRONTEND_NODE_MODULES is required for JSX transformation");
    const vite = await import(pathToFileURL(join(dependencyRoot, "vite/dist/node/index.js")).href);
    const sourceUrl = new URL("./PropAccountsPanel.jsx", import.meta.url);
    const source = await readFile(sourceUrl, "utf8");
    const transformed = await vite.transformWithOxc(source, sourceUrl.pathname);
    const temporary = await mkdtemp("/tmp/cc-2s-component-test-");
    const output = join(temporary, "PropAccountsPanel.mjs");
    const outcomeCardUrl = new URL("./PropOutcomeCard.jsx", import.meta.url);
    const outcomeCardSource = await readFile(outcomeCardUrl, "utf8");
    const outcomeCardTransformed = await vite.transformWithOxc(outcomeCardSource, outcomeCardUrl.pathname);
    const outcomeCardOutput = join(temporary, "PropOutcomeCard.mjs");
    const modelUrl = new URL("../../features/prop-accounts/propAccountsViewModel.js", import.meta.url).href;
    const fixturesUrl = new URL("../../features/prop-accounts/propAccountsFixtures.js", import.meta.url).href;
    const outcomeFixturesUrl = new URL("../../features/prop-accounts/propOutcomeFixtures.js", import.meta.url).href;
    const code = transformed.code
        .replace(/from\s+["']react\/jsx-runtime["']/g, `from "${jsxRuntimeStub}"`)
        .replace(/from\s+["']react["']/g, `from "${reactStub}"`)
        .replace('from "../../features/prop-accounts/propAccountsViewModel.js"', `from "${modelUrl}"`)
        .replace('from "../../features/prop-accounts/propAccountsFixtures.js"', `from "${fixturesUrl}"`)
        .replace('from "./PropOutcomeCard.jsx"', `from "${pathToFileURL(outcomeCardOutput).href}"`)
        .replace('from "../../features/prop-accounts/propOutcomeFixtures.js"', `from "${outcomeFixturesUrl}"`)
        .replace('import "./prop-accounts.css";', "");
    const outcomeCardCode = outcomeCardTransformed.code
        .replace(/from\s+["']react\/jsx-runtime["']/g, `from "${jsxRuntimeStub}"`);
    await writeFile(outcomeCardOutput, outcomeCardCode);
    await writeFile(output, code);
    try {
        return await import(`${pathToFileURL(output).href}?test=${Date.now()}`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
}

const descendants = (node) => {
    if (node === null || node === undefined || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [String(node)];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};
const textOf = (node) => descendants(node)
    .filter((item) => typeof item === "string")
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
const byTestId = (node, id) => descendants(node).find((item) => (
    typeof item === "object" && item.props?.["data-testid"] === id
));

let PropAccountsView;
let normalizePropAccountsView;
let createPropAccountsFixture;
let PROP_ACCOUNT_ID;
let NORMAL_ACCOUNT_ID;

test.before(async () => {
    ({ PropAccountsView } = await loadComponent());
    ({ normalizePropAccountsView } = await import("../../features/prop-accounts/propAccountsViewModel.js"));
    ({ createPropAccountsFixture, PROP_ACCOUNT_ID, NORMAL_ACCOUNT_ID } = await import("../../features/prop-accounts/propAccountsFixtures.js"));
});

const render = (scenarioId, viewedAccountId = PROP_ACCOUNT_ID, extra = {}) => PropAccountsView({
    scenarioId,
    viewModel: normalizePropAccountsView(createPropAccountsFixture({ scenarioId, viewedAccountId })),
    ...extra,
});

test("fixture banner and disabled execution remain visible in all scenarios", async () => {
    const { PROP_FIXTURE_SCENARIOS } = await import("../../features/prop-accounts/propAccountsFixtures.js");
    for (const { id } of PROP_FIXTURE_SCENARIOS) {
        const node = render(id);
        assert.match(textOf(byTestId(node, "fixture-banner")), /サンプル表示 \/ 実口座未接続/);
        assert.match(textOf(byTestId(node, "execution-state")), /DISABLED/);
        const buttonLabels = descendants(node)
            .filter((item) => item?.type === "button")
            .map(textOf)
            .join(" ");
        assert.doesNotMatch(buttonLabels, /\b(?:START|BUY|SELL|CLOSE)\b/);
    }
});

test("account selector emits exact account scope and keeps displayed data isolated", () => {
    const selected = [];
    const prop = render("connected_read_only", PROP_ACCOUNT_ID, {
        onAccountChange: (accountId) => selected.push(accountId),
    });
    const normalButton = byTestId(prop, "account-option-normal");
    normalButton.props.onClick();
    assert.deepEqual(selected, [NORMAL_ACCOUNT_ID]);
    assert.match(textOf(byTestId(prop, "selected-account-identity")), /HyroTrader Demo/);
    assert.match(textOf(byTestId(prop, "positions-card")), /BTCUSDT/);

    const normal = render("connected_read_only", NORMAL_ACCOUNT_ID);
    assert.match(textOf(byTestId(normal, "selected-account-identity")), /通常取引サンプル口座/);
    assert.doesNotMatch(textOf(byTestId(normal, "positions-card")), /BTCUSDT/);
});

test("state axes render independently for partial data", () => {
    const node = render("partial_data");
    assert.match(textOf(byTestId(node, "connection-state")), /CONNECTED_READ_ONLY/);
    assert.match(textOf(byTestId(node, "data-quality-state")), /PARTIAL/);
    assert.match(textOf(byTestId(node, "rules-readiness-state")), /RULES_UNKNOWN/);
    assert.match(textOf(byTestId(node, "execution-state")), /DISABLED/);
    assert.match(textOf(byTestId(node, "open-orders-card")), /取得できませんでした/);
});

test("rules unknown never renders READY or fabricated thresholds", () => {
    const rules = byTestId(render("rules_unknown"), "prop-rules-card");
    assert.match(textOf(rules), /RULES_UNKNOWN/);
    assert.doesNotMatch(textOf(rules), /架空ルールのサンプル/);
    assert.match(textOf(rules), /未取得/);
});

test("connected fixture preserves precision, negative PnL, and sample rule warning", () => {
    const node = render("connected_read_only");
    assert.match(textOf(byTestId(node, "metric-balance")), /12,345,678,901,234,567,890\.123456789012345678 USDT/);
    assert.match(textOf(byTestId(node, "metric-equity")), /USD相当/);
    assert.match(textOf(byTestId(node, "metric-realized-pnl")), /−42\.000000000000000009/);
    assert.match(textOf(byTestId(node, "prop-rules-card")), /架空ルールのサンプル/);
});

test("details expose dialog semantics and explicit close", () => {
    const closes = [];
    const node = render("partial_data", PROP_ACCOUNT_ID, {
        detailsOpen: true,
        onDetailsClose: () => closes.push("closed"),
    });
    const details = byTestId(node, "prop-details");
    assert.ok(details);
    assert.equal(details.props.role, "dialog");
    assert.equal(details.props["aria-modal"], "true");
    assert.equal(details.props.tabIndex, "-1");
    const closeButton = descendants(details).find((item) => item?.props?.["aria-label"] === "状態詳細を閉じる");
    closeButton.props.onClick();
    assert.deepEqual(closes, ["closed"]);
});

test("invalid view model renders a safe error and does not fallback", () => {
    const invalid = normalizePropAccountsView({ schemaVersion: "invalid", fixture: { enabled: false } });
    const node = PropAccountsView({ viewModel: invalid });
    assert.ok(byTestId(node, "prop-accounts-invalid"));
    assert.match(textOf(node), /fallbackやREADY補完は行っていません/);
    assert.equal(byTestId(node, "selected-account-identity"), undefined);
});

test("component and preview sources contain no API, storage, runtime, or operational wiring", async () => {
    const files = [
        new URL("./PropAccountsPanel.jsx", import.meta.url),
        new URL("../../../prop-accounts-preview/main.jsx", import.meta.url),
    ];
    for (const file of files) {
        const source = await readFile(file, "utf8");
        assert.doesNotMatch(source, /fetch\s*\(|axios|WebSocket|localStorage|sessionStorage|indexedDB|\/api\//);
        assert.doesNotMatch(source, /botStart|manualTrade|placeOrder|cancelOrder|closePosition/);
    }
});


test("invalid collection data is never rendered as a normal empty list", () => {
    const fixture = createPropAccountsFixture({ scenarioId: "connected_read_only" });
    fixture.accounts[1] = {
        ...fixture.accounts[1],
        positions: {
            quality: "COMPLETE",
            items: [{ symbol: "BTCUSDT", side: "LONG", quantity: "NaN" }],
            missingFields: [],
        },
    };
    const node = PropAccountsView({
        scenarioId: "connected_read_only",
        viewModel: normalizePropAccountsView(fixture),
    });
    const positions = textOf(byTestId(node, "positions-card"));
    assert.match(positions, /FAILED/);
    assert.match(positions, /取得できませんでした/);
    assert.doesNotMatch(positions, /正常な空一覧/);
});


test("synthetic evaluation scenarios render without execution or challenge authority", () => {
    const passing = render("connected_read_only", PROP_ACCOUNT_ID, { evaluationScenarioId: "calculation_pass" });
    assert.match(textOf(byTestId(passing, "outcome-card")), /計算結果 — PASS/);
    assert.match(textOf(byTestId(passing, "outcome-card")), /計算上の適合 ≠ 取引可能/);
    assert.match(textOf(byTestId(passing, "outcome-card")), /Challenge合格・READY・実行権限を意味しません/);

    const blocked = render("connected_read_only", PROP_ACCOUNT_ID, { evaluationScenarioId: "maximum_loss_block" });
    assert.match(textOf(byTestId(blocked, "outcome-card")), /計算結果 — BLOCK/);
    assert.match(textOf(byTestId(blocked, "outcome-rule-results")), /STATIC_MAXIMUM_LOSS BLOCK/);

    const unknown = render("connected_read_only", PROP_ACCOUNT_ID, { evaluationScenarioId: "unsupported_required_rule" });
    assert.match(textOf(byTestId(unknown, "outcome-summary")), /UNKNOWN.*PARTIAL.*DISABLED/);
    assert.ok(byTestId(unknown, "outcome-evidence-details"));
});

test("pre-evaluation rejection has no fabricated outcome and normal account hides PROP outcome", () => {
    const rejected = render("connected_read_only", PROP_ACCOUNT_ID, { evaluationScenarioId: "pre_evaluation_validation_failure" });
    assert.match(textOf(byTestId(rejected, "outcome-card")), /Complete Outcomeは生成されていません/);
    const normal = render("connected_read_only", NORMAL_ACCOUNT_ID);
    assert.equal(byTestId(normal, "outcome-card"), undefined);
});
