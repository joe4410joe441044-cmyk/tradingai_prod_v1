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

test("renders final decision as most visible item", async () => {
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

    assert.match(text, /FINAL DECISION（最終判断）/);
    assert.match(text, /HOLD/);
});

test("renders entry readiness and current state", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({
        decision: {
            mode: "PAPER",
            finalDecision: "HOLD",
            currentState: "WAITING FOR SIGNAL",
            entryReadiness: "READY",
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

    assert.match(text, /ENTRY READINESS（エントリー準備）/);
    assert.match(text, /READY/);
    assert.match(text, /CURRENT STATE（現在状態）/);
    assert.match(text, /WAITING FOR SIGNAL/);
});

test("renders blocking information when present", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({
        decision: {
            mode: "PAPER",
            finalDecision: "HOLD",
            currentState: "WAITING FOR SIGNAL",
            entryReadiness: "READY",
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

    assert.match(text, /BLOCKING STAGE（停止工程）/);
    assert.match(text, /PYTHON STRATEGY/);
    assert.match(text, /BLOCKING REASON（停止理由）/);
    assert.match(text, /ENTRY_THRESHOLD_NOT_MET/);
});

test("does not render blocking information when not present", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({
        decision: {
            mode: "PAPER",
            finalDecision: "BUY",
            currentState: "READY",
            entryReadiness: "READY",
            stages: {
                market: { status: "PASS" },
                pythonStrategy: { status: "PASS", confidence: 0.85 },
                moneyManagement: { status: "PASS" },
                governance: { status: "PASS" },
                execution: { status: "READY FOR ORDER", positionState: "FLAT", orderState: "NONE" },
            },
        },
    }));

    assert.doesNotMatch(text, /BLOCKING STAGE/);
    assert.doesNotMatch(text, /BLOCKING REASON/);
});

test("renders decision pipeline with all stages", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: { blockingStage: "PYTHON STRATEGY", stages: {} } }));
    
    for (const stage of ["MARKET（市場）", "PYTHON STRATEGY（Python戦略）", "MONEY MANAGEMENT（資金管理）", "GOVERNANCE（安全判定）", "EXECUTION（注文実行）", "POSITION（ポジション）"]) {
        assert.match(text, new RegExp(stage));
    }
});

test("renders additional unknown stages from backend", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ 
        decision: { 
            blockingStage: "PYTHON STRATEGY", 
            stages: { 
                customStage: { status: "PASS" }, 
                anotherStage: { status: "BLOCKED" } 
            } 
        } 
    }));
    
    assert.match(text, /CUSTOMSTAGE/);
    assert.match(text, /ANOTHERSTAGE/);
});

test("renders runtime metadata in compact grid", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: {
        mode: "PAPER", exchange: "kucoin", realOrderAllowed: false,
        bot: "RUNNING", loopState: "RUNNING", autoTradeEnabled: true,
        tradingAiMode: "OFF", tradingAiStatus: "NOT_INSTALLED",
        stale: false, timestamp: Date.now() / 1000, cycleId: "12345",
        stateSince: Date.now() / 1000 - 3600,
        stages: { execution: { orderState: "NONE" } }
    } }));

    assert.match(text, /RUNTIME META（ランタイム情報）/);
    assert.match(text, /MODE（モード） PAPER/);
    assert.match(text, /EXCHANGE（取引所） kucoin/);
    assert.match(text, /REAL ORDER ALLOWED（実注文許可） NO/);
    assert.match(text, /BOT（ボット） RUNNING/);
    assert.match(text, /LOOP（ループ） RUNNING/);
    assert.match(text, /AUTO TRADE（自動売買） ENABLED/);
    assert.match(text, /TRADING AI（売買AI） OFF/);
    assert.match(text, /AI IMPLEMENTATION（AI実装） NOT_INSTALLED/);
    assert.match(text, /MARKET STALE（市場データ遅延） NO/);
    assert.match(text, /CYCLE ID（サイクルID） 12345/);
    assert.match(text, /PENDING ORDER（保留注文） NO/);
});

test("renders stale market data warning", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: { stale: true } }));
    assert.match(text, /STALE DECISION DATA（判断データが古くなっています）/);
});

test("does not render stale warning when not stale", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ decision: { stale: false } }));
    assert.doesNotMatch(text, /STALE DECISION DATA/);
});

test("renders pending order status", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ 
        decision: { 
            stages: { execution: { orderState: "SUBMITTED" } } 
        } 
    }));
    assert.match(text, /PENDING ORDER（保留注文） YES/);
});

test("renders no pending order when none", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ 
        decision: { 
            stages: { execution: { orderState: "NONE" } } 
        } 
    }));
    assert.match(text, /PENDING ORDER（保留注文） NO/);
});

test("renders decision details section collapsed by default", async () => {
    const Component = await loadComponent();
    const tree = Component({ decision: {} });
    const disclosure = tree.props.children.find((child) => child?.type === "details");
    assert.equal(disclosure.props.open, undefined);
});

test("renders all decision stages with correct statuses", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({ 
        decision: { 
            blockingStage: "MONEY MANAGEMENT", 
            stages: { 
                market: { status: "PASS" }, 
                pythonStrategy: { status: "PASS", confidence: 0.75 }, 
                moneyManagement: { status: "BLOCKED", reason: "RISK_LIMIT" }, 
                governance: { status: "NOT REACHED" }, 
                execution: { status: "NOT REACHED" }, 
                position: { status: "UNKNOWN" } 
            } 
        } 
    }));
    
    assert.match(text, /MARKET（市場）.*PASS/);
    assert.match(text, /PYTHON STRATEGY（Python戦略）.*PASS.*75.0%/);
    assert.match(text, /MONEY MANAGEMENT（資金管理）.*BLOCKED.*RISK_LIMIT/);
});