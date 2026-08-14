import assert from "node:assert/strict";
import test from "node:test";

import {
    OPERATOR_AUTH_STATE,
    getOperatorAuthStatus,
    setOperatorAuthStatus,
    subscribeOperatorAuthStatus,
} from "./operatorAuth.js";

test("operator auth store notifies subscribers and exposes the current status", () => {
    const seen = [];
    const unsubscribe = subscribeOperatorAuthStatus((status) => seen.push(status));

    setOperatorAuthStatus(OPERATOR_AUTH_STATE.AUTHENTICATED);
    assert.equal(getOperatorAuthStatus(), OPERATOR_AUTH_STATE.AUTHENTICATED);
    assert.deepEqual(seen, [OPERATOR_AUTH_STATE.AUTHENTICATED]);

    setOperatorAuthStatus(OPERATOR_AUTH_STATE.UNAUTHENTICATED);
    assert.equal(getOperatorAuthStatus(), OPERATOR_AUTH_STATE.UNAUTHENTICATED);
    assert.deepEqual(seen, [
        OPERATOR_AUTH_STATE.AUTHENTICATED,
        OPERATOR_AUTH_STATE.UNAUTHENTICATED,
    ]);

    unsubscribe();
    setOperatorAuthStatus(OPERATOR_AUTH_STATE.AUTHENTICATED);
    assert.equal(seen.length, 2);
});
