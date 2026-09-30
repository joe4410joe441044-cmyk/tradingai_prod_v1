import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { compilePositionModules } from "../../../test-support/positionModules.js";

const temporary = await mkdtemp(fileURLToPath(new URL(".position-test-", import.meta.url)));
await compilePositionModules(temporary);
const { default: Current } = await import(pathToFileURL(join(temporary, "CurrentPositionCard.mjs")));
const { default: Last } = await import(pathToFileURL(join(temporary, "LastPositionEventCard.mjs")));
await rm(temporary, { recursive: true, force: true });
const render = (component, position) => renderToStaticMarkup(createElement(component, { position }));
const base = { status: "OPEN", event: "CLOSED", mode: "PAPER", control: "MANUAL", symbol: "GRIFFAINUSDT", side: "LONG",
    quantity: 6174, quantityUnit: "coin", entryPrice: .016195, markPrice: .016195, exitPrice: .016195,
    unrealizedPnl: 0, realizedPnl: 0, holdingMs: 643, exitReason: "MOMENTUM_DECAY", freshness: "FRESH" };

for (const mode of ["PAPER", "LIVE"]) for (const side of ["LONG", "SHORT"]) for (const control of ["MANUAL", "BOT", "UNKNOWN"]) {
    test(`CurrentPositionCard OPEN ${mode} ${side} ${control}`, () => {
        const html = render(Current, { ...base, mode, side, control });
        for (const value of ["● OPEN", mode, side, control, "6,174 coin", "0.016195", "UNREALIZED PNL", "0.00", "643 ms"]) assert.ok(html.includes(value), value);
        assert.ok(!html.includes("NO OPEN POSITION"));
    });
}
for (const [position, expected] of [
    [{status:"FLAT"}, "NO OPEN POSITION"], [{status:"UNKNOWN"}, "POSITION STATE UNAVAILABLE"],
    [{status:"FLAT", freshness:"STALE"}, "POSITION DATA IS STALE"],
    [{status:"OPEN", freshness:"STALE"}, "UNKNOWN / STALE"],
    [{status:"UNKNOWN",reason:"MULTIPLE_POSITIONS",positions:[{symbol:"XRPUSDTM",side:"LONG"},{symbol:"ETHUSDTM",side:"SHORT"}]}, "2 OPEN POSITIONS DETECTED"],
    [{}, "POSITION STATE UNAVAILABLE"],
]) test(`CurrentPositionCard ${expected} ${position.status}`, () => {
    const html = render(Current, position);
    assert.ok(html.includes(expected));
    if (position.status !== "FLAT" || position.freshness) assert.ok(!html.includes("NO OPEN POSITION"));
    if (position.positions) for (const v of ["XRPUSDTM", "LONG", "ETHUSDTM", "SHORT"]) assert.ok(html.includes(v));
});
for (const Component of [Current, Last]) {
    for (const pnl of [null, 0, 1.23, -1.23]) test(`${Component.name} PnL ${pnl}`, () => {
        const html = render(Component, { ...base, unrealizedPnl: pnl, realizedPnl: pnl, entryPrice:null, exitPrice:null, markPrice:null });
        assert.ok(html.includes(pnl === null ? "—" : pnl.toFixed(2)));
        if (pnl === null) assert.ok(!html.includes("0.00"));
        assert.ok(html.includes(pnl > 0 ? "metric--positive" : pnl < 0 ? "metric--negative" : "metric--neutral"));
    });
    for (const unit of ["coin", "contract", null]) test(`${Component.name} unit ${unit}`, () => {
        const html = render(Component, { ...base, quantity:12, quantityUnit:unit, coinQuantity:6174, contractQuantity:12 });
        assert.ok(html.includes(unit === "coin" ? "12 coin" : unit === "contract" ? "12 contracts" : "12 UNIT UNKNOWN"));
        if (Component === Current) for (const text of ["COIN QUANTITY", "6,174", "CONTRACTS"]) assert.ok(html.includes(text));
    });
}
for (const mode of ["PAPER", "LIVE"]) for (const control of ["MANUAL", "BOT", "UNKNOWN"]) test(`LastPositionEventCard CLOSED ${mode} ${control}`, () => {
    const html = render(Last, { ...base, mode, control });
    for (const value of ["CLOSED", mode, control, "643 ms", "0.00", "MOMENTUM_DECAY", "REALIZED PNL"]) assert.ok(html.includes(value));
    assert.ok(!html.includes("UNREALIZED PNL"));
});
for (const event of ["NONE", "UNKNOWN", undefined]) test(`LastPositionEventCard ${event}`, () => {
    const html = render(Last, { event });
    assert.ok(html.includes(event === "NONE" ? "NO RECENT POSITION EVENT" : "RECENT POSITION EVENT UNAVAILABLE"));
    if (event !== "NONE") assert.ok(!html.includes("NO RECENT POSITION EVENT"));
});
test("CurrentPositionCard missing numeric facts remain unknown", () => {
    const html = render(Current, { status:"OPEN", side:"BUY", quantity:null });
    assert.ok(html.includes("SIDE UNKNOWN"));
    assert.ok(html.includes("— UNIT UNKNOWN"));
    assert.ok(!html.includes("0.00"));
    assert.ok(!html.includes(">BUY<"));
});
