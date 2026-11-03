import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
    DEFAULT_EVALUATION_INPUT,
    buildEvaluationRequest,
    requestIsCurrent,
    responseMatchesScope,
} from "./offlinePropWorkflow.js";

const ACCOUNT = {
    identity: {
        account_id: "acc_20000000000040008000000000000002",
        revision: 7,
    },
};

test("request keeps financial values as strings and maps empty values to explicit null", () => {
    const request = buildEvaluationRequest({
        requestId: "r-1",
        account: ACCOUNT,
        input: { ...DEFAULT_EVALUATION_INPUT, balance: "0", equity: "", realizedPnl: "-0.000000000000000001" },
    });
    assert.equal(request.accountId, ACCOUNT.identity.account_id);
    assert.equal(request.identityRevision, 7);
    assert.equal(request.observation.balance, "0");
    assert.equal(request.observation.equity, null);
    assert.equal(request.observation.realizedPnl, "-0.000000000000000001");
    assert.equal(typeof request.rules.initialBalance, "string");
});

test("stale response guard requires request, account, revision, and unchanged generation", () => {
    const response = { requestId: "r-1", accountId: "acc-a", identityRevision: 2 };
    const expected = { requestId: "r-1", accountId: "acc-a", identityRevision: 2, generation: 4, currentGeneration: 4 };
    assert.equal(responseMatchesScope(response, expected), true);
    assert.equal(responseMatchesScope(response, { ...expected, currentGeneration: 5 }), false);
    assert.equal(responseMatchesScope({ ...response, accountId: "acc-b" }, expected), false);
    assert.equal(responseMatchesScope({ ...response, identityRevision: 3 }, expected), false);
    assert.equal(responseMatchesScope({ ...response, requestId: "late" }, expected), false);
});

test("request ownership rejects replaced controllers and unmounted components", () => {
    const first = {};
    const second = {};
    assert.equal(requestIsCurrent(first, first, true), true);
    assert.equal(requestIsCurrent(first, second, true), false);
    assert.equal(requestIsCurrent(first, first, false), false);
});

test("workflow UI has explicit modes, inputs, loading/error/result paths, and no credential fields", async () => {
    const component = await readFile(new URL("../../components/prop-accounts/OfflinePropWorkflow.jsx", import.meta.url), "utf8");
    assert.match(component, /INPUT EVALUATION MODE/);
    assert.match(component, /サンプル口座を作成・選択/);
    assert.match(component, /status === "LOADING"/);
    assert.match(component, /requestIsCurrent/);
    assert.match(component, /evaluationToken\.current/);
    assert.match(component, /mounted\.current = false/);
    assert.match(component, /aria-live="polite"/);
    assert.match(component, /aria-describedby/);
    assert.match(component, /aria-busy/);
    assert.match(component, /offline-error/);
    assert.match(component, /offline-result/);
    assert.match(component, /revision更新/);
    assert.match(component, /SYNTHETIC \/ NOT OFFICIAL/);
    assert.doesNotMatch(component, /name=["'](?:apiKey|secret|credential|credentialPath)["']/i);
    assert.doesNotMatch(component, /localStorage|sessionStorage|indexedDB/);
});

test("client is limited to three loopback POST endpoints and has no wildcard credentials", async () => {
    const client = await readFile(new URL("./offlinePropWorkflowClient.js", import.meta.url), "utf8");
    assert.match(client, /http:\/\/127\.0\.0\.1:4188/);
    assert.match(client, /\/offline\/accounts/);
    assert.match(client, /\/offline\/accounts\/revise/);
    assert.match(client, /\/offline\/evaluate/);
    assert.doesNotMatch(client, /https:\/\//);
    assert.match(client, /credentials: "omit"/);
});
