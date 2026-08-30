import assert from "node:assert/strict";
import test from "node:test";

import { formatMoneyManagementAxisTimestamp } from "./moneyManagementChartFormatters.js";

test("chart axis timestamps use compact MM/DD labels without mutating input", () => {
    const timestamp = "2026-08-29T16:47:24.888745Z";
    const point = { timestamp };

    assert.equal(formatMoneyManagementAxisTimestamp(point.timestamp), "08/29");
    assert.equal(point.timestamp, timestamp);
});

test("chart axis timestamp formatter preserves unknown values", () => {
    assert.equal(formatMoneyManagementAxisTimestamp("Not reported"), "Not reported");
    assert.equal(formatMoneyManagementAxisTimestamp(null), null);
});
