const BOT_STATES = new Set([
    "NOT_CONNECTED",
    "STOPPED",
    "RUNNING",
    "UNKNOWN",
]);
const LOOP_STATES = new Set([
    "NOT_CONNECTED",
    "STOPPED",
    "STARTING",
    "RUNNING",
    "STOPPING",
    "UNKNOWN",
]);
const EMERGENCY_STATES = new Set([
    "READY",
    "PROCESSING",
    "LOCKED",
    "ACTION_REQUIRED",
    "UNKNOWN",
]);
const FRESHNESS_STATES = new Set(["FRESH", "STALE", "UNKNOWN"]);

const record = (value) => (
    value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {}
);
const strictBoolean = (value, field, warnings) => {
    if (value === true || value === false) return value;
    warnings.push(`INVALID_BOOLEAN:${field}`);
    return null;
};
const optionalText = (value, field, warnings) => {
    if (value === null || value === undefined) return null;
    if (typeof value === "string" && value.trim()) return value.trim();
    warnings.push(`INVALID_TEXT:${field}`);
    return null;
};
const enumValue = (value, allowed, field, warnings) => {
    if (typeof value === "string" && allowed.has(value)) return value;
    warnings.push(`UNKNOWN_ENUM:${field}`);
    return "UNKNOWN";
};
const timestamp = (value, field, warnings) => {
    if (value === null || value === undefined) return null;
    if (
        typeof value === "string"
        && value.trim()
        && Number.isFinite(Date.parse(value))
    ) {
        return value;
    }
    warnings.push(`INVALID_TIMESTAMP:${field}`);
    return null;
};

export function normalizeAdvisorRuntimeResponse(raw) {
    const root = record(raw);
    const bot = record(root.bot);
    const operation = record(root.operation);
    const safety = record(root.safety);
    const runtime = record(root.runtime);
    const warnings = Array.isArray(root.warnings)
        ? root.warnings.filter((value) => typeof value === "string")
        : [];

    if (
        !Array.isArray(root.warnings)
        || warnings.length !== root.warnings.length
    ) {
        warnings.push("WARNINGS_INVALID");
    }

    return {
        bot: {
            state: enumValue(bot.state, BOT_STATES, "bot.state", warnings),
            mode: optionalText(bot.mode, "bot.mode", warnings),
            exchange: optionalText(bot.exchange, "bot.exchange", warnings),
            symbol: optionalText(bot.symbol, "bot.symbol", warnings),
        },
        operation: {
            loopEnabled: strictBoolean(
                operation.loopEnabled,
                "operation.loopEnabled",
                warnings,
            ),
            loopState: enumValue(
                operation.loopState,
                LOOP_STATES,
                "operation.loopState",
                warnings,
            ),
            autoTradeEnabled: strictBoolean(
                operation.autoTradeEnabled,
                "operation.autoTradeEnabled",
                warnings,
            ),
        },
        safety: {
            emergencyLocked: strictBoolean(
                safety.emergencyLocked,
                "safety.emergencyLocked",
                warnings,
            ),
            emergencyState: enumValue(
                safety.emergencyState,
                EMERGENCY_STATES,
                "safety.emergencyState",
                warnings,
            ),
            dryRun: strictBoolean(safety.dryRun, "safety.dryRun", warnings),
            realOrderAllowed: strictBoolean(
                safety.realOrderAllowed,
                "safety.realOrderAllowed",
                warnings,
            ),
        },
        runtime: {
            capturedAt: timestamp(
                runtime.capturedAt,
                "runtime.capturedAt",
                warnings,
            ),
            sourceUpdatedAt: timestamp(
                runtime.sourceUpdatedAt,
                "runtime.sourceUpdatedAt",
                warnings,
            ),
            freshness: enumValue(
                runtime.freshness,
                FRESHNESS_STATES,
                "runtime.freshness",
                warnings,
            ),
        },
        warnings: [...new Set(warnings)],
    };
}
