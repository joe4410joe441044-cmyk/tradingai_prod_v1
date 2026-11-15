import assert from "node:assert/strict";
import test from "node:test";

import {
    HYRO_TRIAL_REFRESH_PATH,
    refreshHyroTrialProgress,
    validateHyroTrialRefreshChallenge,
} from "./hyroTrialRefreshApi.js";
import { ISSUED_HYRO_TRIAL_EVIDENCE } from "./hyroTrialReadModel.js";

const refreshed = () => ({
    ...ISSUED_HYRO_TRIAL_EVIDENCE,
    updatedAt: "2026-11-15T12:00:00Z",
    source: "HYRO OFFICIAL MCP / SERVER READ-ONLY REFRESH",
    dataQuality: "READY",
    metrics: {
        ...ISSUED_HYRO_TRIAL_EVIDENCE.metrics,
        observedAt: "2026-11-15T12:00:00Z",
        currentEquity: 25_125,
        tradeHistoryComplete: true,
    },
});

test("refresh response validator accepts only redacted scoped Trial data", () => {
    const accepted = validateHyroTrialRefreshChallenge(refreshed());
    assert.equal(accepted.metrics.currentEquity, 25_125);
    assert.equal(validateHyroTrialRefreshChallenge({ ...refreshed(), publicId: "must-not-enter-browser" }), null);
    assert.equal(validateHyroTrialRefreshChallenge({
        ...refreshed(),
        metrics: { ...refreshed().metrics, token: "secret" },
    }), null);
    assert.equal(validateHyroTrialRefreshChallenge({
        ...refreshed(),
        metrics: { ...refreshed().metrics, currentEquity: "25125" },
    }), null);
});

test("refresh uses same-origin credentials and CSRF without exposing secrets", async () => {
    const priorFetch = globalThis.fetch;
    const priorDocument = globalThis.document;
    const calls = [];
    globalThis.document = { cookie: "tradingai_csrf=fixture-csrf" };
    globalThis.fetch = async (path, options) => {
        calls.push({ path, options });
        return {
            ok: true,
            status: 200,
            async json() {
                return { ok: true, challenge: refreshed() };
            },
        };
    };
    try {
        const result = await refreshHyroTrialProgress();
        assert.equal(result.ok, true);
        assert.equal(result.challenge.metrics.currentEquity, 25_125);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].path, HYRO_TRIAL_REFRESH_PATH);
        assert.equal(calls[0].options.method, "POST");
        assert.equal(calls[0].options.credentials, "same-origin");
        assert.equal(calls[0].options.headers["X-TradingAI-CSRF"], "fixture-csrf");
        assert.equal("body" in calls[0].options, false);
    } finally {
        globalThis.fetch = priorFetch;
        globalThis.document = priorDocument;
    }
});

test("refresh converts unsafe or failed responses to fixed safe errors", async () => {
    const priorFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
        ok: true,
        status: 200,
        async json() {
            return { ok: true, challenge: { ...refreshed(), challengePublicId: "secret-id" } };
        },
    });
    try {
        const result = await refreshHyroTrialProgress();
        assert.deepEqual(result, { ok: false, status: 200, code: "HYRO_TRIAL_REFRESH_FAILED" });
        assert.doesNotMatch(JSON.stringify(result), /secret-id/);
    } finally {
        globalThis.fetch = priorFetch;
    }
});
