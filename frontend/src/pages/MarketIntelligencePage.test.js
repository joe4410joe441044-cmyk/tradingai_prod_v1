import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const loadPage = async () => {
    const source = new URL("./MarketIntelligencePage.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".mi-page-test-"));
    const output = join(temporary, "MarketIntelligencePage.mjs");
    const componentStub = (label, named = "") => moduleUrl(`export default()=>({type:'section',props:{children:'${label}'}});${named}`);
    const aiWorkspaceStub = moduleUrl("export default ({finalDecision})=>({type:'section',props:{children:['AI INTELLIGENCE','Real-time Market Recognition & AI Decision Engine',finalDecision,'Detector Summary','Feature Snapshot','Strategy','AI Review','Governance','EXECUTION / POSITION']}})");
    const autoMarketSelectionStub = componentStub("AUTO MARKET SELECTION COLLAPSIBLE");
    const boundaryStub = moduleUrl("export default ({children})=>children");
    const providerStub = moduleUrl("export const MarketIntelligenceProvider=({children})=>children");
    const workspaceStub = moduleUrl("export default ({primaryLeft,primaryRight,secondary,investigation})=>({type:'section',props:{children:[primaryLeft,primaryRight,secondary,investigation]}})");
    const investigationStub = moduleUrl("export default ({children})=>({type:'section',props:{children:['REPLAY / INVESTIGATION',children]}})");
    let code = transformed.code.replace('from "../components/market-intelligence/AIIntelligenceWorkspace";',
        `from "${aiWorkspaceStub}";`)
        .replace('from "../components/market-intelligence/AutoMarketSelectionPanel";', `from "${autoMarketSelectionStub}";`);
    const replacements = [
        ["DecisionRailway", "DECISION RAILWAY", "export const DecisionRailwaySummary=()=>({type:'section',props:{children:'AI FINAL DECISION'}})"], ["MarketIntelligenceHeader", "MI HEADER"],
        ["MarketIntelligenceStatusLayer", "PAGE STATUS"], ["MarketIntelligenceToolbar", "MI TOOLBAR"],
        ["ReplayController", "REPLAY CONTROLLER"], ["ReplayInspector", "REPLAY INSPECTOR"],
        ["ReplayMarketView", "REPLAY MARKET VIEW"], ["PositionTimeline", "POSITION TIMELINE"],
        ["ReplayTimeline", "REPLAY TIMELINE"],
    ];
    for (const [name, label, named] of replacements) {
        const path = name.startsWith("MarketIntelligence") || name.startsWith("Replay")
            || name === "DecisionRailway" || name === "PositionTimeline"
            ? `../components/market-intelligence/${name}` : name;
        code = code.replace(`from "${path}";`, `from "${componentStub(label, named)}";`);
    }
    code = code.replace('from "../components/market-intelligence/MarketIntelligenceErrorBoundary";', `from "${boundaryStub}";`)
        .replace('from "../components/market-intelligence/MarketIntelligenceWorkspace";', `from "${workspaceStub}";`)
        .replace('from "../components/market-intelligence/ReplayInvestigationPanel";', `from "${investigationStub}";`)
        .replace('from "../state/market-intelligence/MarketIntelligenceProvider";', `from "${providerStub}";`);
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=page`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const textOf = (node) => {
    if (node == null) return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};

test("MarketIntelligencePage prioritizes market selection primary, AI secondary, replay investigation collapsed", async () => {
    const { default: Page } = await loadPage();
    const text = textOf(Page());
    for (const expected of ["MARKET INTELLIGENCE（市場インテリジェンス）", "MI TOOLBAR", "REPLAY MARKET VIEW",
        "AUTO MARKET SELECTION COLLAPSIBLE", "AI INTELLIGENCE", "Real-time Market Recognition & AI Decision Engine", "AI FINAL DECISION",
        "Detector Summary", "Feature Snapshot", "Strategy", "AI Review", "Governance", "EXECUTION / POSITION",
        "REPLAY / INVESTIGATION", "REPLAY CONTROLLER", "DECISION RAILWAY", "REPLAY INSPECTOR", "POSITION TIMELINE", "REPLAY TIMELINE"])
        assert.match(text, new RegExp(expected));
    assert.doesNotMatch(text, /MI HEADER|PAGE STATUS/);
    assert.equal(text.indexOf("REPLAY MARKET VIEW") < text.indexOf("AUTO MARKET SELECTION COLLAPSIBLE"), true);
    assert.equal(text.indexOf("AUTO MARKET SELECTION COLLAPSIBLE") < text.indexOf("AI INTELLIGENCE"), true);
    assert.equal(text.indexOf("AI INTELLIGENCE") < text.indexOf("REPLAY / INVESTIGATION"), true);
    assert.equal(text.indexOf("REPLAY / INVESTIGATION") < text.indexOf("REPLAY CONTROLLER"), true);
    assert.equal(text.indexOf("REPLAY CONTROLLER") < text.indexOf("DECISION RAILWAY"), true);
    assert.equal(text.indexOf("DECISION RAILWAY") < text.indexOf("REPLAY INSPECTOR"), true);
    assert.equal(text.indexOf("REPLAY INSPECTOR") < text.indexOf("POSITION TIMELINE"), true);
    assert.equal(text.indexOf("POSITION TIMELINE") < text.indexOf("REPLAY TIMELINE"), true);
});

test("Dashboard no longer renders the standalone Auto Market Selection card", async () => {
    const dashboard = await readFile(new URL("./Dashboard.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(dashboard, /AutoMarketSelectionCard/);
    assert.doesNotMatch(dashboard, /data-testid=["']auto-market-selection-card/);
});

test("Dashboard connects the formal AUTO candidate and readiness to Operation", async () => {
    const dashboard = await readFile(new URL("./Dashboard.jsx", import.meta.url), "utf8");
    assert.match(dashboard, /displaySymbol: botStatus\?\.autoMarketSelection\?\.topCandidate\?\.symbol/);
    assert.match(dashboard, /autoMarketState: botStatus\?\.autoMarketSelection\?\.productionIntegration\?\.status/);
    assert.doesNotMatch(dashboard, /displaySymbol: botStatus\?\.activeSymbol/);
});
