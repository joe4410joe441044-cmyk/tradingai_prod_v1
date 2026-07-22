import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";
import { buildReplayMarkerOverlayModel } from "../../features/market-intelligence/replay/replayMarkerOverlayModel.js";

const directory = dirname(fileURLToPath(import.meta.url));
const loadModule = async () => {
    const source = new URL("./ReplayMarkerOverlay.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(source, "utf8"), fileURLToPath(source));
    const temporary = await mkdtemp(join(directory, ".marker-overlay-test-"));
    const output = join(temporary, "ReplayMarkerOverlay.mjs");
    try {
        await writeFile(output, transformed.code);
        return await import(`${pathToFileURL(output).href}?test=marker-overlay`);
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
const textOf = (node) => {
    const children = node?.props?.children;
    if (Array.isArray(children)) return children.map((child) => typeof child === "object" ? textOf(child) : String(child ?? "")).join("");
    return typeof children === "object" ? textOf(children) : String(children ?? "");
};

test("empty overlay renders summary, legend, diagnostics, and empty layers", async () => {
    const module = await loadModule();
    const model = buildReplayMarkerOverlayModel(null, {});
    const nodes = descendants([module.PriceMarkerLayer({ model }), module.TimeMarkerLayer({ model }), module.default({ model })]);
    const text = nodes.map(textOf).join(" ");
    for (const expected of ["NO PRICE MARKERS", "NO TIME MARKERS", "Marker Summary", "Marker Legend", "Marker Diagnostics",
        "BUY", "SELL", "ENTRY", "EXIT", "REDUCE ONLY", "FLATTEN", "ORDER FAILED", "GOVERNANCE BLOCK", "UNKNOWN"])
        assert.match(text, new RegExp(expected));
});

test("overlay renders block, failure, reduce-only, and flatten text safely", async () => {
    const module = await loadModule();
    const events = [
        ["block", "GOVERNANCE_BLOCK", { reason: "blocked", blocked: true }],
        ["fail", "ORDER_FAILED", { reason: "failed", failed: true, orderId: "order-1" }],
        ["reduce", "REDUCE_ONLY", { reduceOnly: true }], ["flat", "FLATTEN", { flatten: true }],
    ].map(([markerId, markerType, values], sequence) => ({
        id: markerId, markerId, type: markerType, timestamp: "2026-01-01T00:00:00Z", sequence,
        price: 100, quantity: null, side: null, reason: null, orderId: null,
        reduceOnly: false, flatten: false, blocked: false, failed: false,
        source: "SYSTEM", eventType: "MARKET_SNAPSHOT", dataQuality: "VALID", ...values,
    }));
    const byType = Object.fromEntries(["BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN", "ORDER_FAILED",
        "GOVERNANCE_BLOCK", "UNKNOWN"].map((type) => [type, events.filter((marker) => marker.type === type).length]));
    const model = buildReplayMarkerOverlayModel({ projection: { markerContext: { markers: events, count: events.length,
        latestMarker: events.at(-1), summary: { total: events.length, byType, buy: 0, sell: 0, entry: 0, exit: 0,
            reduceOnly: 1, flatten: 1, failed: 1, blocked: 1, unknown: 0 } } } }, {
        orderBook: { asks: [], bids: [] }, recentTrades: { rows: [] },
    });
    const nodes = descendants([module.PriceMarkerLayer({ model }), module.TimeMarkerLayer({ model }), module.default({ model })]);
    const text = nodes.map(textOf).join(" ");
    for (const expected of ["GOVERNANCE BLOCK", "ORDER FAILED", "REDUCE ONLY", "FLATTEN", "BlockedTRUE", "FailedTRUE",
        "Marker Details", "Formal Marker Summary", "Data QualityVALID", "Event TypeMARKET_SNAPSHOT",
        "IDblock", "Marker IDblock", "TypeGOVERNANCE_BLOCK", "Timestamp2026-01-01T00:00:00.000Z",
        "Sequence0", "Price100", "Quantity—", "Side—", "Reasonblocked", "Order ID—",
        "Reduce OnlyFALSE", "FlattenFALSE", "SourceSYSTEM", "Event ID—", "Trade ID—",
        "Decision ID—", "Position ID—", "Station ID—"])
        assert.match(text, new RegExp(expected));
    assert.equal(nodes.some(({ type }) => ["button", "input", "select"].includes(type)), false);
    assert.equal(nodes.some(({ props }) => typeof props?.onClick === "function" || props?.tabIndex !== undefined), false);
});
