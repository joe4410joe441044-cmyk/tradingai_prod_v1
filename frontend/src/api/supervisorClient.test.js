import assert from "node:assert/strict";
import test from "node:test";

import {
    deriveProviderConnection,
    getSupervisorProviderStatus,
    getSupervisorSnapshot,
    llmInterpretationSeverity,
    normalizeSupervisorProviderStatus,
    SupervisorStatusError,
    supervisorCoreSeverity,
} from "./supervisorClient.js";

test("normalization defaults missing fields to safe UNKNOWN/false values", () => {
    const status = normalizeSupervisorProviderStatus(null);
    assert.equal(status.provider, "UNKNOWN");
    assert.equal(status.supervisorCore, "UNKNOWN");
    assert.equal(status.llmStatus, "UNKNOWN");
    assert.equal(status.providerConfigured, false);
    assert.equal(status.providerEnabled, false);
    assert.equal(status.providerAvailable, false);
    assert.equal(status.operationalEffect, "NONE");
});

test("Core AVAILABLE with Provider DISABLED and LLM DISABLED keeps Core normal (Test A)", () => {
    const status = normalizeSupervisorProviderStatus({
        provider: "DISABLED",
        supervisorCore: "AVAILABLE",
        llmStatus: "DISABLED",
        providerConfigured: true,
        providerEnabled: false,
        providerAvailable: false,
        llmInterpretationAvailable: false,
        operationalEffect: "NONE",
    });
    assert.equal(supervisorCoreSeverity(status.supervisorCore), "normal");
    assert.equal(llmInterpretationSeverity(status.llmStatus), "neutral");
    assert.equal(deriveProviderConnection(status), "DISABLED");
});

test("providerConfigured true with disabled provider is never CONNECTED (Test B)", () => {
    const status = normalizeSupervisorProviderStatus({
        provider: "DISABLED",
        providerConfigured: true,
        providerEnabled: false,
        providerAvailable: false,
        llmInterpretationAvailable: false,
    });
    assert.notEqual(deriveProviderConnection(status), "CONNECTED");
    assert.equal(status.providerConfigured, true);
    assert.equal(status.providerEnabled, false);
    assert.equal(status.providerAvailable, false);
});

test("LLM UNAVAILABLE degrades AI layer but preserves Core AVAILABLE (Test C)", () => {
    const status = normalizeSupervisorProviderStatus({
        supervisorCore: "AVAILABLE",
        llmStatus: "UNAVAILABLE",
    });
    assert.equal(supervisorCoreSeverity(status.supervisorCore), "normal");
    assert.equal(llmInterpretationSeverity(status.llmStatus), "degraded");
});

test("LLM ERROR is an AI layer error while operational effect stays NONE (Test D)", () => {
    const status = normalizeSupervisorProviderStatus({
        supervisorCore: "AVAILABLE",
        llmStatus: "ERROR",
        operationalEffect: "NONE",
    });
    assert.equal(llmInterpretationSeverity(status.llmStatus), "error");
    assert.equal(status.operationalEffect, "NONE");
});

test("conversation disabled leaves the Supervisor Core available (Test F)", () => {
    const status = normalizeSupervisorProviderStatus({
        provider: "DISABLED",
        supervisorCore: "AVAILABLE",
        llmStatus: "DISABLED",
        providerConfigured: true,
        providerEnabled: false,
        providerAvailable: false,
        llmInterpretationAvailable: false,
        operationalEffect: "NONE",
    });
    assert.equal(supervisorCoreSeverity(status.supervisorCore), "normal");
    assert.notEqual(deriveProviderConnection(status), "CONNECTED");
    assert.equal(status.mode, "SHADOW");
});

test("Shadow mode yields Operational Effect NONE with no execution authority (Test G)", () => {
    const status = normalizeSupervisorProviderStatus({
        provider: "DISABLED",
        supervisorCore: "AVAILABLE",
        llmStatus: "DISABLED",
        operationalEffect: "NONE",
        mode: "SHADOW",
    });
    assert.equal(status.mode, "SHADOW");
    assert.equal(status.operationalEffect, "NONE");
    assert.equal(supervisorCoreSeverity(status.supervisorCore), "normal");
    assert.equal(deriveProviderConnection(status), "NOT_CONFIGURED");
});

test("connection is only reported when enabled and available together", () => {
    assert.equal(deriveProviderConnection(normalizeSupervisorProviderStatus({
        providerConfigured: true, providerEnabled: true, providerAvailable: true, llmInterpretationAvailable: true,
    })), "CONNECTED");
    assert.equal(deriveProviderConnection(normalizeSupervisorProviderStatus({
        providerConfigured: true, providerEnabled: false, providerAvailable: true, llmInterpretationAvailable: true,
    })), "DISABLED");
});

test("getSupervisorProviderStatus surfaces a non-ok response as a typed error", async () => {
    const fetchImpl = async () => ({ ok: false, json: async () => ({ code: "SERVICE_UNAVAILABLE", message: "down" }) });
    await assert.rejects(
        getSupervisorProviderStatus({ fetchImpl }),
        (error) => error instanceof SupervisorStatusError && error.code === "SERVICE_UNAVAILABLE",
    );
});

test("getSupervisorSnapshot preserves a successful bounded payload", async () => {
    const payload = { capturedAt: "2026-08-13T00:00:00Z", overallFreshness: "FRESH", warnings: [] };
    const fetchImpl = async () => ({ ok: true, json: async () => payload });
    const result = await getSupervisorSnapshot({ fetchImpl });
    assert.equal(result.capturedAt, payload.capturedAt);
    assert.equal(result.overallFreshness, "FRESH");
});
