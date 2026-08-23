import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./TradingDecisionCard.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".trading-decision-test-"));
    const output = join(temporary, "TradingDecisionCard.mjs");
    const modelUrl = new URL("./tradingCycleModel.js", import.meta.url).href;
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
            .replace('from "./tradingCycleModel";', `from "${modelUrl}";`));
        return await import(`${pathToFileURL(output).href}?test=trading-decision`);
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

test("TradingDecisionCard renders trading cycle title", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ decision: {} }));
    const titles = nodes.filter((node) => 
        node.type === "h2" || (node.props && node.props.children && 
        (String(node.props.children).includes("TRADING CYCLE") || String(node.props.children).includes("トレーディングサイクル")))
    );
    assert.ok(titles.length > 0);
});

test("TradingDecisionCard renders all 15 stages", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ decision: {} }));
    const stageLabels = [
        "Parameter Context",
        "Market Selection",
        "Market Data",
        "Feature Builder",
        "Micro Edge Strategy",
        "AI Decision / Review",
        "Money Management",
        "Governance",
        "Execution",
        "Position",
        "Exit Monitoring",
        "Settlement / Exit Execution",
        "Position Closed",
        "Trade / Parameter Performance Record",
        "Ready for Next Trade",
    ];
    
    const foundLabels = [];
    nodes.forEach((node) => {
        if (node.type === "div" && node.props?.className?.includes("trading-cycle-stage-label")) {
            const text = String(node.props.children).trim();
            if (stageLabels.includes(text)) {
                foundLabels.push(text);
            }
        }
    });
    
    assert.equal(foundLabels.length, 15);
    stageLabels.forEach(label => {
        assert.ok(foundLabels.includes(label));
    });
});

test("TradingDecisionCard renders current activity panel", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ decision: {} }));
    
    const hasActivityPanel = nodes.some((node) => 
        node.type === "section" && node.props?.className?.includes("current-activity-panel")
    );
    
    assert.ok(hasActivityPanel);
});

test("TradingDecisionCard renders lower status panel", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ decision: {} }));
    
    const hasLowerPanel = nodes.some((node) => 
        node.type === "section" && node.props?.className?.includes("lower-status-panel")
    );
    
    assert.ok(hasLowerPanel);
});

test("TradingDecisionCard displays selected symbol when available", async () => {
    const symbol = "BTC/USDT";
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ 
        decision: {
            stages: {
                market: {
                    symbol,
                },
            },
        } 
    }));
    
    const hasSymbol = nodes.some((node) => {
        const text = String(node.props?.children || "").trim();
        return text === symbol;
    });
    
    assert.ok(hasSymbol);
});

test("TradingDecisionCard handles position open state", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ 
        decision: {
            currentState: "POSITION OPEN",
            stages: {
                execution: {
                    positionState: "POSITION OPEN",
                },
            },
        } 
    }));
    
    const hasPositionStage = nodes.some((node) => {
        const text = String(node.props?.children || "").trim();
        return text === "Position";
    });
    
    assert.ok(hasPositionStage);
});

test("TradingDecisionCard displays correct labels for Japanese users", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ decision: {} }));
    
    const hasJapaneseTitle = nodes.some((node) => {
        const text = String(node.props?.children || "").trim();
        return text.includes("トレーディングサイクル");
    });
    
    assert.ok(hasJapaneseTitle);
});

test("TradingDecisionCard handles stopped state correctly", async () => {
    const { default: TradingDecisionCard } = await loadModule();
    const nodes = descendants(TradingDecisionCard({ 
        decision: {
            currentActivity: "BOT_STOPPED"
        } 
    }));
    
    // Check that all stages are NOT_REACHED
    const activeStages = nodes.filter((node) => 
        node.type === "div" && node.props?.["data-status"] === "CURRENT"
    );
    assert.equal(activeStages.length, 0);
});