import assert from "node:assert/strict";
import test from "node:test";
import {
    normalizePaperCapitalPreset,
    PAPER_CAPITAL_ERRORS,
    validatePaperCapitalInput,
} from "./paperCapitalModel.js";

for (const [input, canonical] of [
    ["100", "100.00"],
    ["100.0", "100.00"],
    ["100.00", "100.00"],
    ["1000", "1000.00"],
    ["10000", "10000.00"],
]) {
    test(`manual Paper Capital ${input} is valid and canonical`, () => {
        assert.deepEqual(validatePaperCapitalInput(input), {
            valid: true,
            canonical,
            error: null,
        });
    });
}

test("manual Paper Capital over two decimal places fails closed", () => {
    assert.deepEqual(validatePaperCapitalInput("100.001"), {
        valid: false,
        canonical: null,
        error: PAPER_CAPITAL_ERRORS.invalid,
    });
});

test("manual Paper Capital preserves required, minimum, and maximum validation", () => {
    assert.equal(validatePaperCapitalInput("").error, PAPER_CAPITAL_ERRORS.required);
    assert.equal(validatePaperCapitalInput("0.009").error, PAPER_CAPITAL_ERRORS.invalid);
    assert.equal(validatePaperCapitalInput("0.00").error, PAPER_CAPITAL_ERRORS.minimum);
    assert.equal(validatePaperCapitalInput("1000000000.01").error, PAPER_CAPITAL_ERRORS.maximum);
});

test("REAL AVAILABLE exchange precision is normalized before use as Paper Capital", () => {
    const normalized = normalizePaperCapitalPreset(7.91836966);

    assert.equal(normalized, "7.92");
    assert.deepEqual(validatePaperCapitalInput(normalized), {
        valid: true,
        canonical: "7.92",
        error: null,
    });
});

test("non-finite machine presets are not normalized", () => {
    assert.equal(normalizePaperCapitalPreset(undefined), null);
    assert.equal(normalizePaperCapitalPreset("not-a-number"), null);
});
