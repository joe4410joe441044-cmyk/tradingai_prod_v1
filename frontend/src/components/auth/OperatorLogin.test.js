import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
    new URL("./OperatorLogin.jsx", import.meta.url),
    "utf8",
);

test("authenticated state renders bilingual Authenticated and Logout labels", () => {
    assert.match(source, /Authenticated（認証済み）/);
    assert.match(source, /Logout（ログアウト）/);
});

test("logout still revokes the operator session via the auth client", () => {
    assert.match(source, /client\.logout\(\)/);
    assert.match(source, /setOperatorAuthStatus\(OPERATOR_AUTH_STATE\.UNAUTHENTICATED\)/);
});

test("operator login has no trading or execution integration", () => {
    assert.doesNotMatch(source, /botStart|botStop|order|position|execute/i);
});
