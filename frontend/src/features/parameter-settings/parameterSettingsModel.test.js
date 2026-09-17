import assert from "node:assert/strict";
import test from "node:test";

import {
    ADVANCED_PARAMETER_GROUPS,
    LIVE_WRITABLE_PARAMETER_NAMES,
    buildAdvancedGroups,
    buildConfigurationPayload,
    buildEffectiveRevisionModel,
    buildPrimaryRows,
    buildRuntimeContext,
    countAdvancedParameters,
    countPrimaryParameters,
    dedupeWarnings,
    formatParameterValue,
    isLiveWritable,
    normalizeDraftForSave,
    normalizeParameterValue,
    performSave,
    splitSchema,
    unitSymbol,
    validateDraftValue,
} from "./parameterSettingsModel.js";

const metadata = (name, overrides = {}) => ({
    name,
    labelEn: name,
    labelJa: name,
    unit: "normalized score (0.0-1.0)",
    minimum: 0,
    maximum: 1,
    minimumInclusive: true,
    maximumInclusive: true,
    precision: 6,
    valueType: "float",
    couplingGroup: "ENTRY_QUALITY",
    tier: "PRIMARY",
    editable: true,
    description: name,
    ...overrides,
});

const schema = {
    parameters: [
        metadata("minimumCompositeScore"),
        metadata("maximumStrategySpreadPct", {
            unit: "percent (0-100 scale)",
            minimumInclusive: false,
            maximum: 5,
        }),
        metadata("momentumWindowSeconds", {
            unit: "seconds",
            minimum: 5,
            maximum: 600,
        }),
        metadata("minimumStrategyConfidence"),
        metadata("maximumHoldMs", {
            unit: "milliseconds",
            precision: 0,
            valueType: "int",
            minimum: 100,
            maximum: 60000,
        }),
        metadata("minimumHoldMs", {
            tier: "ADVANCED",
            unit: "milliseconds",
            precision: 0,
            valueType: "int",
            maximum: 60000,
        }),
        metadata("exitMomentumMinimum", { tier: "ADVANCED" }),
        metadata("exitLiquidityQualityMinimum", { tier: "ADVANCED" }),
        metadata("exitSpreadQualityMinimum", { tier: "ADVANCED" }),
        metadata("momentumMinimumWarmupSeconds", {
            tier: "ADVANCED",
            unit: "seconds",
        }),
        metadata("absorptionVolumePercentile", {
            tier: "ADVANCED",
            unit: "normalized percentile (0.0-1.0)",
        }),
        metadata("liquidityQualityPercentile", {
            tier: "ADVANCED",
            unit: "normalized percentile (0.0-1.0)",
        }),
    ],
};

const configuration = {
    configuredRevision: 7,
    effectiveRevision: 5,
    status: "PENDING",
    source: "PARAMETER_SETTINGS",
    scope: "PAPER",
    parameterSetId: "strategy-params/PAPER",
    parameters: {
        minimumCompositeScore: 0.4,
        maximumStrategySpreadPct: 0.5,
        momentumWindowSeconds: 60,
        minimumStrategyConfidence: 0.3,
        maximumHoldMs: 3000,
        minimumHoldMs: 500,
        exitMomentumMinimum: 0.4,
        exitLiquidityQualityMinimum: 0.3,
        exitSpreadQualityMinimum: 0.3,
        momentumMinimumWarmupSeconds: 20,
        absorptionVolumePercentile: 0.9,
        liquidityQualityPercentile: 0.9,
    },
};

const effective = {
    configuredRevision: 7,
    effectiveRevision: 5,
    parameters: {
        ...configuration.parameters,
        minimumCompositeScore: 0.34,
    },
};

const runtime = {
    runtimeSnapshotAvailable: true,
    effectiveRevision: 4,
    featureContract: "TIME_SYMBOL_NORMALIZED_V1",
    capturedAt: "2026-01-01T00:00:00.000000Z",
    parameters: { minimumCompositeScore: 0.3 },
};

test("schema split exposes exactly 5 primary and 7 advanced parameters", () => {
    assert.equal(countPrimaryParameters(schema), 5);
    assert.equal(countAdvancedParameters(schema), 7);
    const split = splitSchema(schema);
    assert.equal(split.primary.length, 5);
    assert.equal(split.advanced.length, 7);
});

test("advanced parameters are grouped into the four canonical groups", () => {
    const groups = buildAdvancedGroups(schema, {
        configured: configuration,
        effective,
        runtime,
    });
    assert.deepEqual(
        groups.map((group) => group.id),
        ADVANCED_PARAMETER_GROUPS.map((group) => group.id),
    );
    assert.equal(
        groups.reduce((total, group) => total + group.rows.length, 0),
        7,
    );
    for (const group of groups) {
        assert.ok(group.rows.length > 0, group.id);
    }
});

test("configured, effective and runtime values stay distinct", () => {
    const rows = buildPrimaryRows(schema, {
        configured: configuration,
        effective,
        runtime,
    });
    const composite = rows.find(
        (row) => row.name === "minimumCompositeScore",
    );
    assert.equal(composite.configuredValue, 0.4);
    assert.equal(composite.effectiveValue, 0.34);
    assert.equal(composite.runtimeValue, 0.3);
    assert.equal(composite.configuredDisplay, "0.40");
    assert.equal(composite.effectiveDisplay, "0.34");
    assert.equal(composite.runtimeDisplay, "0.30");
    assert.equal(composite.status, "PENDING");
});

test("units are displayed including percent for maximumStrategySpreadPct", () => {
    const rows = buildPrimaryRows(schema, {
        configured: configuration,
        effective,
        runtime,
    });
    const spread = rows.find(
        (row) => row.name === "maximumStrategySpreadPct",
    );
    assert.equal(spread.unitSymbol, "%");
    assert.match(spread.configuredDisplay, /%$/);
    assert.equal(spread.configuredDisplay, "0.50 %");
    const hold = rows.find((row) => row.name === "maximumHoldMs");
    assert.equal(hold.configuredDisplay, "3000 ms");
    const momentum = rows.find(
        (row) => row.name === "momentumWindowSeconds",
    );
    assert.equal(momentum.configuredDisplay, "60 s");
});

test("normalized percentile units never render a percent suffix", () => {
    assert.equal(unitSymbol("normalized percentile (0.0-1.0)"), "");
    const absorption = metadata("absorptionVolumePercentile", {
        unit: "normalized percentile (0.0-1.0)",
        minimumInclusive: false,
    });
    assert.equal(formatParameterValue(absorption, 0.9), "0.90");
    assert.equal(formatParameterValue(absorption, 0.9).includes("%"), false);
});

test("identical authority warnings are deduplicated and distinct ones preserved", () => {
    const shared = {
        code: "CONFIDENCE_EXCEEDS_COMPOSITE",
        parameter: "minimumStrategyConfidence",
        message: "minimumStrategyConfidence is greater than "
            + "minimumCompositeScore; the confidence floor may never bind",
    };
    const distinct = {
        code: "EXIT_MOMENTUM_HIGH",
        parameter: "exitMomentumMinimum",
        message: "exitMomentumMinimum is greater than 0.5 and may cause "
            + "unusually early momentum-decay exits",
    };
    assert.equal(dedupeWarnings([shared, shared, distinct]).length, 2);

    const revision = buildEffectiveRevisionModel(
        { configuredRevision: 1, effectiveRevision: 1, warnings: [shared] },
        { effectiveRevision: 1, warnings: [shared, distinct] },
        {},
    );
    assert.equal(revision.warnings.length, 2);
    assert.equal(
        revision.warnings[0].code,
        "CONFIDENCE_EXCEEDS_COMPOSITE",
    );
    assert.equal(revision.warnings[1].code, "EXIT_MOMENTUM_HIGH");
});

test("frontend validation is convenience only and uses backend ranges", () => {
    assert.equal(
        validateDraftValue(metadata("x"), 0.5),
        null,
    );
    assert.match(validateDraftValue(metadata("x"), 2), />= 0|<= 1/);
    assert.match(
        validateDraftValue(
            metadata("spread", {
                unit: "percent (0-100 scale)",
                minimum: 0,
                maximum: 5,
                minimumInclusive: false,
            }),
            0,
        ),
        /> 0/,
    );
    assert.equal(
        validateDraftValue(
            metadata("ms", { valueType: "int" }),
            1.5,
        ),
        "value must be an integer",
    );
});

test("LIVE writability is fail-closed for unmigrated parameters", () => {
    assert.equal(isLiveWritable("minimumCompositeScore"), true);
    assert.equal(isLiveWritable("maximumStrategySpreadPct"), false);
    assert.equal(isLiveWritable("momentumWindowSeconds"), false);
    assert.equal(isLiveWritable("absorptionVolumePercentile"), false);
    assert.equal(LIVE_WRITABLE_PARAMETER_NAMES.length, 7);
});

test("configuration payload adds confirmLive only for LIVE scope", () => {
    const paper = buildConfigurationPayload({
        scope: "PAPER",
        parameters: { minimumCompositeScore: 0.4 },
        expectedRevision: 7,
    });
    assert.deepEqual(paper, {
        scope: "PAPER",
        parameters: { minimumCompositeScore: 0.4 },
        expectedRevision: 7,
    });
    const live = buildConfigurationPayload({
        scope: "LIVE",
        parameters: { minimumCompositeScore: 0.4 },
        expectedRevision: 7,
        confirmLive: true,
    });
    assert.equal(live.confirmLive, true);
    assert.equal(live.scope, "LIVE");
});

test("scope selector never changes the bot mode", async () => {
    const calls = [];
    const api = {
        updateConfiguration: async (payload) => {
            calls.push(payload);
            return { ok: true, status: 200, body: { code: "CONFIGURATION_ACCEPTED" } };
        },
    };
    await performSave({
        scope: "LIVE",
        parameters: { minimumCompositeScore: 0.4 },
        expectedRevision: 7,
        confirmLive: true,
        api,
    });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].scope, "LIVE");
    assert.equal(calls[0].confirmLive, true);
    assert.equal("mode" in calls[0], false);
    assert.equal("start" in calls[0], false);
});

test("PAPER save returns success without confirmLive", async () => {
    const result = await performSave({
        scope: "PAPER",
        parameters: { minimumCompositeScore: 0.4 },
        expectedRevision: 7,
        api: {
            updateConfiguration: async () => ({
                ok: true,
                status: 200,
                body: { code: "CONFIGURATION_ACCEPTED", warnings: [] },
            }),
        },
    });
    assert.equal(result.ok, true);
    assert.equal(result.status, 200);
});

test("409 conflict and 422 validation are surfaced without throwing", async () => {
    const conflict = await performSave({
        scope: "PAPER",
        parameters: {},
        expectedRevision: 7,
        api: {
            updateConfiguration: async () => ({
                ok: false,
                status: 409,
                body: {
                    code: "REVISION_CONFLICT",
                    configuredRevision: 8,
                },
            }),
        },
    });
    assert.equal(conflict.ok, false);
    assert.equal(conflict.status, 409);
    assert.equal(conflict.code, "REVISION_CONFLICT");
    assert.equal(conflict.body.configuredRevision, 8);

    const invalid = await performSave({
        scope: "PAPER",
        parameters: {},
        expectedRevision: 7,
        api: {
            updateConfiguration: async () => ({
                ok: false,
                status: 422,
                body: { code: "INVALID_CONFIGURATION" },
            }),
        },
    });
    assert.equal(invalid.ok, false);
    assert.equal(invalid.status, 422);
    assert.equal(invalid.code, "INVALID_CONFIGURATION");
});

test("runtime context is read-only context mirroring", () => {
    const context = buildRuntimeContext(
        {
            symbol: "BTCUSDT",
            timeframe: "1m",
            mode: "paper",
            sl_percent: 1,
            tp_percent: 2,
            trailingStop: true,
        },
        configuration,
        runtime,
    );
    assert.equal(context.symbol, "BTCUSDT");
    assert.equal(context.timeframe, "1m");
    assert.equal(context.mode, "paper");
    assert.equal(context.parameterSetId, "strategy-params/PAPER");
    assert.equal(context.scope, "PAPER");
    assert.equal(context.source, "PARAMETER_SETTINGS");
    assert.equal(context.featureContract, "TIME_SYMBOL_NORMALIZED_V1");
    assert.equal(context.sl, "1");
    assert.equal(context.tp, "2");
    assert.equal(context.trailingStop, "ON");
    assert.equal(context.aiDecision, "OFF");
    assert.equal(context.aiStatus, "NOT_INSTALLED");
    assert.equal(context.aiAuthority, "NONE");
});

test("effective revision model distinguishes configured/effective/runtime", () => {
    const model = buildEffectiveRevisionModel(
        configuration,
        effective,
        runtime,
    );
    assert.equal(model.configuredRevision, 7);
    assert.equal(model.effectiveRevision, 5);
    assert.equal(model.runtimeRevision, 4);
    assert.equal(model.pending, true);
    assert.equal(model.runtimeAvailable, true);
    assert.equal(model.capturedAt, "2026-01-01T00:00:00.000000Z");
});

test("effective revision model tracks the promotion transition", () => {
    const promotedConfiguration = {
        ...configuration,
        configuredRevision: 5,
        effectiveRevision: 5,
        status: "ACTIVE",
        pending: false,
    };
    const promotedEffective = { ...effective, effectiveRevision: 5 };

    // Promotion is not the same as runtime observation: before the runtime
    // consumes R5 the runtime revision must not be claimed.
    const beforeRuntime = buildEffectiveRevisionModel(
        promotedConfiguration,
        promotedEffective,
        { runtimeSnapshotAvailable: false, parameters: {} },
    );
    assert.equal(beforeRuntime.pending, false);
    assert.equal(beforeRuntime.status, "ACTIVE");
    assert.equal(beforeRuntime.runtimeAvailable, false);
    assert.equal(beforeRuntime.runtimeRevision, null);

    const afterRuntime = buildEffectiveRevisionModel(
        promotedConfiguration,
        promotedEffective,
        {
            runtimeSnapshotAvailable: true,
            effectiveRevision: 5,
            capturedAt: "2026-01-02T00:00:00.000000Z",
            parameters: { minimumCompositeScore: 0.4 },
        },
    );
    assert.equal(afterRuntime.runtimeRevision, 5);
    assert.equal(afterRuntime.pending, false);
});

test("effective revision model reports NO_RUNTIME_SNAPSHOT explicitly", () => {
    const model = buildEffectiveRevisionModel(configuration, effective, {
        runtimeSnapshotAvailable: false,
        parameters: {},
    });
    assert.equal(model.runtimeAvailable, false);
    assert.equal(model.runtimeRevision, null);
});

test("formatParameterValue never fabricates a value", () => {
    assert.equal(formatParameterValue(metadata("x"), null), "—");
    assert.equal(formatParameterValue(metadata("x"), undefined), "—");
    assert.equal(formatParameterValue(metadata("x"), "bad"), "—");
    assert.equal(formatParameterValue(metadata("x"), 0), "0");
});

/* =================================================
   Canonical serialization contract.

   The DOM input always yields a string; the outgoing payload must carry the
   canonical JSON type declared by the schema valueType. Invalid input must
   remain detectable and is never silently coerced to 0/NaN/null.
================================================= */

const integerMetadata = metadata("maximumHoldMs", {
    unit: "milliseconds",
    precision: 0,
    valueType: "int",
    minimum: 100,
    maximum: 60000,
});
const floatMetadata = metadata("minimumCompositeScore");
const booleanMetadata = metadata("flag", { valueType: "bool" });

test("TEST A — INTEGER edit serializes as a JSON number", () => {
    const value = normalizeParameterValue(integerMetadata, "30000");
    assert.equal(value, 30000);
    assert.equal(typeof value, "number");
    assert.notEqual(value, "30000");

    const payload = buildConfigurationPayload({
        scope: "PAPER",
        parameters: { maximumHoldMs: "30000" },
        expectedRevision: 1,
        schema,
    });
    assert.equal(payload.parameters.maximumHoldMs, 30000);
    assert.equal(typeof payload.parameters.maximumHoldMs, "number");
});

test("TEST B — INTEGER decimal is never silently truncated", () => {
    const value = normalizeParameterValue(integerMetadata, "3.5");
    assert.equal(value, "3.5");
    assert.equal(typeof value, "string");
    // Frontend validation already blocks the mutation before it is sent.
    assert.equal(
        validateDraftValue(integerMetadata, "3.5"),
        "value must be an integer",
    );
});

test("TEST C — FLOAT edit serializes as a JSON number preserving decimals", () => {
    const value = normalizeParameterValue(floatMetadata, "0.45");
    assert.equal(value, 0.45);
    assert.equal(typeof value, "number");
});

test("TEST D — BOOLEAN contract never sends strings", () => {
    assert.equal(normalizeParameterValue(booleanMetadata, "true"), true);
    assert.equal(normalizeParameterValue(booleanMetadata, "false"), false);
    assert.equal(typeof normalizeParameterValue(booleanMetadata, "true"), "boolean");
});

test("TEST E — empty numeric input never becomes 0", () => {
    assert.equal(normalizeParameterValue(integerMetadata, ""), "");
    assert.equal(normalizeParameterValue(floatMetadata, "   "), "   ");
    const payload = buildConfigurationPayload({
        scope: "PAPER",
        parameters: { maximumHoldMs: "" },
        expectedRevision: 1,
        schema,
    });
    assert.equal(payload.parameters.maximumHoldMs, "");
});

test("TEST F — non-finite input never becomes an accepted payload", () => {
    assert.equal(normalizeParameterValue(floatMetadata, "abc"), "abc");
    assert.equal(normalizeParameterValue(integerMetadata, "Infinity"), "Infinity");
    const normalized = normalizeDraftForSave(schema, {
        minimumCompositeScore: "abc",
    });
    assert.equal(normalized.minimumCompositeScore, "abc");
    assert.equal(Number.isFinite(normalized.minimumCompositeScore), false);
});

test("TEST G — full draft mixes canonical types across all fields", () => {
    const draft = {
        minimumCompositeScore: "0.34",
        maximumStrategySpreadPct: "0.5",
        momentumWindowSeconds: "60",
        minimumStrategyConfidence: "0.23",
        maximumHoldMs: "30000",
        minimumHoldMs: "500",
        exitMomentumMinimum: "0.4",
        exitLiquidityQualityMinimum: "0.3",
        exitSpreadQualityMinimum: "0.3",
        momentumMinimumWarmupSeconds: "20",
        absorptionVolumePercentile: "0.9",
        liquidityQualityPercentile: "0.9",
    };
    const normalized = normalizeDraftForSave(schema, draft);
    for (const [name, value] of Object.entries(normalized)) {
        assert.equal(typeof value, "number", name);
    }
    assert.equal(normalized.maximumHoldMs, 30000);
    assert.equal(Number.isInteger(normalized.maximumHoldMs), true);
    assert.equal(normalized.maximumHoldMs, 30000);
    assert.equal(Number.isInteger(normalized.minimumHoldMs), true);
    assert.equal(normalized.minimumCompositeScore, 0.34);
    assert.equal(normalized.momentumWindowSeconds, 60);
});

test("TEST H — PAPER payload serialization carries canonical types", () => {
    const payload = buildConfigurationPayload({
        scope: "PAPER",
        parameters: {
            ...configuration.parameters,
            maximumHoldMs: "30000",
        },
        expectedRevision: configuration.configuredRevision,
        schema,
    });
    assert.equal(payload.scope, "PAPER");
    assert.equal(payload.confirmLive, undefined);
    assert.equal(typeof payload.parameters.maximumHoldMs, "number");
    assert.equal(payload.parameters.maximumHoldMs, 30000);
    for (const value of Object.values(payload.parameters)) {
        assert.equal(typeof value, "number");
    }
});

test("TEST I — LIVE payload serialization uses the same shared contract", () => {
    const payload = buildConfigurationPayload({
        scope: "LIVE",
        parameters: { minimumCompositeScore: "0.4", maximumHoldMs: "30000" },
        expectedRevision: 5,
        confirmLive: true,
        schema,
    });
    assert.equal(payload.scope, "LIVE");
    assert.equal(payload.confirmLive, true);
    assert.equal(typeof payload.parameters.minimumCompositeScore, "number");
    assert.equal(typeof payload.parameters.maximumHoldMs, "number");
    assert.equal(payload.parameters.maximumHoldMs, 30000);
});

test("normalization is schema-driven and leaves unknown parameters untouched", () => {
    const normalized = normalizeDraftForSave(schema, {
        maximumHoldMs: "30000",
        notInSchema: "1.5",
    });
    assert.equal(normalized.maximumHoldMs, 30000);
    assert.equal(normalized.notInSchema, "1.5");
    // Without schema metadata the payload is forwarded unchanged.
    const passthrough = normalizeDraftForSave(null, { maximumHoldMs: "30000" });
    assert.equal(passthrough.maximumHoldMs, "30000");
});

test("TEST J — canonical INVALID_CONFIGURATION detail is preserved for the UI", async () => {
    const result = await performSave({
        scope: "PAPER",
        parameters: { maximumHoldMs: "30000" },
        expectedRevision: 1,
        schema,
        api: {
            updateConfiguration: async () => ({
                ok: false,
                status: 422,
                body: {
                    code: "INVALID_CONFIGURATION",
                    message: "configuration failed canonical validation",
                    validation: {
                        isValid: false,
                        errors: [{
                            code: "INVALID_TYPE",
                            parameter: "maximumHoldMs",
                            message: "maximumHoldMs must be a finite numeric value, got str",
                        }],
                        warnings: [],
                    },
                },
            }),
        },
    });
    assert.equal(result.ok, false);
    assert.equal(result.status, 422);
    assert.equal(result.code, "INVALID_CONFIGURATION");
    assert.equal(
        result.body.validation.errors[0].parameter,
        "maximumHoldMs",
    );
    assert.match(
        result.body.validation.errors[0].message,
        /finite numeric value/,
    );
});

test("TEST K — revision conflict classification is preserved", async () => {
    const result = await performSave({
        scope: "PAPER",
        parameters: { maximumHoldMs: 30000 },
        expectedRevision: 1,
        schema,
        api: {
            updateConfiguration: async () => ({
                ok: false,
                status: 409,
                body: { code: "REVISION_CONFLICT", configuredRevision: 2 },
            }),
        },
    });
    assert.equal(result.ok, false);
    assert.equal(result.status, 409);
    assert.equal(result.code, "REVISION_CONFLICT");
});

test("TEST L — authentication failure classification is preserved", async () => {
    const result = await performSave({
        scope: "PAPER",
        parameters: { maximumHoldMs: 30000 },
        expectedRevision: 1,
        schema,
        api: {
            updateConfiguration: async () => ({
                ok: false,
                status: 403,
                body: { status: "UNAUTHENTICATED" },
            }),
        },
    });
    assert.equal(result.ok, false);
    assert.equal(result.status, 403);
    assert.equal(result.body.status, "UNAUTHENTICATED");
});
