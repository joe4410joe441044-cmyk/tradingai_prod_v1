import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
    new URL("./OperationAuthGate.jsx", import.meta.url),
    "utf8",
);

test("gate renders the operator login and an auth required notice", () => {
    assert.match(source, /<OperatorLogin/);
    assert.match(source, /Log in as the\s+operator to enable Operation control/);
    assert.match(source, /data-testid="operation-auth-gate-notice"/);
});

test("gate renders operation children only when authenticated", () => {
    assert.match(source, /authenticated \?/);
    assert.match(source, /status === OPERATOR_AUTH_STATE\.AUTHENTICATED/);
    assert.match(source, /\bchildren\b/);
});

test("gate reuses the existing operator auth store subscription", () => {
    assert.match(source, /subscribeOperatorAuthStatus/);
    assert.match(source, /getOperatorAuthStatus/);
});

test("gate does not invent a second login flow", () => {
    // Must reuse OperatorLogin from the existing auth feature, not a new form.
    assert.match(source, /import OperatorLogin from "\.\/OperatorLogin"/);
    assert.doesNotMatch(source, /type="password"/);
});
