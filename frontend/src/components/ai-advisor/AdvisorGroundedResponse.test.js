import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("grounded response renders only plain validated fields and no controls", async () => {
    const source = await readFile(
        new URL("./AdvisorGroundedResponse.jsx", import.meta.url),
        "utf8",
    );
    for (const label of [
        "Conclusion", "Citation", "Version", "Freshness",
        "Uncertainty", "Limitations", "Safe Alternative", "Refusal",
    ]) {
        assert.match(source, new RegExp(label));
    }
    assert.match(source, /claim\.claimType/);
    for (const forbidden of [
        "dangerouslySetInnerHTML", "innerHTML", "href=", "<a ",
        "fetch(", "button", "localStorage", "sessionStorage",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
});
