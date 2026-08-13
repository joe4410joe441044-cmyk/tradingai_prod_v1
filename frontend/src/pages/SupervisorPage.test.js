import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorPage.jsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../styles/supervisor.css", import.meta.url), "utf8");

test("Supervisor page exposes its title and unobtrusive Shadow mode", function () {
    assert.match(source, /<h1>SUPERVISOR<\/h1>/);
    assert.match(source, /MODE: SHADOW/);
    assert.match(source, /supervisor-page__mode/);
});

test("Master is primary and precedes the collapsed MM specialist", function () {
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
    assert.match(overview, /<dt>Supervisor Core<\/dt>/);
    assert.match(overview, /<dt>AI Interpretation<\/dt>/);
    assert.match(overview, /<dt>Operational Effect<\/dt>/);
    assert.match(source, /SHADOW API/);
    assert.match(source, /MODE: SHADOW/);
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
