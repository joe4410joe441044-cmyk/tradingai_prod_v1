import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

var source = await readFile(new URL("./MarketRecorderPage.jsx", import.meta.url), "utf8");
var styles = await readFile(new URL("../styles/market-recorder.css", import.meta.url), "utf8");

test("Recorder page wires state-aware START and STOP controls", function () {
    assert.match(source, /useRecorderControl\(recorderStatus, \[recorderStorage, recorderArchives\]\)/);
    assert.match(source, /disabled={!recorderControl\.canStart}/);
    assert.match(source, /disabled={!recorderControl\.canStop}/);
});

test("Recorder page exposes bounded archive pagination", function () {
    assert.match(source, /recorderArchives\.previousPage/);
    assert.match(source, /recorderArchives\.nextPage/);
    assert.match(source, /totalPages/);
});

test("Recorder page uses a compact responsive overview and prominent controls", function () {
    assert.match(source, /className="mr-overview-grid"/);
    assert.match(source, /mr-control-button--start/);
    assert.match(source, /mr-control-button--stop/);
    assert.match(styles, /\.mr-overview-grid[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
    assert.match(styles, /\.mr-control-button[\s\S]*min-height:\s*52px/);
    assert.match(styles, /@media \(max-width: 760px\)[\s\S]*\.mr-overview-grid[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/);
});

test("Recorder page does not present archive placeholders as working actions", function () {
    assert.match(source, /Download API not implemented/);
    assert.match(source, /Replay not yet available/);
    assert.match(source, /Delete not yet available/);
});

test("Recorder diagnostics show only authority-backed counters", function () {
    assert.match(source, /Messages Received/);
    assert.match(source, /Sequence Anomalies/);
    assert.doesNotMatch(source, /<dt>Queue<\/dt>/);
    assert.doesNotMatch(source, /<dt>Latency<\/dt>/);
    assert.doesNotMatch(source, /<dt>Buffer<\/dt>/);
});
