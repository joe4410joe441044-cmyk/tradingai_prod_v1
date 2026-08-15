import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./SupervisorDetailsDisclosure.jsx", import.meta.url), "utf8");
const historySource = await readFile(new URL("../../features/supervisor/history/SupervisorHistoryPanel.jsx", import.meta.url), "utf8");

test("details start collapsed and use an accessible disclosure button", function () {
    assert.match(source, /useState\(false\)/);
    assert.match(source, /aria-expanded={isExpanded}/);
    assert.match(source, /aria-controls={contentId}/);
    assert.ok(source.includes("onClick={() => setIsExpanded((expanded) => !expanded)}"));
});

test("history is mounted only after the outer Details disclosure opens", function () {
    assert.match(source, /import SupervisorHistoryPanel/);
    assert.ok(source.indexOf("{isExpanded &&") < source.indexOf("<SupervisorHistoryPanel"));
});

test("snapshot panel is mounted lazily alongside history after disclosure opens", function () {
    assert.match(source, /import SupervisorSnapshotPanel/);
    assert.ok(source.indexOf("{isExpanded &&") < source.indexOf("<SupervisorSnapshotPanel"));
    assert.ok(source.indexOf("<SupervisorSnapshotPanel") < source.indexOf("<SupervisorHistoryPanel"));
});

test("details reveal only the Snapshot, Diagnostics, and History on demand", function () {
    assert.match(historySource, /Decision \/ Change History/);
    assert.match(source, /{isExpanded && \(/);
    assert.doesNotMatch(source, /<p>NOT CONNECTED<\/p>/);
    assert.doesNotMatch(source, /MM Assessment|Current Settings|Numeric Evidence|System \/ Runtime/);
});

test("details contain no mock metrics or runtime integration", function () {
    assert.doesNotMatch(source, /fetch\(|axios|equityValue|riskBudget|exposureValue/);
});
