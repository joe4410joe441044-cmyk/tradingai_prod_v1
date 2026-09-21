import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const statusStripSource = await readFile(
    new URL("./StatusStrip.jsx", import.meta.url),
    "utf8",
);

test("TOP runtime status bar keeps the five runtime-critical items", () => {
    assert.match(statusStripSource, /BOT \/ ボット/);
    assert.match(statusStripSource, /BROWSER WS \/ 画面接続/);
    assert.match(statusStripSource, /STRATEGY LOOP/);
    assert.match(statusStripSource, /LATENCY \/ 遅延/);
    assert.match(statusStripSource, /MODE/);
});

test("TOP runtime status bar removes the low-value presentation items", () => {
    assert.doesNotMatch(statusStripSource, /EXEC \/ 実行/);
    assert.doesNotMatch(statusStripSource, /PIPELINE/);
    assert.doesNotMatch(statusStripSource, /STAGES/);
    assert.doesNotMatch(statusStripSource, /SESSION/);
    assert.doesNotMatch(statusStripSource, /VERSION/);
});


// Render the actual components against the backend's independent lifecycle,
// loop, and execution-authority facts from a disarmed LIVE MANUAL session.
const { transformWithOxc } = await import("vite");
const { createElement } = await import("react");
const { renderToStaticMarkup } = await import("react-dom/server");

async function loadComponent(relativePath) {
    const url = new URL(relativePath, import.meta.url);
    const source = await readFile(url, "utf8");
    const transformed = await transformWithOxc(source, url.pathname);
    const code = transformed.code
        .replace(/from "(react(?:\/jsx-runtime)?)"/g,
            (_, name) => `from "${import.meta.resolve(name)}"`)
        .replace('from "../runtime/runtimeDisplay"',
            `from "${new URL("../runtime/runtimeDisplay.js", import.meta.url).href}"`);
    return (await import(`data:text/javascript,${encodeURIComponent(code)}`)).default;
}

const StatusStrip = await loadComponent("./StatusStrip.jsx");
const DiagnosticsPanel = await loadComponent("./runtime/DiagnosticsPanel.jsx");

const liveManualHealth = {
    running: true,
    mode: "LIVE",
    browserWebSocket: { status: "LIVE", connected: true },
    runtimeEngine: { status: "STOPPED", healthy: true },
    runtimeLoop: { status: "STOPPED", running: false },
    executionAuthority: { enabled: false },
    executionEngine: { available: true, enabled: false, allowed: false },
    latencyMs: 1,
};

test("LIVE MANUAL monitoring running with loop off does not claim the engine stopped", () => {
    const html = renderToStaticMarkup(createElement(StatusStrip, { runtimeHealth: liveManualHealth }));
    assert.match(html, /BOT \/ ボット.*RUNNING/s);
    assert.match(html, /STRATEGY LOOP.*STOPPED/s);
    assert.match(html, /LIVE/);
    assert.doesNotMatch(html, /RUNTIME ENGINE/);
    const diagnostics = renderToStaticMarkup(createElement(DiagnosticsPanel, { runtimeHealth: liveManualHealth }));
    assert.match(diagnostics, /No active warnings or errors/);
});

test("strategy loop errors remain visible under their subsystem name", () => {
    const runtimeHealth = {
        ...liveManualHealth,
        runtimeEngine: { status: "ERROR", healthy: false },
    };
    const html = renderToStaticMarkup(createElement(DiagnosticsPanel, { runtimeHealth }));
    assert.match(html, /STRATEGY LOOP/);
    assert.match(html, /ERROR/);
    assert.doesNotMatch(html, /RUNTIME ENGINE/);
});
