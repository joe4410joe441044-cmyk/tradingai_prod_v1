import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorPage.jsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../styles/supervisor.css", import.meta.url), "utf8");

test("Supervisor page exposes a compact title and unobtrusive Shadow mode", function () {
    assert.match(source, /<h1>Supervisor<\/h1>/);
    assert.match(source, /SHADOW · READ ONLY/);
    assert.match(source, /supervisor-page__mode/);
});

test("legacy large title is removed and the page identity stays compact", function () {
    assert.doesNotMatch(source, /TRADINGAI OVERSIGHT/);
    assert.doesNotMatch(source, /<h1>SUPERVISOR<\/h1>/);
});

test("Master is primary and precedes the collapsed MM specialist and Details", function () {
    assert.ok(source.indexOf("MASTER SUPERVISOR") < source.indexOf("<MMSupervisorSection"));
    assert.ok(source.indexOf("<MMSupervisorSection") < source.indexOf("<SupervisorDetailsDisclosure"));
});

test("page remains isolated from App, Navigation, Advisor, direct API calls, and future supervisors", function () {
    assert.doesNotMatch(source, /AppNavigation|AIAdvisor|ai-advisor|fetch\(|axios|\/api\//);
    assert.doesNotMatch(source, /Strategy Supervisor|Execution Supervisor|System Health Supervisor/);
});

test("overview separates Core and AI layers while the page stays SHADOW-only", async function () {
    const overview = await readFile(
        new URL("../components/supervisor/SupervisorOverview.jsx", import.meta.url),
        "utf8",
    );
    assert.match(overview, /label="Core"/);
    assert.match(overview, /label="AI"/);
    assert.match(overview, /label="Effect"/);
    assert.match(source, /SHADOW API/);
    assert.match(source, /SHADOW · READ ONLY/);
});

test("layout is bounded and collapses to one column at narrow widths", function () {
    assert.match(styles, /max-width:\s*1180px/);
    assert.match(styles, /overflow-x:\s*hidden/);
    assert.match(styles, /@media \(max-width: 600px\)[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/);
});

test("page adds no operational or provider-setup controls", function () {
    assert.doesNotMatch(source, /Start Bot|Start Loop|Auto Trade|Execute Order|Cancel Order|Flatten|Unlock Emergency|Change Risk|Change Quantity|Change Governance|Change MM/);
    assert.doesNotMatch(source, /API Key|Provider selector|OpenAI selector|Ollama enable|Model selector|Model download|Model load|Inference start/);
});

test("conversation unavailable never marks the Supervisor Core unavailable", async function () {
    const shell = await readFile(
        new URL("../components/supervisor/SupervisorConversationShell.jsx", import.meta.url),
        "utf8",
    );
    assert.match(shell, /SHADOW · 実変更なし/);
    assert.match(shell, /role="alert"/);
    assert.doesNotMatch(shell, /Supervisor (UNAVAILABLE|DOWN|FAILURE|ERROR)/);
    assert.doesNotMatch(source, /Supervisor Core[\s\S]{0,400}UNAVAILABLE/);
});

test("Supervisor wires left/right top-edge help launchers that default CLOSED", function () {
    assert.match(source, /ai-help-dock/);
    assert.match(source, /label="どのAIに聞く？"/);
    assert.match(source, /label="Supervisor ガイド"/);
    assert.match(source, /helpDrawer === "which-ai"/);
    assert.match(source, /helpDrawer === "supervisor-guide"/);
    assert.match(source, /useState\(null\)/);
    assert.match(source, /WhichAiGuide/);
    assert.match(source, /SupervisorGuide/);
});

test("Supervisor guide drawer is an overlay, not a large card in flow", function () {
    assert.match(source, /AiHelpDrawer/);
    assert.match(source, /side="left"/);
    assert.match(source, /side="right"/);
    assert.match(source, /onClose=\{closeHelp\}/);
});

test("Supervisor Master/MM contextual '?' reuses the same guide drawer", function () {
    assert.match(source, /requestSupervisorHelp\("master"\)/);
    assert.match(source, /onRequestSupervisorHelp=\{requestSupervisorHelp\}/);
    assert.match(source, /focusSection=\{guideSection\}/);
    assert.ok(source.indexOf("requestSupervisorHelp") < source.indexOf("<SupervisorDetailsDisclosure") || source.includes("requestSupervisorHelp"));
});

test("Supervisor keeps the existing Master and MM conversations", function () {
    assert.match(source, /SupervisorConversationShell/);
    assert.match(source, /supervisorName="Master Supervisor"/);
    assert.match(source, /agentId="MASTER_SUPERVISOR"/);
    assert.match(source, /<MMSupervisorSection/);
    assert.match(source, /<SupervisorDetailsDisclosure/);
    assert.match(source, /<SupervisorOverview/);
    assert.match(source, /SHADOW · READ ONLY/);
});

test("Supervisor help does not add operational or provider-setup controls", function () {
    assert.doesNotMatch(source, /Start Bot|Start Loop|Auto Trade|Execute Order|Cancel Order|Flatten|Unlock Emergency|Change Risk|Change Quantity|Change Governance|Change MM/);
    assert.doesNotMatch(source, /API Key|Provider selector|OpenAI selector/);
});

test("MM Supervisor section opens the same Supervisor guide and is SHADOW", async function () {
    const mm = await readFile(
        new URL("../components/supervisor/MMSupervisorSection.jsx", import.meta.url),
        "utf8",
    );
    assert.match(mm, /onRequestSupervisorHelp/);
    assert.match(mm, /onRequestSupervisorHelp\("mm"\)/);
    assert.match(mm, /supervisor-heading-help/);
    assert.match(mm, /State: <strong>\{state\}<\/strong>/);
    assert.match(mm, /supervisorName="MM Supervisor"/);
});
