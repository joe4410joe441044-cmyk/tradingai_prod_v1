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
        "Unknown / Not Available（確認できない情報）",
        "Reason（理由）",
        "Missing Information（不足している情報）",
        "Next Step（次にすること）",
        "Decision Impact（判断への影響）",
        "Operational Effect",
    ]) {
        assert.match(source, new RegExp(label));
    }
    assert.match(source, /claim\.claimType/);
    assert.match(source, /response\.actionableUnknowns/);
    assert.match(source, /item\.safeNextStep/);
    assert.match(source, /item\.decisionImpact/);
    for (const forbidden of [
        "dangerouslySetInnerHTML", "innerHTML", "href=", "<a ",
        "fetch(", "button", "localStorage", "sessionStorage",
    ]) {
        assert.doesNotMatch(source, new RegExp(forbidden.replace("(", "\\(")));
    }
});
