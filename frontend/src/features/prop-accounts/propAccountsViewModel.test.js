import assert from "node:assert/strict";
import test from "node:test";

import {
    displayAmount,
    displayQuantity,
    formatDecimalString,
    normalizePropAccountsView,
    selectedAccount,
} from "./propAccountsViewModel.js";
import {
    NORMAL_ACCOUNT_ID,
    PROP_ACCOUNT_ID,
    PROP_FIXTURE_SCENARIOS,
    createPropAccountsFixture,
} from "./propAccountsFixtures.js";

test("ten required scenarios normalize with independent axes and disabled execution", () => {
    assert.equal(PROP_FIXTURE_SCENARIOS.length, 10);
    for (const scenario of PROP_FIXTURE_SCENARIOS) {
        const view = normalizePropAccountsView(createPropAccountsFixture({ scenarioId: scenario.id }));
        assert.equal(view.status, "READY", scenario.id);
        assert.equal(view.fixture.enabled, true, scenario.id);
        const account = selectedAccount(view);
        assert.equal(account.accountSummary.accountId, PROP_ACCOUNT_ID);
        assert.equal(account.executionCapability.authorityState, "DISABLED");
        assert.equal(account.executionCapability.grantsExecutionAuthority, false);
        assert.equal(account.aiContext.status, "NOT_INTEGRATED");
        assert.equal(account.aiContext.grantsExecutionAuthority, false);
        assert.equal(typeof account.connection.state, "string");
        assert.equal(typeof account.observation.quality, "string");
        assert.equal(typeof account.propRules.readiness, "string");
    }
});

test("decimal display preserves large, high precision, negative, and zero strings", () => {
    assert.equal(
        formatDecimalString("98765432101234567890.123456789012345678"),
        "98,765,432,101,234,567,890.123456789012345678",
    );
    assert.equal(formatDecimalString("-42.000000000000000009"), "−42.000000000000000009");
    assert.equal(displayAmount({ amount: "0", currency: "USDT", unit: "ASSET" }), "0 USDT");
    assert.equal(displayAmount(null), "未取得");
    assert.equal(displayAmount({ amount: "NaN", currency: "USDT", unit: "ASSET" }), "未取得（不正な値）");
    assert.equal(displayQuantity("0.000000010000000001", "BTC"), "0.000000010000000001 BTC");
});

test("USD equivalent and USDT asset are not presented as the same unit", () => {
    assert.equal(displayAmount({ amount: "1.25", currency: "USD", unit: "USD_EQUIVALENT" }), "1.25 USD相当");
    assert.equal(displayAmount({ amount: "1.25", currency: "USDT", unit: "ASSET" }), "1.25 USDT");
});

test("account selection is scope exact and never mixes normal and PROP data", () => {
    const prop = normalizePropAccountsView(createPropAccountsFixture({
        scenarioId: "connected_read_only",
        viewedAccountId: PROP_ACCOUNT_ID,
    }));
    const normal = normalizePropAccountsView(createPropAccountsFixture({
        scenarioId: "connected_read_only",
        viewedAccountId: NORMAL_ACCOUNT_ID,
    }));
    assert.equal(selectedAccount(prop).accountSummary.accountType, "PROP");
    assert.equal(selectedAccount(prop).positions.items[0].symbol, "BTCUSDT");
    assert.equal(selectedAccount(normal).accountSummary.accountType, "NORMAL");
    assert.equal(selectedAccount(normal).positions.items.length, 0);
    assert.equal(selectedAccount(normal).propRules.readiness, "NOT_APPLICABLE");
});

test("partial and stale observations cannot preserve READY rules", () => {
    for (const scenarioId of ["partial_data", "stale_data"]) {
        const account = selectedAccount(normalizePropAccountsView(createPropAccountsFixture({ scenarioId })));
        assert.equal(account.connection.state, "CONNECTED_READ_ONLY");
        assert.notEqual(account.observation.quality, "COMPLETE");
        assert.equal(account.propRules.readiness, "RULES_UNKNOWN");
    }
});

test("empty successful collections differ from failed collections", () => {
    const empty = selectedAccount(normalizePropAccountsView(createPropAccountsFixture({ scenarioId: "rules_unknown" })));
    const failed = selectedAccount(normalizePropAccountsView(createPropAccountsFixture({ scenarioId: "auth_failure" })));
    assert.deepEqual([empty.positions.quality, empty.positions.items.length], ["COMPLETE", 0]);
    assert.deepEqual([failed.positions.quality, failed.positions.items.length], ["FAILED", 0]);
});

test("invalid envelope and missing viewed account fail closed without fallback", () => {
    const fixture = createPropAccountsFixture();
    const invalidEnvelope = normalizePropAccountsView({ ...fixture, fixture: { enabled: false } });
    const missingView = normalizePropAccountsView({ ...fixture, viewedAccountId: "acc_30000000000040008000000000000003" });
    assert.deepEqual(invalidEnvelope.accounts, []);
    assert.equal(invalidEnvelope.status, "INVALID");
    assert.equal(missingView.errorCode, "VIEWED_ACCOUNT_NOT_FOUND");
    assert.equal(selectedAccount(missingView), null);
});

test("fixture modules expose no secret-bearing fields or side-effect APIs", async () => {
    const { readFile } = await import("node:fs/promises");
    const sources = await Promise.all([
        readFile(new URL("./propAccountsFixtures.js", import.meta.url), "utf8"),
        readFile(new URL("./propAccountsViewModel.js", import.meta.url), "utf8"),
    ]);
    for (const source of sources) {
        assert.doesNotMatch(source, /fetch\s*\(|axios|WebSocket|localStorage|sessionStorage|indexedDB/);
        assert.doesNotMatch(source, /apiKey|secret|signature|credentialPath|rawUid|rawIp|rawResponse/i);
    }
});


test("normalized amounts preserve invalid, missing, and zero as distinct states", () => {
    const fixture = createPropAccountsFixture({ scenarioId: "connected_read_only" });
    fixture.accounts[1] = {
        ...fixture.accounts[1],
        observation: {
            ...fixture.accounts[1].observation,
            balance: { amount: "NaN", currency: "USDT", unit: "ASSET" },
            equity: null,
            realizedPnl: { amount: "0", currency: "USDT", unit: "ASSET" },
        },
    };
    const account = selectedAccount(normalizePropAccountsView(fixture));
    assert.equal(displayAmount(account.observation.balance), "未取得（不正な値）");
    assert.equal(displayAmount(account.observation.equity), "未取得");
    assert.equal(displayAmount(account.observation.realizedPnl), "0 USDT");
});

test("invalid collection items never normalize to a successful empty collection", () => {
    const fixture = createPropAccountsFixture({ scenarioId: "connected_read_only" });
    fixture.accounts[1] = {
        ...fixture.accounts[1],
        positions: {
            quality: "COMPLETE",
            items: [{ symbol: "BTCUSDT", side: "LONG", quantity: "NaN" }],
            missingFields: [],
        },
        openOrders: {
            ...fixture.accounts[1].openOrders,
            items: [
                ...fixture.accounts[1].openOrders.items,
                { symbol: "ETHUSDT", side: "BUY", quantity: "invalid" },
            ],
        },
    };
    const account = selectedAccount(normalizePropAccountsView(fixture));
    assert.deepEqual([account.positions.quality, account.positions.items.length], ["FAILED", 0]);
    assert.equal(account.positions.invalidItemCount, 1);
    assert.ok(account.positions.missingFields.includes("invalidItems"));
    assert.equal(account.openOrders.quality, "PARTIAL");
    assert.equal(account.openOrders.items.length, 1);
});

test("invalid rule limits fail readiness closed instead of being silently removed", () => {
    const fixture = createPropAccountsFixture({ scenarioId: "connected_read_only" });
    fixture.accounts[1] = {
        ...fixture.accounts[1],
        propRules: {
            ...fixture.accounts[1].propRules,
            limits: [...fixture.accounts[1].propRules.limits, { state: "PASS" }],
        },
    };
    const account = selectedAccount(normalizePropAccountsView(fixture));
    assert.equal(account.propRules.readiness, "RULES_UNKNOWN");
    assert.ok(account.propRules.unknownFields.includes("invalidRuleLimits"));
});
