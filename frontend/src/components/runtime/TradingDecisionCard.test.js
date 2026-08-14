import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};

const loadComponent = async () => {
    const source = new URL("./TradingDecisionCard.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".trading-decision-test-"));
    const output = join(temporary, "component.mjs");
    await writeFile(output, transformed.code);
    try {
        return (await import(pathToFileURL(output).href)).default;
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

test("renders the complete entry-readiness contract", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({
        decision: {
            mode: "PAPER",
            finalDecision: "HOLD",
            currentState: "WAITING FOR SIGNAL",
            blockingStage: "PYTHON STRATEGY",
            blockingReason: "ENTRY_THRESHOLD_NOT_MET",
            stages: {
                market: { status: "PASS" },
                pythonStrategy: { status: "HOLD", confidence: 0.42 },
                moneyManagement: { status: "NOT REACHED" },
                governance: { status: "NOT REACHED" },
                execution: { status: "NO ORDER", positionState: "FLAT", orderState: "NONE" },
            },
        },
    }));

    for (const expected of [
        "TRADING DECISION（売買判断）", "PAPER", "HOLD", "WAITING FOR SIGNAL",
        "PYTHON STRATEGY", "ENTRY_THRESHOLD_NOT_MET",
        "MONEY MANAGEMENT", "NOT REACHED", "NO ORDER", "FLAT",
        "TRADING AI", "OFF", "NOT_INSTALLED",
        "Decision Details（判断詳細）", "FINAL DECISION（最終判断）",
        "ENTRY READINESS（エントリー準備）", "STOPPED HERE（現在停止）",
        "ENTRY CONDITIONS（エントリー条件）", "NOT EXPOSED", "STOPPED HERE（現在停止）",
    ]) assert.match(text, new RegExp(expected));
});

test("provides bilingual labels for every decision stage", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: {} }));

    for (const expected of [
        "MARKET（市場）", "PYTHON STRATEGY（Python戦略）",
        "MONEY MANAGEMENT（資金管理）", "GOVERNANCE（安全判定）",
        "EXECUTION（注文実行）", "POSITION（ポジション）",
    ]) assert.match(text, new RegExp(expected));
});

test("renders the six-stage route map in processing order", async () => {
    const Component = await loadComponent();
    const tree = Component({ decision: { blockingStage: "PYTHON STRATEGY", stages: {} } });
    const pipeline = tree.props.children.find((child) => child?.props?.className === "trading-decision-pipeline");
    const text = textOf(pipeline);
    const labels = ["MARKET（市場）", "PYTHON STRATEGY（Python戦略）", "MONEY MANAGEMENT（資金管理）", "GOVERNANCE（安全判定）", "EXECUTION（注文実行）", "POSITION（ポジション）"];
    labels.reduce((position, stage) => {
        const next = text.indexOf(stage);
        assert.ok(next > position, `${stage} must follow the previous stage`);
        return next;
    }, -1);
    assert.equal((text.match(/━━▶/g) || []).length, 5);
    assert.equal(pipeline.props.children[1].props.children[1].props["aria-current"], "step");
});

test("keeps decision details closed by default", async () => {
    const Component = await loadComponent();
    const tree = Component({ decision: {} });
    const disclosure = tree.props.children.find((child) => child?.type === "details");
    assert.equal(disclosure.props.open, undefined);
});

test("shows the current block context from the matching stage only", async () => {
    const Component = await loadComponent();
    const scenarios = [
        {
            blockingStage: "PYTHON STRATEGY",
            stages: { pythonStrategy: { confidence: 0.126, executionAllowed: false, decision: "HOLD", suppressionReason: "LIQUIDITY_DETERIORATION" } },
            expected: ["PYTHON STRATEGY（Python戦略）", "12.6 %", "EXECUTION ALLOWED（実行許可） NO", "LIQUIDITY_DETERIORATION"],
        },
        {
            blockingStage: "MONEY MANAGEMENT",
            stages: { moneyManagement: { riskAmount: "4.50", exposure: "25.00", reason: "RISK_LIMIT" } },
            expected: ["MONEY MANAGEMENT（資金管理）", "RISK（リスク） 4.50", "EXPOSURE（エクスポージャー） 25.00", "REASON（理由） RISK_LIMIT"],
        },
        {
            blockingStage: "GOVERNANCE",
            stages: { governance: { executionAuthority: "DISABLED", reason: "RULE_BLOCK", decision: "BLOCK" } },
            expected: ["GOVERNANCE（安全判定）", "RULE（ルール） DISABLED", "BLOCK REASON（停止理由） RULE_BLOCK", "DECISION（判断） BLOCK"],
        },
        {
            blockingStage: "EXECUTION",
            stages: { execution: { orderState: "SUBMITTED", state: "WAITING FOR FILL" } },
            expected: ["EXECUTION（注文実行）", "ORDER STATE（注文状態） SUBMITTED", "PENDING（保留） SUBMITTED", "WAITING FILL（約定待ち） WAITING FOR FILL"],
        },
        {
            blockingStage: "POSITION",
            stages: { execution: { positionState: "LONG" } },
            expected: ["POSITION（ポジション）", "POSITION（方向） LONG", "ENTRY PRICE（建値） --", "CURRENT PNL（現在損益） --"],
        },
    ];

    for (const scenario of scenarios) {
        const text = textOf(Component({ decision: scenario }));
        assert.match(text, /CURRENT BLOCK CONTEXT（現在停止工程）/);
        for (const expected of scenario.expected) assert.match(text, new RegExp(expected));
    }
});

test("shows operational summary values only from the runtime contract", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: {
        mode: "PAPER", exchange: "kucoin", realOrderAllowed: false,
        bot: "RUNNING", loopState: "RUNNING", autoTradeEnabled: true,
        tradingAiMode: "OFF", tradingAiStatus: "NOT_INSTALLED",
    } }));
    assert.match(text, /MODE（モード） PAPER/);
    assert.match(text, /EXCHANGE（取引所） kucoin/);
    assert.match(text, /REAL ORDER ALLOWED（実注文許可） NO/);
    assert.match(text, /BOT（ボット） RUNNING/);
    assert.match(text, /LOOP（ループ） RUNNING/);
    assert.match(text, /AUTO TRADE（自動売買） ENABLED/);
    assert.match(text, /TRADING AI（売買AI） OFF/);
    assert.match(text, /AI IMPLEMENTATION（AI実装） NOT_INSTALLED/);
});

test("marks unpublished operational and execution fields explicitly", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: { blockingStage: "PYTHON STRATEGY", stages: { pythonStrategy: {} } } }));
    assert.match(text, /BOT（ボット） NOT AVAILABLE/);
    assert.match(text, /LOOP（ループ） NOT AVAILABLE/);
    assert.match(text, /AUTO TRADE（自動売買） NOT AVAILABLE/);
    assert.match(text, /EXECUTION ALLOWED（実行許可） NOT PUBLISHED（未公開）/);
});

test("renders unavailable values without inventing a decision", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: undefined }));
    assert.match(text, /NOT AVAILABLE/);
    assert.doesNotMatch(text, /AI_HOLD/);
});

test("renders backend-computed entry readiness without threshold logic", async () => {
    const Component = await loadComponent();
    const condition = (code, status, currentValue, threshold, operator, delta = null, sourceStatus = "MEASURED") => ({ code, status, currentValue, threshold, operator, delta, sourceStatus });
    const text = textOf(Component({ decision: {
        blockingStage: "PYTHON STRATEGY",
        entryReadinessAvailable: true,
        entryReadiness: {
            available: true,
            candidateDirection: "SELL",
            strategyDecision: "HOLD",
            blockingCondition: "LIQUIDITY_QUALITY",
            conditions: [
                condition("SPREAD", "PASS", 0.00001, 0.0005, "<="),
                condition("SPREAD_VOLATILITY", "PASS", 0, 0.65, "<="),
                condition("LIQUIDITY_QUALITY", "FAIL", 0.0936, 0.35, ">=", 0.2564),
                condition("MOMENTUM", "FAIL", 0, 0.5, ">=", 0.5, "DEFAULTED"),
                condition("PRESSURE_ALIGNMENT", "PASS", 0.4715, 0.15, ">=", 0, "DERIVED"),
                condition("EDGE", "FAIL", 0.3322, 0.55, ">="),
                condition("CONFIDENCE", "FAIL", 0.1661, 0.6, ">="),
                { code: "ABSORPTION", status: "PASS", currentValue: false, expected: false, delta: null, sourceStatus: "MEASURED" },
                { code: "STAGNANT_FLOW", status: "PASS", currentValue: false, expected: false, delta: null, sourceStatus: "MEASURED" },
                { code: "FAKE_PRESSURE", status: "PASS", currentValue: false, expected: false, delta: null, sourceStatus: "MEASURED" },
                { code: "LIQUIDITY_SAFETY", status: "PASS", currentValue: true, expected: true, delta: null, sourceStatus: "DERIVED" },
            ],
        },
        stages: {},
    } }));
    for (const expected of [
        "ENTRY READINESS（エントリー準備）", "Candidate SELL", "Python Decision HOLD",
        "Primary Blocker  LIQUIDITY_QUALITY", "Liquidity FAIL", "0.0936 / >=0.3500",
        "LIQUIDITY_QUALITY GAP 0.2564", "Liquidity Safety PASS", "source  DEFAULTED",
        "EDGE :  FAIL", "CONFIDENCE :  FAIL",
    ]) assert.match(text, new RegExp(expected));
    assert.doesNotMatch(text, /SELL GAP/);
});

test("uses the backend PASS and FAIL statuses for readiness tones", async () => {
    const Component = await loadComponent();
    const rendered = Component({ decision: {
        entryReadiness: {
            available: true,
            conditions: [
                { code: "SPREAD", status: "PASS", currentValue: 0.0001, threshold: 0.0005, operator: "<=" },
                { code: "LIQUIDITY_QUALITY", status: "FAIL", currentValue: 0.1, threshold: 0.35, operator: ">=" },
            ],
        },
        stages: {},
    } });
    const source = await readFile(new URL("./TradingDecisionCard.jsx", import.meta.url), "utf8");
    assert.match(textOf(rendered), /Spread PASS/);
    assert.match(textOf(rendered), /Liquidity FAIL/);
    assert.match(source, /\["FAIL", "HOLD", "BLOCK", "ENTRY BLOCKED"\]/);
});
