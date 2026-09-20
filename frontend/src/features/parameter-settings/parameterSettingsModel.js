/* =================================================
   PARAMETER SETTINGS view model (pure, testable).

   This module contains no React and no network.  It maps the canonical
   backend schema and the CONFIGURED / EFFECTIVE / RUNTIME reads into
   deterministic presentation rows.  The backend registry remains the single
   source of range/unit metadata; the frontend never redefines ranges.
================================================= */

export const PARAMETER_SETTINGS_SCOPE = Object.freeze({
    PAPER: "PAPER",
    LIVE: "LIVE",
});

export const PARAMETER_SETTINGS_TIER = Object.freeze({
    PRIMARY: "PRIMARY",
    ADVANCED: "ADVANCED",
});

export const PRIMARY_PARAMETER_NAMES = Object.freeze([
    "minimumCompositeScore",
    "maximumStrategySpreadPct",
    "momentumWindowSeconds",
    "minimumStrategyConfidence",
    "maximumHoldMs",
]);

export const ADVANCED_PARAMETER_NAMES = Object.freeze([
    "minimumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
    "momentumMinimumWarmupSeconds",
    "absorptionVolumePercentile",
    "liquidityQualityPercentile",
]);

export const LIVE_WRITABLE_PARAMETER_NAMES = Object.freeze([
    "minimumCompositeScore",
    "minimumStrategyConfidence",
    "maximumHoldMs",
    "minimumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
]);

export const ADVANCED_PARAMETER_GROUPS = Object.freeze([
    {
        id: "HOLDING_TIME",
        labelEn: "Holding-Time",
        labelJa: "保有時間",
        parameters: ["minimumHoldMs"],
    },
    {
        id: "EXIT_DETERIORATION",
        labelEn: "Exit-Deterioration",
        labelJa: "決済劣化",
        parameters: [
            "exitMomentumMinimum",
            "exitLiquidityQualityMinimum",
            "exitSpreadQualityMinimum",
        ],
    },
    {
        id: "MOMENTUM_HORIZON",
        labelEn: "Momentum-Horizon",
        labelJa: "モメンタム・ホライズン",
        parameters: ["momentumMinimumWarmupSeconds"],
    },
    {
        id: "DETECTOR_SENSITIVITY",
        labelEn: "Detector-Sensitivity",
        labelJa: "検出感度",
        parameters: [
            "absorptionVolumePercentile",
            "liquidityQualityPercentile",
        ],
    },
]);

export const normalizeScope = (value) => {
    const normalized = String(value ?? "").trim().toUpperCase();
    if (normalized === PARAMETER_SETTINGS_SCOPE.LIVE) {
        return PARAMETER_SETTINGS_SCOPE.LIVE;
    }
    if (normalized === PARAMETER_SETTINGS_SCOPE.PAPER) {
        return PARAMETER_SETTINGS_SCOPE.PAPER;
    }
    return PARAMETER_SETTINGS_SCOPE.PAPER;
};

export const isLiveWritable = (name) => (
    LIVE_WRITABLE_PARAMETER_NAMES.includes(name)
);

export const isLiveScope = (scope) => normalizeScope(scope) === (
    PARAMETER_SETTINGS_SCOPE.LIVE
);

const schemaParameters = (schema) => (
    Array.isArray(schema?.parameters) ? schema.parameters : []
);

export const findSchemaParameter = (schema, name) => (
    schemaParameters(schema).find((entry) => entry?.name === name) ?? null
);

export const splitSchema = (schema) => {
    const primary = [];
    const advanced = [];
    for (const entry of schemaParameters(schema)) {
        if (entry?.tier === PARAMETER_SETTINGS_TIER.PRIMARY) {
            primary.push(entry);
        } else if (entry?.tier === PARAMETER_SETTINGS_TIER.ADVANCED) {
            advanced.push(entry);
        }
    }
    return { primary, advanced };
};

export const unitSymbol = (unit) => {
    const value = String(unit ?? "").toLowerCase();
    // A normalized percentile rank (0.0-1.0) is not a percent. Check it
    // before the generic "percent" match so 0.90 is never shown as "0.90 %".
    if (value.includes("percentile")) return "";
    if (value.includes("percent")) return "%";
    if (value.includes("millisecond")) return "ms";
    if (value.includes("seconds")) return "s";
    return "";
};

const displayPrecision = (metadata) => {
    const unit = String(metadata?.unit ?? "").toLowerCase();
    if (metadata?.valueType === "int" || unit.includes("millisecond")) {
        return 0;
    }
    return 2;
};

export const formatParameterValue = (metadata, value) => {
    if (value === null || value === undefined || value === "") {
        return "—";
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return "—";
    }
    const precision = displayPrecision(metadata);
    const text = Number.isInteger(numeric)
        ? String(numeric)
        : numeric.toFixed(precision);
    const symbol = unitSymbol(metadata?.unit);
    return symbol ? `${text} ${symbol}` : text;
};

export const describeParameterConstraint = (metadata) => {
    if (!metadata) return null;
    const lower = metadata.minimumInclusive === false ? ">" : ">=";
    if (metadata.maximum == null) {
        return `${lower} ${metadata.minimum} ${metadata.unit ?? ""}`.trim();
    }
    const upper = metadata.maximumInclusive === false ? "<" : "<=";
    return `${lower} ${metadata.minimum} and ${upper} ${metadata.maximum} ${metadata.unit ?? ""}`.trim();
};

export const validateDraftValue = (metadata, value) => {
    if (value === "" || value === null || value === undefined) {
        return "value is required";
    }
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return "value must be a finite number";
    }
    if (metadata?.valueType === "int" && !Number.isInteger(numeric)) {
        return "value must be an integer";
    }
    const aboveMinimum = metadata?.minimumInclusive === false
        ? numeric > metadata.minimum
        : numeric >= metadata.minimum;
    if (!aboveMinimum) {
        return `must be ${metadata?.minimumInclusive === false ? ">" : ">="} ${metadata.minimum}`;
    }
    const belowMaximum = metadata?.maximum == null || (metadata.maximumInclusive === false
        ? numeric < metadata.maximum
        : numeric <= metadata.maximum);
    if (!belowMaximum) {
        return `must be ${metadata?.maximumInclusive === false ? "<" : "<="} ${metadata.maximum}`;
    }
    return null;
};

export const buildParameterRow = (metadata, sources = {}) => {
    const configured = sources.configured?.parameters?.[metadata.name];
    const effective = sources.effective?.parameters?.[metadata.name];
    const runtime = sources.runtime?.parameters?.[metadata.name];
    const configuredRevision = sources.configured?.configuredRevision;
    const effectiveRevision = sources.effective?.effectiveRevision;
    const pending = (
        Number.isInteger(configuredRevision)
        && Number.isInteger(effectiveRevision)
        && configuredRevision > effectiveRevision
    );
    return {
        name: metadata.name,
        labelEn: metadata.labelEn,
        labelJa: metadata.labelJa,
        unit: metadata.unit,
        unitSymbol: unitSymbol(metadata.unit),
        minimum: metadata.minimum,
        maximum: metadata.maximum,
        minimumInclusive: metadata.minimumInclusive,
        maximumInclusive: metadata.maximumInclusive,
        precision: metadata.precision,
        couplingGroup: metadata.couplingGroup,
        tier: metadata.tier,
        description: metadata.description,
        editable: metadata.editable !== false,
        liveWritable: isLiveWritable(metadata.name),
        liveLocked: !isLiveWritable(metadata.name),
        configuredValue: configured,
        effectiveValue: effective,
        runtimeValue: runtime,
        configuredDisplay: formatParameterValue(metadata, configured),
        effectiveDisplay: formatParameterValue(metadata, effective),
        runtimeDisplay: formatParameterValue(metadata, runtime),
        status: pending
            ? "PENDING"
            : (effective === undefined ? "UNKNOWN" : "EFFECTIVE"),
        source: sources.configured?.source ?? null,
        constraint: describeParameterConstraint(metadata),
    };
};

export const buildParameterRows = (schema, sources = {}) => (
    schemaParameters(schema).map((metadata) => (
        buildParameterRow(metadata, sources)
    ))
);

export const buildPrimaryRows = (schema, sources = {}) => (
    splitSchema(schema).primary.map((metadata) => (
        buildParameterRow(metadata, sources)
    ))
);

export const buildAdvancedGroups = (schema, sources = {}) => (
    ADVANCED_PARAMETER_GROUPS.map((group) => ({
        ...group,
        rows: group.parameters
            .map((name) => findSchemaParameter(schema, name))
            .filter(Boolean)
            .map((metadata) => buildParameterRow(metadata, sources)),
    }))
);

export const countPrimaryParameters = (schema) => (
    splitSchema(schema).primary.length
);

export const countAdvancedParameters = (schema) => (
    splitSchema(schema).advanced.length
);

/* The canonical schema metadata (valueType) is the single authority for the
   serialized JSON type. DOM inputs always yield strings, so the draft is
   normalized to the canonical type before it is placed on the wire. Invalid
   input is preserved verbatim rather than coerced (never to 0/NaN/null) so it
   remains detectable and the backend canonical validator stays authoritative. */
const canonicalValueType = (metadata) => {
    const valueType = metadata?.valueType;
    return typeof valueType === "string" ? valueType.trim().toLowerCase() : null;
};

export const normalizeParameterValue = (metadata, value) => {
    if (value === null || value === undefined) return value;
    if (typeof value === "string" && value.trim() === "") return value;

    const valueType = canonicalValueType(metadata);
    if (valueType === "int" || valueType === "float") {
        const numeric = typeof value === "number" ? value : Number(value);
        if (!Number.isFinite(numeric)) return value;
        if (valueType === "int") {
            return Number.isInteger(numeric) ? numeric : value;
        }
        return numeric;
    }
    if (valueType === "bool" || valueType === "boolean") {
        if (typeof value === "boolean") return value;
        if (value === "true" || value === 1 || value === "1") return true;
        if (value === "false" || value === 0 || value === "0") return false;
        return value;
    }
    return value;
};

export const normalizeDraftForSave = (schema, parameters = {}) => {
    const normalized = { ...(parameters ?? {}) };
    for (const metadata of schemaParameters(schema)) {
        if (!(metadata.name in normalized)) continue;
        normalized[metadata.name] = normalizeParameterValue(
            metadata,
            normalized[metadata.name],
        );
    }
    return normalized;
};

export const buildConfigurationPayload = ({
    scope,
    parameters,
    expectedRevision,
    confirmLive = false,
    schema = null,
}) => {
    const payload = {
        scope: normalizeScope(scope),
        parameters: normalizeDraftForSave(schema, parameters),
        expectedRevision,
    };
    if (isLiveScope(scope)) {
        payload.confirmLive = confirmLive === true;
    }
    return payload;
};

export const buildRuntimeContext = (
    botStatus = {},
    configuration = {},
    runtime = {},
) => {
    const tradeSettings = botStatus?.tradeSettings ?? {};
    const dash = (value) => (
        value === null || value === undefined || value === ""
            ? "—"
            : String(value)
    );
    const trailing = botStatus?.trailingStop
        ?? botStatus?.trailing_stop
        ?? tradeSettings.trailing_stop;
    return {
        symbol: dash(botStatus?.symbol),
        timeframe: dash(botStatus?.timeframe ?? tradeSettings.timeframe),
        mode: dash(botStatus?.mode),
        parameterSetId: dash(configuration?.parameterSetId),
        scope: dash(configuration?.scope),
        source: dash(configuration?.source),
        featureContract: dash(runtime?.featureContract),
        aiDecision: dash(botStatus?.tradingAiMode ?? "OFF"),
        aiStatus: dash(botStatus?.tradingAiStatus ?? "NOT_INSTALLED"),
        aiAuthority: "NONE",
        sl: dash(botStatus?.sl_percent ?? tradeSettings.sl_percent),
        tp: dash(botStatus?.tp_percent ?? tradeSettings.tp_percent),
        trailingStop: trailing === true
            ? "ON"
            : (trailing === false ? "OFF" : "—"),
    };
};

export const warningKey = (warning) => (
    `${warning?.code ?? ""}|${warning?.parameter ?? ""}|${warning?.message ?? ""}`
);

/* The same cross-field warning is legitimately emitted by both the configured
   and effective authority responses. Presentation aggregates them, so dedupe
   only truly identical warnings and keep distinct warnings intact. */
export const dedupeWarnings = (warnings = []) => {
    const seen = new Set();
    const result = [];
    for (const warning of warnings) {
        const key = warningKey(warning);
        if (seen.has(key)) continue;
        seen.add(key);
        result.push(warning);
    }
    return result;
};

export const buildEffectiveRevisionModel = (
    configuration = {},
    effective = {},
    runtime = {},
) => ({
    configuredRevision: configuration?.configuredRevision ?? null,
    effectiveRevision: effective?.effectiveRevision ?? null,
    runtimeRevision: runtime?.effectiveRevision ?? null,
    scope: configuration?.scope ?? null,
    source: configuration?.source ?? null,
    status: configuration?.status ?? null,
    warnings: dedupeWarnings([
        ...(configuration?.warnings ?? []),
        ...(effective?.warnings ?? []),
    ]),
    capturedAt: runtime?.capturedAt ?? null,
    runtimeAvailable: runtime?.runtimeSnapshotAvailable === true,
    pending: (
        Number.isInteger(configuration?.configuredRevision)
        && Number.isInteger(effective?.effectiveRevision)
        && configuration.configuredRevision > effective.effectiveRevision
    ),
});

export const applyDraftChange = (draft, name, value) => ({
    ...(draft ?? {}),
    [name]: value,
});

export const draftFromConfiguration = (configuration = {}) => ({
    ...(configuration?.parameters ?? {}),
});

export const draftHasErrors = (schema, draft = {}) => {
    const errors = {};
    for (const metadata of schemaParameters(schema)) {
        if (!(metadata.name in draft)) continue;
        const message = validateDraftValue(metadata, draft[metadata.name]);
        if (message) {
            errors[metadata.name] = message;
        }
    }
    return errors;
};

export const liveWriteBlockReason = (scope, row) => {
    if (!isLiveScope(scope)) return null;
    if (row?.liveWritable) return null;
    return "LIVE_UNMIGRATED_PARAMETER_WRITE_REJECTED";
};

export const performSave = async ({
    scope,
    parameters,
    expectedRevision,
    confirmLive = false,
    schema = null,
    api,
}) => {
    if (typeof api?.updateConfiguration !== "function") {
        throw new TypeError("api.updateConfiguration is required");
    }
    const payload = buildConfigurationPayload({
        scope,
        parameters,
        expectedRevision,
        confirmLive,
        schema,
    });
    const response = await api.updateConfiguration(payload);
    if (response?.ok) {
        return {
            ok: true,
            status: response.status,
            body: response.body,
        };
    }
    return {
        ok: false,
        status: response?.status ?? 0,
        code: response?.body?.code ?? null,
        message: response?.body?.message ?? "Configuration update failed.",
        body: response?.body ?? null,
    };
};
