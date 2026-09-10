import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
    normalizePaperCapitalPreset,
    validatePaperCapitalInput,
} from "./paperCapitalModel.js";

const controlSource = await readFile(
    new URL("./PaperCapitalControl.jsx", import.meta.url),
    "utf8",
);

test("PaperCapitalControl centralizes manual validation and preset normalization", () => {
    assert.match(controlSource, /validatePaperCapitalInput\(capitalInput\)/);
    assert.match(controlSource, /normalizePaperCapitalPreset\(realAvailableRaw\)/);
    assert.doesNotMatch(controlSource, /chooseCapital\(realAvailableRaw,/);
});

test("confirmation and POST payload use the same canonical Paper Capital", () => {
    assert.match(controlSource, /capital: canonicalCapital/);
    assert.match(controlSource, /New Simulation Capital: \{canonicalCapital\} USDT/);
    assert.doesNotMatch(controlSource, /capital: capitalInput\.trim\(\)/);

    const capitalInput = normalizePaperCapitalPreset(7.91836966);
    const { canonical } = validatePaperCapitalInput(capitalInput);
    const confirmationValue = canonical;
    const payload = { capital: canonical };

    assert.equal(capitalInput, "7.92");
    assert.equal(confirmationValue, "7.92");
    assert.equal(payload.capital, confirmationValue);
});

test("manual over-precision remains invalid instead of being normalized", () => {
    assert.equal(validatePaperCapitalInput("100.001").valid, false);
});
