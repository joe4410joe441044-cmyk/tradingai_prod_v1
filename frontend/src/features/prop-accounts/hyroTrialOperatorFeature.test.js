import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
    HYRO_SAMPLE_CHALLENGES,
    deriveHyroTrialReadiness,
    isHyroTrialOperatorEnabled,
    syntheticHyroTrialClient,
    validateHyroTrialSettings,
} from "./hyroTrialOperatorFeature.js";

const validSettings = Object.freeze({
    strategy: "TREND_FOLLOW_SAMPLE",
    riskPerTradePercent: "0.5",
    dailyLossLimitPercent: "5",
    maximumLossPercent: "10",
});

test("Hyro trial operator preview is strict default OFF", () => {
    assert.equal(isHyroTrialOperatorEnabled({}), false);
    assert.equal(isHyroTrialOperatorEnabled({ VITE_HYRO_TRIAL_OPERATOR_PREVIEW_ENABLED: "true" }), true);
    for (const value of ["TRUE", "1", "yes", " true ", ""]) {
        assert.equal(isHyroTrialOperatorEnabled({ VITE_HYRO_TRIAL_OPERATOR_PREVIEW_ENABLED: value }), false);
    }
});

test("sample connector stays in memory and reports zero external/order calls", async () => {
    const connection = await syntheticHyroTrialClient.checkConnection();
    const listing = await syntheticHyroTrialClient.listChallenges();
    const started = await syntheticHyroTrialClient.startSimulation();
    const stopped = await syntheticHyroTrialClient.stopSimulation();
    assert.equal(connection.externalNetworkCalls, 0);
    assert.equal(connection.orderCalls, 0);
    assert.equal(listing.externalNetworkCalls, 0);
    assert.equal(listing.orderCalls, 0);
    assert.equal(started.orderCalls, 0);
    assert.equal(stopped.orderCalls, 0);
    assert.equal(listing.challenges, HYRO_SAMPLE_CHALLENGES);
});

test("readiness requires selected account and account-scoped valid saved settings", () => {
    assert.deepEqual(validateHyroTrialSettings(validSettings), { valid: true, errors: [] });
    assert.equal(validateHyroTrialSettings({ ...validSettings, riskPerTradePercent: "0" }).valid, false);
    assert.equal(deriveHyroTrialReadiness({ selectedChallenge: null, savedSettings: null, simulation: { state: "STOPPED" } }).state, "BLOCKED");
    const ready = deriveHyroTrialReadiness({ selectedChallenge: HYRO_SAMPLE_CHALLENGES[0], savedSettings: validSettings, simulation: { state: "STOPPED" } });
    assert.equal(ready.state, "READY");
    assert.equal(ready.executionMode, "SIMULATION_ONLY_NO_ORDERS");
    assert.equal(ready.realHyroStartEnabled, false);
    assert.equal(deriveHyroTrialReadiness({ selectedChallenge: HYRO_SAMPLE_CHALLENGES[0], savedSettings: validSettings, simulation: { state: "RUNNING" } }).state, "BLOCKED");
});

test("normal app integration is feature-gated and Hyro branch excludes production lifecycle handlers", async () => {
    const [app, dashboard, surface, accountStatus] = await Promise.all([
        readFile(new URL("../../App.jsx", import.meta.url), "utf8"),
        readFile(new URL("../../pages/Dashboard.jsx", import.meta.url), "utf8"),
        readFile(new URL("../../components/prop-accounts/HyroTrialOperationSurface.jsx", import.meta.url), "utf8"),
        readFile(new URL("../../components/prop-accounts/HyroTrialAccountStatus.jsx", import.meta.url), "utf8"),
    ]);
    assert.match(app, /HyroTrialOperatorProvider/);
    assert.match(dashboard, /HyroTrialOperationSurface/);
    const authGate = await readFile(new URL("../../components/auth/OperationAuthGate.jsx", import.meta.url), "utf8");
    assert.match(authGate, /preview-disabled-kucoin-controls/);
    assert.match(authGate, /<fieldset/);
    assert.match(authGate, /disabled/);
    assert.match(surface, /通常口座 — KuCoin/);
    assert.match(surface, /PROP口座 — HyroTrader/);
    assert.match(surface, /注文を送らないシミュレーション/);
    assert.match(surface, /実Hyro START（未確認のため無効）/);
    assert.doesNotMatch(surface, /authenticatedControlRequest|requestBotStop|live-order-entry|\/api\//);
    assert.match(accountStatus, /未確認値を0として表示しません/);
});
