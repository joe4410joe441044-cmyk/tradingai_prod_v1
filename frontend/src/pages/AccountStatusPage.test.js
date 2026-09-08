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
        await writeFile(output, transformed.code
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
    return node ? String(node.props?.children ?? "") : undefined;
};

const PAPER_BOT_STATUS = {
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
        realAccount: {
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
        },
        paperAccount: {
            balance: 1000,
            equity: 1000,
            availableBalance: 980,
            positions: [],
            totalPnl: 0,
            source: "PAPER_SIMULATION",
            positionState: "FLAT",
            available: true,
        },
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
};

const READ_ONLY_BOT_STATUS = {
    ...PAPER_BOT_STATUS,
    selectedMode: "LIVE",
    executionMode: "LIVE",
    realOrderAllowed: false,
    executionEntryAllowed: false,
    liveOrderEntryAllowed: false,
    executionEnabled: true,
    botState: "LIVE",
    pendingOrder: false,
    realAccountConnected: true,
    accountRuntime: {
        ...PAPER_BOT_STATUS.accountRuntime,
        realAccount: {
            exchange: "kucoin",
            accountType: "KUCOIN_FUTURES",
            connected: true,
            authenticated: true,
            apiKeyPresent: true,
            permission: "READ_ONLY",
            balance: 1500,
            equity: 1500,
            availableBalance: 1200,
            positions: [],
            positionSummary: "FLAT",
            lastSync: Date.now() / 1000,
            stale: false,
            loading: false,
        },
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
};

test("Account Status renders Real / Live as primary and Paper / Simulation as secondary", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    const real = findByTestId(nodes, "real-account-section");
    const paper = findByTestId(nodes, "paper-account-section");
    assert.ok(real, "real account section renders");
    assert.ok(paper, "paper account section renders");
    assert.match(String(real.props.className), /as-primary-card/);
    assert.match(String(paper.props.className), /as-paper-card/);
});

test("Account Status renders real financial grid, icons and connection/auth/permission", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    assert.ok(findByTestId(nodes, "account-financial-status"), "financial status frame renders");
    assert.ok(findByTestId(nodes, "financial-metric-grid"), "3x3 financial grid renders");
    const metricKeys = [
        "equity", "availableBalance", "walletBalance", "unrealizedPnl",
        "realizedPnlToday", "totalPnlToday", "marginUsed", "marginAvailable", "marginRatio",
    ];
    metricKeys.forEach((key) => {
        assert.ok(findByTestId(nodes, `financial-${key}`), `financial ${key} slot renders`);
        assert.ok(findByTestId(nodes, `financial-icon-${key}`), `financial ${key} icon renders`);
    });
    // Unavailable real account never fabricates a zero for authoritative metrics
    assert.equal(findByTestId(nodes, "financial-equity-state").props.children, "UNAVAILABLE");
    assert.equal(readTestIdValue(nodes, "financial-equity-value"), "—");
    // connection/auth metadata preserved inside DETAILS (kept in DOM)
    assert.equal(readTestIdValue(nodes, "real-connection"), "NOT_CONNECTED");
    assert.equal(readTestIdValue(nodes, "real-auth"), "NOT_VERIFIED");
    assert.equal(readTestIdValue(nodes, "real-permission"), "NOT_VERIFIED");
    assert.ok(findByTestId(nodes, "real-sync-status"));
});

test("Account Status renders Account Runtime and Live Context cards", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    assert.ok(findByTestId(nodes, "account-runtime-section"));
    assert.ok(findByTestId(nodes, "runtime-mode"));
    assert.ok(findByTestId(nodes, "runtime-bot-state"));
    assert.ok(findByTestId(nodes, "runtime-real-orders"));
    assert.ok(findByTestId(nodes, "execution-authority-grid"));
    assert.ok(findByTestId(nodes, "live-context-section"));
    assert.equal(readTestIdValue(nodes, "live-context-mode"), "PAPER");
    assert.equal(readTestIdValue(nodes, "live-context-execution"), "NOT ALLOWED");
});

test("PAPER MODE — LIVE ACCOUNT INACTIVE renders and freshness is not invented", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    const context = findByTestId(nodes, "real-account-paper-context");
    assert.ok(context, "paper context renders in paper mode");
    assert.match(String(context.props.children), /PAPER MODE（ペーパーモード）— LIVE ACCOUNT INACTIVE（実口座取引停止中）/);
    assert.equal(
        readTestIdValue(nodes, "live-context-message"),
        "PAPER MODE（ペーパーモード）— LIVE ACCOUNT INACTIVE（実口座取引停止中）",
    );
    assert.equal(readTestIdValue(nodes, "live-context-freshness"), "NOT_FETCHED");
});

test("READ_ONLY account access is preserved and not converted to LIVE READY", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: READ_ONLY_BOT_STATUS }));
    assert.equal(readTestIdValue(nodes, "real-permission"), "READ_ONLY");
    assert.equal(readTestIdValue(nodes, "real-connection"), "CONNECTED");
    assert.equal(readTestIdValue(nodes, "live-context-access"), "READ_ONLY");
    assert.equal(readTestIdValue(nodes, "authority-real-order-allowed"), "NO");
    const allText = texts(nodes);
    assert.equal(allText.some((text) => /LIVE READY/i.test(text)), false);
});

test("UNKNOWN / UNAVAILABLE / STALE are not converted to a READY state", async () => {
    const { AccountStatusView } = await loadModule();
    const staleStatus = {
        ...PAPER_BOT_STATUS,
        accountRuntime: {
            ...PAPER_BOT_STATUS.accountRuntime,
            realAccount: {
                ...PAPER_BOT_STATUS.accountRuntime.realAccount,
                stale: true,
                permission: "NOT_VERIFIED",
            },
        },
    };
    const nodes = walk(AccountStatusView({ botStatus: staleStatus }));
    assert.equal(readTestIdValue(nodes, "real-sync-status"), "STALE");
    assert.equal(readTestIdValue(nodes, "live-context-freshness"), "STALE");
    assert.equal(readTestIdValue(nodes, "authority-real-order-allowed"), "NO");
    const allText = texts(nodes);
    assert.equal(allText.some((text) => /LIVE READY|READY TO/i.test(text)), false);
    assert.equal(allText.some((text) => /READY ONLY|FULL LIVE/i.test(text)), false);
});

test("UNKNOWN account state fails closed and is never upgraded to a READY state", async () => {
    const { AccountStatusView } = await loadModule();
    const unknownStatus = {
        ...PAPER_BOT_STATUS,
        permission: "UNKNOWN",
        accountType: "UNKNOWN",
        accountRuntime: {
            ...PAPER_BOT_STATUS.accountRuntime,
            realAccount: {
                ...PAPER_BOT_STATUS.accountRuntime.realAccount,
                permission: "UNKNOWN",
                accountType: "UNKNOWN",
                balance: null,
                lastSync: null,
            },
        },
    };
    const nodes = walk(AccountStatusView({ botStatus: unknownStatus }));
    // UNKNOWN is a fail-closed placeholder ("--"), never upgraded to VERIFIED/READ_ONLY/READY
    assert.equal(readTestIdValue(nodes, "real-permission"), "--");
    assert.equal(readTestIdValue(nodes, "real-account-type"), "--");
    // auth stays NOT_VERIFIED (not upgraded to VERIFIED); real equity stays UNAVAILABLE
    assert.equal(readTestIdValue(nodes, "real-auth"), "NOT_VERIFIED");
    // UNKNOWN (null) real balance never becomes "0.00"
    assert.equal(findByTestId(nodes, "financial-equity-state").props.children, "UNAVAILABLE");
    assert.notEqual(readTestIdValue(nodes, "financial-equity-value"), "0.00");
    assert.notEqual(readTestIdValue(nodes, "financial-walletBalance-value"), "0.00");
    assert.equal(readTestIdValue(nodes, "live-context-freshness"), "NOT_FETCHED");
    const allText = texts(nodes);
    assert.equal(allText.some((text) => /LIVE READY|READY TO|FULL LIVE/i.test(text)), false);
});

test("UNAVAILABLE account reason fails closed instead of fabricating a balance", async () => {
    const { AccountStatusView } = await loadModule();
    const unavailableStatus = {
        ...PAPER_BOT_STATUS,
        accountRuntime: {
            ...PAPER_BOT_STATUS.accountRuntime,
            realAccount: {
                ...PAPER_BOT_STATUS.accountRuntime.realAccount,
                accountReason: "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
                balanceReason: "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
            },
        },
    };
    const nodes = walk(AccountStatusView({ botStatus: unavailableStatus }));
    // no numeric balance is fabricated for an unavailable account
    assert.equal(findByTestId(nodes, "financial-equity-state").props.children, "UNAVAILABLE");
    assert.equal(readTestIdValue(nodes, "financial-equity-value"), "—");
    assert.equal(readTestIdValue(nodes, "financial-availableBalance-value"), "—");
    assert.notEqual(readTestIdValue(nodes, "financial-equity-value"), "0.00");
    assert.notEqual(readTestIdValue(nodes, "financial-availableBalance-value"), "0.00");
    assert.equal(readTestIdValue(nodes, "live-context-freshness"), "NOT_FETCHED");
});

test("Paper metrics and Set Paper Capital control render", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    assert.ok(findByTestId(nodes, "paper-account-metrics"));
    assert.equal(readTestIdValue(nodes, "paper-balance"), "1,000.00");
    assert.equal(readTestIdValue(nodes, "paper-equity"), "1,000.00");
    assert.equal(readTestIdValue(nodes, "paper-source"), "PAPER_SIMULATION");
    assert.ok(findByTestId(nodes, "set-paper-capital"), "Set Paper Capital control present");
});

test("Account Status renders only the DETAILS toggle and no operation buttons", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS, detailsExpanded: false }));
    const buttons = nodes.filter((node) => typeof node === "object" && node.type === "button");
    // The only button is the presentation-only DETAILS toggle (not an operation control).
    assert.equal(buttons.length, 1);
    assert.equal(buttons[0].props.type, "button");
    assert.equal(buttons[0].props["aria-expanded"], false);
    assert.equal(buttons[0].props["aria-controls"], "account-financial-details");
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

test("Account Status renders bilingual English（日本語）labels", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    const allText = texts(nodes).join(" ");
    const required = [
        "Account Status（アカウント状況）",
        "Real / Live Account（実口座）",
        "Production Account（本番口座）",
        "Account Financial Status",
        "EQUITY",
        "純資産",
        "AVAILABLE BALANCE",
        "利用可能額",
        "Authentication（取引所認証）",
        "Account Runtime（アカウント実行状態）",
        "Live Context（LIVE状態）",
        "Paper / Simulation（ペーパー・シミュレーション）",
        "SET PAPER CAPITAL（ペーパー資金設定）",
        "DETAILS",
    ];
    required.forEach((label) => {
        assert.equal(allText.includes(label), true, `missing bilingual label: ${label}`);
    });
});

test("financial metrics expose authoritative Equity / Available / Unrealized when connected", async () => {
    const { AccountStatusView } = await loadModule();
    const connected = {
        ...READ_ONLY_BOT_STATUS,
        accountRuntime: {
            ...READ_ONLY_BOT_STATUS.accountRuntime,
            realAccount: {
                ...READ_ONLY_BOT_STATUS.accountRuntime.realAccount,
                unrealizedPnl: 12.5,
            },
        },
    };
    const nodes = walk(AccountStatusView({ botStatus: connected }));
    assert.equal(readTestIdValue(nodes, "financial-equity-value"), "1,500.00");
    assert.equal(readTestIdValue(nodes, "financial-equity-unit"), "USDT");
    assert.equal(readTestIdValue(nodes, "financial-availableBalance-value"), "1,200.00");
    assert.equal(readTestIdValue(nodes, "financial-availableBalance-unit"), "USDT");
    assert.equal(readTestIdValue(nodes, "financial-unrealizedPnl-value"), "+12.50");
    assert.equal(readTestIdValue(nodes, "financial-unrealizedPnl-unit"), "USDT");
    // walletBalance aliases equity in the backend -> classified ambiguous -> never duplicated as zero
    assert.equal(findByTestId(nodes, "financial-walletBalance-state").props.children, "UNAVAILABLE");
});

test("negative unrealized PnL is never forced to a positive or neutral zero", async () => {
    const { AccountStatusView } = await loadModule();
    const connected = {
        ...READ_ONLY_BOT_STATUS,
        accountRuntime: {
            ...READ_ONLY_BOT_STATUS.accountRuntime,
            realAccount: {
                ...READ_ONLY_BOT_STATUS.accountRuntime.realAccount,
                unrealizedPnl: -8.25,
            },
        },
    };
    const nodes = walk(AccountStatusView({ botStatus: connected }));
    assert.equal(readTestIdValue(nodes, "financial-unrealizedPnl-value"), "-8.25");
    const card = findByTestId(nodes, "financial-unrealizedPnl");
    assert.match(String(card.props.className), /as-fin-card--negative/);
});

test("authoritative zero unrealized PnL is a valid value, never UNAVAILABLE", async () => {
    const { AccountStatusView } = await loadModule();
    const zero = {
        ...READ_ONLY_BOT_STATUS,
        accountRuntime: {
            ...READ_ONLY_BOT_STATUS.accountRuntime,
            realAccount: {
                ...READ_ONLY_BOT_STATUS.accountRuntime.realAccount,
                unrealizedPnl: 0,
            },
        },
    };
    const nodes = walk(AccountStatusView({ botStatus: zero }));
    // An exchange-returned zero must surface as 0.00 USDT, not as UNAVAILABLE and not as a default.
    assert.equal(readTestIdValue(nodes, "financial-unrealizedPnl-value"), "0.00");
    assert.equal(readTestIdValue(nodes, "financial-unrealizedPnl-unit"), "USDT");
    // Missing / unknown still fail closed to UNAVAILABLE on the same card.
    const missing = {
        ...READ_ONLY_BOT_STATUS,
        accountRuntime: {
            ...READ_ONLY_BOT_STATUS.accountRuntime,
            realAccount: {
                ...READ_ONLY_BOT_STATUS.accountRuntime.realAccount,
                unrealizedPnl: undefined,
            },
        },
    };
    const missingNodes = walk(AccountStatusView({ botStatus: missing }));
    assert.equal(findByTestId(missingNodes, "financial-unrealizedPnl-state").props.children, "UNAVAILABLE");
});

test("POSITION remains always visible in the primary account card", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: READ_ONLY_BOT_STATUS }));
    assert.ok(findByTestId(nodes, "real-position"), "POSITION always visible");
    assert.ok(findByTestId(nodes, "real-account-canonical"), "canonical strip renders");
});

test("DETAILS is collapsed by default and toggles on click", async () => {
    const { AccountStatusView } = await loadModule();
    const collapsed = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS, detailsExpanded: false }));
    const toggle = findByTestId(collapsed, "account-details-toggle");
    assert.equal(toggle.props["aria-expanded"], false);
    const details = findByTestId(collapsed, "account-financial-details");
    assert.match(String(details.props.className), /as-financial-details/);
    assert.doesNotMatch(String(details.props.className), /as-financial-details--open/);
    // clicking invokes the toggle handler
    let called = false;
    const interacted = walk(AccountStatusView({
        botStatus: PAPER_BOT_STATUS,
        detailsExpanded: false,
        onDetailsToggle: () => { called = true; },
    }));
    findByTestId(interacted, "account-details-toggle").props.onClick();
    assert.equal(called, true);
    // expanded renders the open state
    const expanded = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS, detailsExpanded: true }));
    assert.equal(findByTestId(expanded, "account-details-toggle").props["aria-expanded"], true);
    assert.match(
        String(findByTestId(expanded, "account-financial-details").props.className),
        /as-financial-details--open/,
    );
});

test("DETAILS preserves all connection / authentication metadata", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: READ_ONLY_BOT_STATUS, detailsExpanded: true }));
    [
        "real-exchange", "real-connection", "real-auth", "real-api-key",
        "real-permission", "real-account-type", "real-sync-status", "real-last-sync",
    ].forEach((id) => {
        assert.ok(findByTestId(nodes, id), `DETAILS preserves ${id}`);
    });
    assert.equal(readTestIdValue(nodes, "real-connection"), "CONNECTED");
    assert.equal(readTestIdValue(nodes, "real-exchange"), "kucoin");
});

test("financial silver frame and READ ONLY authority are preserved", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: READ_ONLY_BOT_STATUS }));
    const frame = findByTestId(nodes, "account-financial-status");
    assert.match(String(frame.props.className), /as-financial-frame/);
    assert.ok(findByTestId(nodes, "real-read-only-authority"), "READ ONLY authority badge present");
    assert.ok(findByTestId(nodes, "real-account-badge"), "real account badge present");
});

test("Account Status preserves canonical status values alongside bilingual labels", async () => {
    const { AccountStatusView } = await loadModule();
    const nodes = walk(AccountStatusView({ botStatus: PAPER_BOT_STATUS }));
    const allText = texts(nodes).join(" ");
    const canonical = [
        "READ ONLY",
        "PAPER_SIMULATION",
        "PAPER",
        "SIMULATION",
        "STOPPED",
        "NOT_CONNECTED",
        "NOT_VERIFIED",
        "FLAT",
        "NO",
    ];
    canonical.forEach((value) => {
        assert.equal(allText.includes(value), true, `missing canonical value: ${value}`);
    });
    assert.equal(allText.includes("LIVE READY"), false);
});
