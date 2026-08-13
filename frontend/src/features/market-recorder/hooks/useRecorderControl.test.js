import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

var source = await readFile(new URL("./useRecorderControl.js", import.meta.url), "utf8");

test("control hook is state-aware and guards duplicate requests", function () {
    assert.match(source, /RECORDER_STATUS_STATE\.RUNNING/);
    assert.match(source, /RECORDER_STATUS_STATE\.STOPPED/);
    assert.match(source, /inFlightRef\.current/);
    assert.match(source, /canStart/);
    assert.match(source, /canStop/);
});

test("control hook interprets domain result and refreshes live resources", function () {
    assert.match(source, /result\.successful !== true/);
    assert.match(source, /CONTROL_CONFLICT/);
    assert.match(source, /refreshStatus\(\)/);
    assert.match(source, /resource\.refresh\(\)/);
    assert.match(source, /Promise\.all\(refreshes\)/);
});
