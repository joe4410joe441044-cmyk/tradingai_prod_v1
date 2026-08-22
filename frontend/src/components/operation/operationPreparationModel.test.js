import assert from "node:assert/strict";
import test from "node:test";

import { deriveOperationReadiness } from "./operationPreparationModel.js";

const readyInputs = (overrides = {}) => ({
    selectionMode: "MANUAL",
    emergencyState: "READY",
    position: "FLAT",
    pendingOrder: false,
    governanceStatus: "READY",
    realOrderAllowed: false,
    executionEnabled: false,
    executionEntryAllowed: true,
    recommendedAction: "CONTINUE",
    riskState: "NORMAL",
    requestedLeverage: 3,
    maximumLeverage: 5,
    ...overrides,
});

for (const [name, requestedLeverage, maximumLeverage, expected] of [
    ["requested 3 / maximum 5 allows", 3, 5, "READY"],
    ["requested 5 / maximum 5 allows", 5, 5, "READY"],
    ["requested 7 / maximum 5 blocks", 7, 5, "BLOCKED"],
    ["zero requested blocks", 0, 5, "BLOCKED"],
    ["negative requested blocks", -1, 5, "BLOCKED"],
    ["malformed requested blocks", "invalid", 5, "BLOCKED"],
    ["non-finite requested blocks", Infinity, 5, "BLOCKED"],
    ["missing maximum blocks", 3, undefined, "BLOCKED"],
    ["malformed maximum blocks", 3, "invalid", "BLOCKED"],
    ["non-finite maximum blocks", 3, Infinity, "BLOCKED"],
]) {
    test(name, () => {
        const result = deriveOperationReadiness(readyInputs({
            requestedLeverage,
            maximumLeverage,
        }));
        assert.equal(result.leverageReadiness, expected);
        assert.equal(result.reviewReadiness, expected);
    });
}
