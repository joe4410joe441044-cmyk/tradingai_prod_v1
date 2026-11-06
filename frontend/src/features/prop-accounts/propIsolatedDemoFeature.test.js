import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { isPropIsolatedDemoEnabled } from "./propIsolatedDemoFeature.js";
import { createSyntheticPropEvaluationClient } from "./syntheticPropEvaluationClient.js";

test("PROP isolated demo is strict default OFF", () => {
    assert.equal(isPropIsolatedDemoEnabled({}), false);
    assert.equal(isPropIsolatedDemoEnabled({ VITE_PROP_ISOLATED_DEMO_ENABLED: "true" }), true);
    for (const value of ["TRUE", "True", "1", "yes", " true ", ""]) {
        assert.equal(isPropIsolatedDemoEnabled({ VITE_PROP_ISOLATED_DEMO_ENABLED: value }), false);
    }
});

test("same-origin synthetic client has fixed relative endpoints and reuses operator auth", async () => {
    const source = await readFile(new URL("./syntheticPropEvaluationClient.js", import.meta.url), "utf8");
    assert.match(source, /authenticatedControlRequest/);
    assert.match(source, /\/api\/prop-accounts\/synthetic\/accounts/);
    assert.match(source, /\/api\/prop-accounts\/synthetic\/evaluate/);
    assert.doesNotMatch(source, /https?:\/\//);
    assert.doesNotMatch(source, /credentials:\s*"omit"|mode:\s*"cors"/);
});

test("page is visibly synthetic and injects the authenticated client", async () => {
    const source = await readFile(new URL("../../pages/PropIsolatedDemoPage.jsx", import.meta.url), "utf8");
    assert.match(source, /DEFAULT OFF · ISOLATED DEMO/);
    assert.match(source, /SYNTHETIC \/ NOT OFFICIAL \/ NO EXECUTION AUTHORITY/);
    assert.match(source, /OfflinePropWorkflow client=\{syntheticPropEvaluationClient\}/);
});

test("client surfaces disabled and unauthenticated safe errors without fallback", async () => {
    for (const error of [
        { code: "PROP_DEMO_DISABLED", message: "isolated PROP demo is disabled", fields: {} },
        { code: "UNAUTHENTICATED", message: "login required", fields: {} },
    ]) {
        const calls = [];
        const client = createSyntheticPropEvaluationClient({
            request: async (path, options) => {
                calls.push([path, options]);
                return { ok: false, json: async () => ({ ok: false, error }) };
            },
        });
        await assert.rejects(
            client.createOfflineAccount({ requestId: "r" }),
            (failure) => failure.code === error.code,
        );
        assert.equal(calls.length, 1);
        assert.equal(calls[0][0], "/api/prop-accounts/synthetic/accounts");
        assert.equal(calls[0][1].method, "POST");
    }
});

test("client rejects non-JSON boundary responses", async () => {
    const client = createSyntheticPropEvaluationClient({
        request: async () => ({ ok: false, json: async () => { throw new Error("html"); } }),
    });
    await assert.rejects(
        client.evaluateOfflineAccount({}),
        (failure) => failure.code === "INVALID_BOUNDARY_RESPONSE",
    );
});
