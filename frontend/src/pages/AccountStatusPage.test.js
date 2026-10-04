import { compilePositionModules } from "../../test-support/positionModules.js";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const loadModule = async () => {
    const source = new URL("./AccountStatusPage.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".account-status-test-"));
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
        return await import(`${pathToFileURL(output).href}?test=account-status-page`);
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
    typeof node === "object"
    && node.props?.["data-testid"] === id
));

const texts = (nodes) => nodes.filter((node) => typeof node === "string" && node.trim() !== "");

const readTestIdValue = (nodes, id) => {
    const node = findByTestId(nodes, id);
    if (!node) return undefined;
    const children = node.props?.children;
    if (Array.isArray(children)) {
        return children
            .flatMap((child) => (typeof child === "string" ? [child] : walk([child])))
            .filter((value) => typeof value === "string")
            .join("");
    }
    return String(children ?? "");
};

const cardText = (nodes, id) => texts(walk(findByTestId(nodes, id))).join(" ").replace(/\s+/g, " ").trim();

/* =================================================
   Canonical fixtures.

   PAPER and REAL values are deliberately different so
   cross-account contamination is provable.
================================================= */

const REAL_NOT_CONNECTED = {
    exchange: "kucoin",
    accountType: "KUCOIN_FUTURES",
    connected: false,
    authenticated: false,
    apiKeyPresent: false,
    permission: "NOT_VERIFIED",
    balance: null,
    equity: null,
    availableBalance: null,
    positions: [],
    positionSummary: null,
    lastSync: null,
    stale: false,
    loading: false,
};

const paperFlat = {
    status: "FLAT", mode: "PAPER", control: "UNKNOWN", freshness: "FRESH",
    source: "PAPER_SIMULATION", positions: [],
};
const liveFlat = {
    status: "FLAT", mode: "LIVE", control: "UNKNOWN", freshness: "FRESH",
    source: "KUCOIN_FUTURES", positions: [],
};

const paperEvent = {
    event: "CLOSED", mode: "PAPER", control: "BOT", symbol: "PAPEREVENT",
    side: "LONG", quantity: 1, quantityUnit: "coin", entryPrice: 1, exitPrice: 1.05,
    realizedPnl: 5, holdingMs: 643, exitReason: "TAKE_PROFIT", tradeId: "PAPER-1",
    source: "PARAMETER_PERFORMANCE_TRADE_HISTORY", realizedPnlAuthoritative: true,
};
const liveEvent = {
    event: "CLOSED", mode: "LIVE", control: "MANUAL", symbol: "REALEVENT",
    side: "SHORT", quantity: 2, quantityUnit: "coin", entryPrice: 2, exitPrice: 1.9,
    realizedPnl: -3, holdingMs: 1200, exitReason: "STOP_LOSS", tradeId: "LIVE-1",
    source: "PARAMETER_PERFORMANCE_TRADE_HISTORY", realizedPnlAuthoritative: true,
};

const paperAccount = {
    balance: 10000,
    equity: 10000,
    availableBalance: 9800,
    positions: [],
    totalPnl: 0,
    realizedPnl: 0,
    unrealizedPnl: 0,
    source: "PAPER_SIMULATION",
    positionState: "FLAT",
    available: true,
};

const connectedRealAccount = {
    exchange: "kucoin",
    accountType: "KUCOIN_FUTURES",
    connected: true,
    authenticated: true,
    apiKeyPresent: true,
    permission: "READ_ONLY",
    balance: 7.92,
    equity: 7.92,
    availableBalance: 5.42,
    walletBalance: 7.92,
    unrealizedPnl: 1.23,
    realizedPnlToday: 0.5,
    totalPnlToday: 1.73,
    marginUsed: 0,
    marginAvailable: 7.92,
    marginRatio: 5,
    positions: [],
    positionSummary: "FLAT",
    lastSync: Date.now() / 1000,
    stale: false,
    loading: false,
};

const baseStatus = (overrides = {}) => ({
    selectedMode: "PAPER",
    executionMode: "SIMULATION",
    realOrderAllowed: false,
    real_order_allowed: false,
    executionEntryAllowed: false,
    liveOrderEntryAllowed: false,
    executionEnabled: false,
    botState: "STOPPED",
    pendingOrder: false,
    exchange: "kucoin",
    exchangeAuth: "NOT_VERIFIED",
    exchangeConnection: "NOT_CONNECTED",
    apiKeyStatus: "MISSING",
    permission: "NOT_VERIFIED",
    accountType: "UNKNOWN",
    realAccountConnected: false,
    balance: 1000,
    equity: 1000,
    availableBalance: 980,
    pnl: 0,
    accountRuntime: {
        realAccount: { ...REAL_NOT_CONNECTED },
        paperAccount: { ...paperAccount },
        positionsByMode: { PAPER: { ...paperFlat }, LIVE: { ...liveFlat } },
        lastPositionEventsByMode: { PAPER: { ...paperEvent }, LIVE: { ...liveEvent } },
        currentPosition: { ...paperFlat },
        lastPositionEvent: { ...paperEvent },
        execution: {
            selectedMode: "PAPER",
            executionMode: "SIMULATION",
            realOrderAllowed: false,
        },
        connection: {
            exchange: "kucoin",
            connected: false,
            authenticated: false,
            apiKeyStatus: "MISSING",
            permission: "NOT_VERIFIED",
        },
    },
    ...overrides,
});

const PAPER_BOT_STATUS = baseStatus();

const READ_ONLY_BOT_STATUS = baseStatus({
    selectedMode: "LIVE",
    executionMode: "LIVE",
    executionEnabled: true,
    botState: "LIVE",
    realAccountConnected: true,
    accountRuntime: {
        ...baseStatus().accountRuntime,
        realAccount: { ...connectedRealAccount },
        execution: {
            selectedMode: "LIVE",
            executionMode: "LIVE",
            realOrderAllowed: false,
        },
        connection: {
            exchange: "kucoin",
            connected: true,
            authenticated: true,
            apiKeyStatus: "VERIFIED",
            permission: "READ_ONLY",
        },
    },
});

const view = (botStatus, accountView, extra = {}) => walk(
    AccountStatusView({ botStatus, accountView, ...extra }),
);

let AccountStatusView;

test.before(async () => {
    ({ AccountStatusView } = await loadModule());
});

/* =================================================
   A-J: ACCOUNT VIEW state and switch
================================================= */

test("A. selectedMode=PAPER initial ACCOUNT VIEW is PAPER", () => {
    const nodes = view(PAPER_BOT_STATUS);
    assert.equal(findByTestId(nodes, "account-view-header").props["data-view"], "PAPER");
    assert.match(cardText(nodes, "account-view-header"), /PAPER ACCOUNT \/ ペーパー口座/);
    assert.equal(findByTestId(nodes, "account-view-option-paper").props["aria-pressed"], true);
    assert.equal(findByTestId(nodes, "account-view-option-live").props["aria-pressed"], false);
});

test("B. selectedMode=LIVE initial ACCOUNT VIEW is REAL", () => {
    const nodes = view(READ_ONLY_BOT_STATUS);
    assert.equal(findByTestId(nodes, "account-view-header").props["data-view"], "LIVE");
    assert.match(cardText(nodes, "account-view-header"), /REAL \/ LIVE ACCOUNT \/ 実口座/);
    assert.equal(findByTestId(nodes, "account-view-option-live").props["aria-pressed"], true);
});

test("C. invalid selectedMode initial ACCOUNT VIEW defaults to PAPER", () => {
    for (const selectedMode of [undefined, null, "", "UNKNOWN"]) {
        const nodes = view(baseStatus({ selectedMode }));
        assert.equal(
            findByTestId(nodes, "account-view-header").props["data-view"],
            "PAPER",
        );
    }
});

test("D/E. switching PAPER <-> REAL invokes the change handler with semantic values", () => {
    const calls = [];
    const nodes = walk(AccountStatusView({
        botStatus: PAPER_BOT_STATUS,
        accountView: "PAPER",
        onAccountViewChange: (value) => calls.push(value),
    }));
    findByTestId(nodes, "account-view-option-live").props.onClick();
    findByTestId(nodes, "account-view-option-paper").props.onClick();
    assert.deepEqual(calls, ["LIVE", "PAPER"]);
});

test("F. manual ACCOUNT VIEW is preserved across polling refreshes", async () => {
    // selectedMode changes under the mounted view, but a manual choice always wins.
    const { resolveAccountView, initialAccountView } = await loadPrefixedModule();
    assert.equal(resolveAccountView("PAPER", "LIVE"), "LIVE");
    assert.equal(resolveAccountView("LIVE", "PAPER"), "PAPER");
    assert.equal(resolveAccountView("LIVE", null), "LIVE");
    assert.equal(resolveAccountView("PAPER", null), "PAPER");
    assert.equal(initialAccountView("LIVE"), "LIVE");
    assert.equal(initialAccountView("PAPER"), "PAPER");
    assert.equal(initialAccountView("garbage"), "PAPER");
});

test("G/H/I/J. ACCOUNT VIEW and ACCOUNT RUNTIME are independent", () => {
    const cases = [
        { view: "PAPER", selectedMode: "PAPER", runtime: "PAPER" },
        { view: "LIVE", selectedMode: "PAPER", runtime: "PAPER" },
        { view: "PAPER", selectedMode: "LIVE", runtime: "LIVE" },
        { view: "LIVE", selectedMode: "LIVE", runtime: "LIVE" },
    ];
    for (const { view: accountView, selectedMode, runtime } of cases) {
        const status = selectedMode === "LIVE" && accountView === "PAPER"
            ? baseStatus({ selectedMode })
            : selectedMode === "PAPER" && accountView === "LIVE"
                ? baseStatus({
                    selectedMode,
                    realAccountConnected: true,
                    accountRuntime: {
                        ...baseStatus().accountRuntime,
                        realAccount: { ...connectedRealAccount },
                    },
                })
                : selectedMode === "LIVE"
                    ? READ_ONLY_BOT_STATUS
                    : PAPER_BOT_STATUS;
        const nodes = view(status, accountView);
        // Runtime is global and follows selectedMode, never accountView.
        assert.equal(readTestIdValue(nodes, "runtime-mode"), runtime);
        assert.equal(readTestIdValue(nodes, "live-context-mode"), runtime);
        // The selected account header follows accountView.
        assert.equal(findByTestId(nodes, "account-view-header").props["data-view"], accountView);
    }
});

test("ACCOUNT VIEW switch never performs a network mutation", async () => {
    const originalFetch = globalThis.fetch;
    const requests = [];
    globalThis.fetch = async (url, options = {}) => {
        requests.push({ url: String(url), method: (options.method ?? "GET").toUpperCase() });
        return { ok: true, json: async () => ({}) };
    };
    try {
        const nodes = walk(AccountStatusView({
            botStatus: PAPER_BOT_STATUS,
            accountView: "PAPER",
            onAccountViewChange: () => {},
        }));
        findByTestId(nodes, "account-view-option-live").props.onClick();
        findByTestId(nodes, "account-view-option-paper").props.onClick();
    } finally {
        globalThis.fetch = originalFetch;
    }
    const mutations = requests.filter(({ method }) => ["POST", "PUT", "PATCH", "DELETE"].includes(method));
    assert.deepEqual(mutations, []);
    assert.deepEqual(requests, []);
});

/* =================================================
   Financial card — one card, view-selected source
================================================= */

test("financial card follows ACCOUNT VIEW and keeps PAPER / REAL isolated", () => {
    const paperNodes = view(PAPER_BOT_STATUS, "PAPER");
    assert.equal(readTestIdValue(paperNodes, "financial-equity-value"), "10,000.00");
    assert.equal(readTestIdValue(paperNodes, "financial-availableBalance-value"), "9,800.00");
    assert.equal(readTestIdValue(paperNodes, "financial-walletBalance-value"), "10,000.00");
    assert.match(cardText(paperNodes, "financial-walletBalance"), /BALANCE/);
    assert.match(cardText(paperNodes, "financial-realizedPnlToday"), /REALIZED PNL/);
    assert.match(cardText(paperNodes, "financial-totalPnlToday"), /TOTAL PNL/);

    const realNodes = view(READ_ONLY_BOT_STATUS, "LIVE");
    assert.equal(readTestIdValue(realNodes, "financial-equity-value"), "7.92");
    assert.equal(readTestIdValue(realNodes, "financial-availableBalance-value"), "5.42");
    assert.equal(readTestIdValue(realNodes, "financial-walletBalance-value"), "7.92");
    assert.equal(readTestIdValue(realNodes, "financial-unrealizedPnl-value"), "+1.23");
    assert.equal(readTestIdValue(realNodes, "financial-marginRatio-value"), "5.00");

    // PAPER value never appears in REAL view and vice versa.
    assert.notEqual(readTestIdValue(realNodes, "financial-equity-value"), "10,000.00");
    assert.notEqual(readTestIdValue(paperNodes, "financial-equity-value"), "7.92");
});

test("PAPER margin cells have no canonical paper equivalent and fail closed", () => {
    const nodes = view(PAPER_BOT_STATUS, "PAPER");
    for (const key of ["marginUsed", "marginAvailable", "marginRatio"]) {
        assert.equal(findByTestId(nodes, `financial-${key}-state`).props.children, "UNAVAILABLE");
        assert.equal(readTestIdValue(nodes, `financial-${key}-value`), "—");
        assert.notEqual(readTestIdValue(nodes, `financial-${key}-value`), "0.00");
    }
});

test("REAL unavailable account fails closed and never fabricates zero", () => {
    // selectedMode PAPER but REAL view forced -> real account not connected.
    const nodes = view(PAPER_BOT_STATUS, "LIVE");
    assert.equal(findByTestId(nodes, "financial-equity-state").props.children, "UNAVAILABLE");
    assert.equal(readTestIdValue(nodes, "financial-equity-value"), "—");
    assert.notEqual(readTestIdValue(nodes, "financial-equity-value"), "0.00");
});

test("PAPER unavailable account fails closed and never fabricates zero", () => {
    const status = baseStatus({
        accountRuntime: {
            ...baseStatus().accountRuntime,
            paperAccount: { ...paperAccount, available: false },
        },
    });
    const nodes = view(status, "PAPER");
    assert.equal(findByTestId(nodes, "financial-equity-state").props.children, "UNAVAILABLE");
    assert.equal(readTestIdValue(nodes, "financial-equity-value"), "—");
    assert.notEqual(readTestIdValue(nodes, "financial-equity-value"), "0.00");
    assert.notEqual(readTestIdValue(nodes, "financial-realizedPnlToday-value"), "0.00");
});

test("authoritative zero remains a valid value in both views", () => {
    const paperNodes = view(PAPER_BOT_STATUS, "PAPER");
    assert.equal(readTestIdValue(paperNodes, "financial-unrealizedPnl-value"), "0.00");
    assert.equal(readTestIdValue(paperNodes, "financial-realizedPnlToday-value"), "0.00");

    const realNodes = view(READ_ONLY_BOT_STATUS, "LIVE");
    // connectedRealAccount has marginUsed = 0 (authoritative flat account).
    assert.equal(readTestIdValue(realNodes, "financial-marginUsed-value"), "0.00");
});

test("9-field grid and 3x3 order are preserved in both views", () => {
    const keys = [
        "equity", "availableBalance", "walletBalance", "unrealizedPnl",
        "realizedPnlToday", "totalPnlToday", "marginUsed", "marginAvailable", "marginRatio",
    ];
    for (const accountView of ["PAPER", "LIVE"]) {
        const nodes = view(READ_ONLY_BOT_STATUS, accountView);
        const grid = findByTestId(nodes, "financial-metric-grid");
        const cardIds = walk(grid)
            .filter((node) => typeof node === "object")
            .map((node) => node.props?.["data-testid"])
            .filter((id) => keys.includes(String(id).replace("financial-", ""))
                && String(id).startsWith("financial-"));
        assert.deepEqual(cardIds, keys.map((key) => `financial-${key}`));
    }
});

/* =================================================
   Current position — view-selected canonical source
================================================= */

const positionStatus = (position) => baseStatus({
    accountRuntime: {
        ...baseStatus().accountRuntime,
        positionsByMode: {
            PAPER: { ...position },
            LIVE: { ...liveEventPosition() },
        },
    },
});
const liveEventPosition = () => ({
    status: "OPEN", mode: "LIVE", control: "MANUAL", symbol: "REALPOS",
    side: "SHORT", quantity: 9, quantityUnit: "contract", freshness: "FRESH",
    source: "KUCOIN_FUTURES", positions: [],
});

test("current position source follows ACCOUNT VIEW", () => {
    const paperNodes = view(PAPER_BOT_STATUS, "PAPER");
    assert.match(cardText(paperNodes, "current-position-card"), /PAPEREVENT|PAPER/);
    assert.equal(cardText(paperNodes, "current-position-card").includes("REALPOS"), false);

    const realNodes = view(READ_ONLY_BOT_STATUS, "LIVE");
    assert.equal(cardText(realNodes, "current-position-card").includes("PAPER"), false);
});

test("position matrix across PAPER covers OPEN_LONG/OPEN_SHORT/FLAT/UNKNOWN/STALE/MULTIPLE", () => {
    const open = {
        status: "OPEN", mode: "PAPER", control: "BOT", symbol: "PAPERUSDT",
        side: "LONG", quantity: 6174, quantityUnit: "coin", coinQuantity: 6174,
        entryPrice: 0.016195, markPrice: 0.016195, unrealizedPnl: 0,
        holdingMs: 643, freshness: "FRESH", source: "PAPER_SIMULATION", positions: [],
    };
    const cases = [
        [{ ...open }, "LONG"],
        [{ ...open, side: "SHORT" }, "SHORT"],
        [{ status: "FLAT", freshness: "FRESH" }, "NO OPEN POSITION"],
        [{ status: "UNKNOWN", freshness: "FRESH" }, "POSITION STATE UNAVAILABLE"],
        [{ ...open, status: "UNKNOWN", freshness: "STALE" }, "POSITION DATA IS STALE"],
        [{
            status: "UNKNOWN", reason: "MULTIPLE_POSITIONS",
            positions: [{ symbol: "XRPUSDTM", side: "LONG" }, { symbol: "ETHUSDTM", side: "SHORT" }],
        }, "2 OPEN POSITIONS DETECTED"],
    ];
    for (const [position, expected] of cases) {
        const nodes = view(positionStatus(position), "PAPER");
        assert.match(cardText(nodes, "current-position-card"), new RegExp(expected));
    }
});

test("cross-mode position isolation: PAPER never appears in REAL view and vice versa", () => {
    const status = baseStatus({
        accountRuntime: {
            ...baseStatus().accountRuntime,
            positionsByMode: {
                PAPER: { status: "OPEN", mode: "PAPER", control: "BOT", symbol: "PAPERONLY", side: "LONG", quantity: 1, quantityUnit: "coin", freshness: "FRESH", positions: [] },
                LIVE: { status: "OPEN", mode: "LIVE", control: "MANUAL", symbol: "REALONLY", side: "SHORT", quantity: 2, quantityUnit: "contract", freshness: "FRESH", positions: [] },
            },
        },
    });
    const paperNodes = view(status, "PAPER");
    assert.match(cardText(paperNodes, "current-position-card"), /PAPERONLY/);
    assert.equal(cardText(paperNodes, "current-position-card").includes("REALONLY"), false);

    const realNodes = view(status, "LIVE");
    assert.match(cardText(realNodes, "current-position-card"), /REALONLY/);
    assert.equal(cardText(realNodes, "current-position-card").includes("PAPERONLY"), false);
});

test("missing requested dual projection shows UNKNOWN instead of cross-mode fallback", () => {
    const status = baseStatus({
        accountRuntime: {
            ...baseStatus().accountRuntime,
            positionsByMode: { PAPER: { ...paperFlat } },
            currentPosition: { status: "OPEN", mode: "LIVE", symbol: "LEGACYLIVE", side: "LONG", quantity: 1, freshness: "FRESH", positions: [] },
        },
    });
    const realNodes = view(status, "LIVE");
    assert.equal(cardText(realNodes, "current-position-card").includes("LEGACYLIVE"), false);
    assert.match(cardText(realNodes, "current-position-card"), /POSITION STATE UNAVAILABLE/);
});

/* =================================================
   Last position event — view-selected canonical source
================================================= */

const eventStatus = (event) => baseStatus({
    accountRuntime: {
        ...baseStatus().accountRuntime,
        lastPositionEventsByMode: {
            PAPER: { ...event },
            LIVE: { ...liveEvent },
        },
    },
});

test("last position event source follows ACCOUNT VIEW", () => {
    const status = baseStatus({
        accountRuntime: {
            ...baseStatus().accountRuntime,
            lastPositionEventsByMode: {
                PAPER: { ...paperEvent, symbol: "PAPEREVENT" },
                LIVE: { ...liveEvent, symbol: "REALEVENT" },
            },
        },
    });
    const paperNodes = view(status, "PAPER");
    assert.match(cardText(paperNodes, "last-position-event-card"), /PAPEREVENT/);
    assert.equal(cardText(paperNodes, "last-position-event-card").includes("REALEVENT"), false);

    const realNodes = view(status, "LIVE");
    assert.match(cardText(realNodes, "last-position-event-card"), /REALEVENT/);
    assert.equal(cardText(realNodes, "last-position-event-card").includes("PAPEREVENT"), false);
});

test("last event matrix: NONE / CLOSED zero / positive / negative", () => {
    const cases = [
        [{ event: "NONE" }, "NO RECENT POSITION EVENT"],
        [{ ...paperEvent, realizedPnl: 0 }, "0.00 USDT"],
        [{ ...paperEvent, realizedPnl: 12.5 }, "12.50 USDT"],
        [{ ...paperEvent, realizedPnl: -8.25 }, "-8.25 USDT"],
    ];
    for (const [event, expected] of cases) {
        const nodes = view(eventStatus(event), "PAPER");
        assert.match(cardText(nodes, "last-position-event-card"), new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
});

test("cross-mode event isolation: PAPER event never leaks into REAL and vice versa", () => {
    const nodes = view(PAPER_BOT_STATUS, "PAPER");
    assert.equal(cardText(nodes, "last-position-event-card").includes("REALEVENT"), false);
    const realNodes = view(READ_ONLY_BOT_STATUS, "LIVE");
    assert.equal(cardText(realNodes, "last-position-event-card").includes("PAPEREVENT"), false);
});

/* =================================================
   Global runtime / context / read-only invariants
================================================= */

test("Account Status renders Account Runtime and Live Context cards globally", () => {
    const nodes = view(PAPER_BOT_STATUS, "PAPER");
    assert.ok(findByTestId(nodes, "account-runtime-section"));
    assert.ok(findByTestId(nodes, "runtime-mode"));
    assert.ok(findByTestId(nodes, "runtime-bot-state"));
    assert.ok(findByTestId(nodes, "runtime-real-orders"));
    assert.ok(findByTestId(nodes, "execution-authority-grid"));
    assert.ok(findByTestId(nodes, "live-context-section"));
    assert.equal(readTestIdValue(nodes, "live-context-mode"), "PAPER");
    assert.equal(readTestIdValue(nodes, "live-context-execution"), "NOT ALLOWED");
});

test("UNKNOWN / UNAVAILABLE / STALE are never upgraded to a READY state", () => {
    const staleStatus = baseStatus({
        accountRuntime: {
            ...baseStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                stale: true,
                permission: "NOT_VERIFIED",
            },
        },
    });
    const nodes = view(staleStatus, "LIVE");
    assert.equal(readTestIdValue(nodes, "real-sync-status"), "STALE");
    assert.equal(readTestIdValue(nodes, "live-context-freshness"), "STALE");
    assert.equal(readTestIdValue(nodes, "authority-real-order-allowed"), "NO");
    const allText = texts(nodes);
    assert.equal(allText.some((text) => /LIVE READY|READY TO|FULL LIVE/i.test(text)), false);
});

test("UNKNOWN account state fails closed and is never upgraded to READY", () => {
    const unknownStatus = baseStatus({
        permission: "UNKNOWN",
        accountType: "UNKNOWN",
        accountRuntime: {
            ...baseStatus().accountRuntime,
            realAccount: {
                ...REAL_NOT_CONNECTED,
                permission: "UNKNOWN",
                accountType: "UNKNOWN",
                balance: null,
                lastSync: null,
            },
        },
    });
    const nodes = view(unknownStatus, "LIVE");
    assert.equal(readTestIdValue(nodes, "real-permission"), "--");
    assert.equal(readTestIdValue(nodes, "real-account-type"), "--");
    assert.equal(readTestIdValue(nodes, "real-auth"), "NOT_VERIFIED");
    assert.equal(findByTestId(nodes, "financial-equity-state").props.children, "UNAVAILABLE");
    assert.notEqual(readTestIdValue(nodes, "financial-equity-value"), "0.00");
    const allText = texts(nodes);
    assert.equal(allText.some((text) => /LIVE READY|READY TO|FULL LIVE/i.test(text)), false);
});

test("Account Status renders only the view switch, DETAILS toggle and paper capital controls", () => {
    const nodes = view(PAPER_BOT_STATUS, "PAPER", { detailsExpanded: false });
    // PAPER view: no REAL DETAILS toggle; the switch is the only pair of buttons.
    assert.equal(findByTestId(nodes, "account-details-toggle"), undefined);
    const buttons = nodes.filter((node) => typeof node === "object" && node.type === "button");
    const testIds = buttons.map((button) => button.props["data-testid"]).filter(Boolean);
    assert.deepEqual(testIds, ["account-view-option-paper", "account-view-option-live"]);
    const allText = texts(nodes);
    const operationPhrases = [
        "START BOT", "STOP BOT", "AUTO TRADE ON", "AUTO TRADE OFF",
        "LOOP ON", "LOOP OFF", "PAPER AUTO START", "PAPER AUTO STOP",
        "LIVE START", "LIVE STOP", "EMERGENCY", "CANCEL ORDER",
        "CLOSE POSITION", "EXECUTION ENABLE",
    ];
    operationPhrases.forEach((phrase) => {
        assert.equal(
            allText.some((text) => new RegExp(`\\b${phrase}\\b`, "i").test(text)),
            false,
            `must not render operation control: ${phrase}`,
        );
    });
});

test("DETAILS toggle only appears in REAL view and toggles", () => {
    const collapsed = view(READ_ONLY_BOT_STATUS, "LIVE", { detailsExpanded: false });
    const toggle = findByTestId(collapsed, "account-details-toggle");
    assert.equal(toggle.props["aria-expanded"], false);
    assert.match(String(findByTestId(collapsed, "account-financial-details").props.className), /as-financial-details/);
    assert.doesNotMatch(String(findByTestId(collapsed, "account-financial-details").props.className), /as-financial-details--open/);

    let called = false;
    const interacted = view(READ_ONLY_BOT_STATUS, "LIVE", {
        detailsExpanded: false,
        onDetailsToggle: () => { called = true; },
    });
    findByTestId(interacted, "account-details-toggle").props.onClick();
    assert.equal(called, true);

    const expanded = view(READ_ONLY_BOT_STATUS, "LIVE", { detailsExpanded: true });
    assert.equal(findByTestId(expanded, "account-details-toggle").props["aria-expanded"], true);
    assert.match(
        String(findByTestId(expanded, "account-financial-details").props.className),
        /as-financial-details--open/,
    );
    ["real-exchange", "real-connection", "real-auth", "real-api-key", "real-permission", "real-account-type", "real-sync-status", "real-last-sync"]
        .forEach((id) => assert.ok(findByTestId(expanded, id), `DETAILS preserves ${id}`));
});

test("READ ONLY badges are preserved and duplicate account badge removed", () => {
    const nodes = view(READ_ONLY_BOT_STATUS, "LIVE");
    assert.equal(texts(nodes).filter((value) => value === "READ ONLY").length >= 1, true);
    assert.ok(findByTestId(nodes, "selected-account-authority"));
    assert.equal(findByTestId(nodes, "real-account-badge"), undefined);
});

/* =================================================
   Duplicate PAPER summary removal + SET PAPER CAPITAL
================================================= */

test("redundant PAPER / SIMULATION summary is removed", () => {
    const nodes = view(PAPER_BOT_STATUS, "PAPER");
    assert.equal(findByTestId(nodes, "paper-account-section"), undefined);
    assert.equal(findByTestId(nodes, "paper-account-metrics"), undefined);
    assert.equal(findByTestId(nodes, "paper-balance"), undefined);
    assert.equal(findByTestId(nodes, "paper-equity"), undefined);
});

test("SET PAPER CAPITAL control remains accessible in PAPER and REAL views", () => {
    for (const accountView of ["PAPER", "LIVE"]) {
        const nodes = view(PAPER_BOT_STATUS, accountView);
        assert.ok(findByTestId(nodes, "paper-capital-section"), `${accountView}: section`);
        assert.ok(findByTestId(nodes, "set-paper-capital"), `${accountView}: control`);
    }
});

test("canonical position cards follow the financial status and remain independent", () => {
    const status = baseStatus();
    for (const accountView of ["PAPER", "LIVE"]) {
        const nodes = view(status, accountView);
        const ids = nodes.filter(n => typeof n === "object").map(n => n.props?.["data-testid"]);
        const order = ["account-financial-status", "current-position-card", "last-position-event-card", "account-runtime-section"];
        for (let i = 1; i < order.length; i++) {
            assert.ok(ids.indexOf(order[i - 1]) < ids.indexOf(order[i]), `${accountView}: order ${order[i]}`);
        }
    }
});

/* =================================================
   Bilingual labels + CSS contract
================================================= */

test("Account Status renders bilingual English（日本語）labels", () => {
    const realText = texts(view(READ_ONLY_BOT_STATUS, "LIVE")).join(" ");
    [
        "Account Status（アカウント状況）",
        "ACCOUNT VIEW（表示口座）",
        "REAL / LIVE ACCOUNT / 実口座",
        "Production Account（本番口座）",
        "Account Financial Status",
        "EQUITY",
        "純資産",
        "AVAILABLE BALANCE",
        "利用可能額",
        "Authentication（取引所認証）",
        "Account Runtime（アカウント実行状態）",
        "Live Context（LIVE状態）",
        "SET PAPER CAPITAL / ペーパー資金設定",
        "SET PAPER CAPITAL（ペーパー資金設定）",
        "DETAILS",
    ].forEach((label) => {
        assert.equal(realText.includes(label), true, `missing bilingual label: ${label}`);
    });

    const paperText = texts(view(PAPER_BOT_STATUS, "PAPER")).join(" ");
    [
        "PAPER ACCOUNT / ペーパー口座",
        "Simulation Account（シミュレーション口座）",
        "利用可能額",
        "SET PAPER CAPITAL / ペーパー資金設定",
    ].forEach((label) => {
        assert.equal(paperText.includes(label), true, `missing PAPER bilingual label: ${label}`);
    });
});

test("Account View switch CSS keeps a compact segmented selector across breakpoints", async () => {
    const css = await readFile(new URL("../styles/dashboard.css", import.meta.url), "utf8");
    [
        ".account-status-page .as-account-view",
        ".account-status-page .as-account-view-option",
        ".account-status-page .as-account-view-option--selected",
        ".account-status-page .as-account-view-options",
        "grid-template-columns: repeat(3, minmax(0, 1fr))",
        "grid-template-columns: repeat(2, minmax(0, 1fr))",
        "grid-template-columns: 1fr",
    ].forEach((rule) => assert.equal(css.includes(rule), true, `missing CSS contract: ${rule}`));
});

/* Load the raw model helpers once for the poll-preservation test. */
let prefixedModulePromise;
const loadPrefixedModule = async () => {
    if (!prefixedModulePromise) {
        const source = new URL("../components/runtime/accountRuntimeModel.js", import.meta.url);
        const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
        const temporary = await mkdtemp(join(directory, ".account-view-helper-test-"));
        const output = join(temporary, "accountRuntimeModel.mjs");
        const apiStub = moduleUrl(
            "export const API={botStatus:()=>'/api/bot/status',paperAccountCapital:()=>'/api/bot/paper-account/capital'};",
        );
        try {
            await writeFile(output, transformed.code.replace('from "../../api/index.js";', `from "${apiStub}";`));
            prefixedModulePromise = import(`${pathToFileURL(output).href}?test=account-view-helper`);
        } finally {
            await rm(temporary, { recursive: true, force: true });
        }
    }
    return prefixedModulePromise;
};
