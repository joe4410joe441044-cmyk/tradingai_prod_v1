import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const dashboardSource = await readFile(
    new URL("./Dashboard.jsx", import.meta.url),
    "utf8",
);

test("Dashboard no longer renders the detailed Account Status block", () => {
    assert.doesNotMatch(dashboardSource, /import AccountRuntimeOverview/);
    assert.doesNotMatch(dashboardSource, /variant="summary"/);
    assert.doesNotMatch(dashboardSource, /accountRuntimeProps/);
    assert.doesNotMatch(dashboardSource, /<AccountRuntimeOverview/);
});

test("Dashboard preserves the runtime strip, operation, and runtime activity", () => {
    assert.match(dashboardSource, /<Header runtimeHealth=\{runtimeHealth\}/);
    assert.match(dashboardSource, /<RuntimeDiagnosticsDisclosure/);
    assert.match(dashboardSource, /<BotControl/);
    assert.match(dashboardSource, /<TradingDecisionCard/);
    assert.match(dashboardSource, /last-execution-activity/);
    assert.match(dashboardSource, /firstAvailable/);
});
