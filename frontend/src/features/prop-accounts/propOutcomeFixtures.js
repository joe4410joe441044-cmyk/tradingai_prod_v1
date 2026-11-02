import generatedFixtures from "./generatedSyntheticOutcomes.json" with { type: "json" };

export const PROP_OUTCOME_FIXTURE_SCHEMA = "tradingai-prop-synthetic-outcome-fixtures/v1";
export const PROP_OUTCOME_CONTEXT_SCHEMA = "tradingai-prop-outcome-read-only-context/v1";
const DECIMAL = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const PURPOSES = new Set(["READ_ONLY_CURRENT", "HISTORICAL_AS_OF", "RETROACTIVE_ANALYSIS"]);
const FRESHNESS_STATES = new Set(["FRESH", "STALE", "UNKNOWN"]);
const COMPLETENESS_STATES = new Set(["COMPLETE", "PARTIAL", "UNKNOWN"]);
const STATES = new Set(["PASS", "BLOCK", "UNKNOWN", "NOT_APPLICABLE"]);
const invalid = (errorCode) => Object.freeze({ status: "INVALID", errorCode });
const isText = (value) => typeof value === "string" && value.length > 0;
const isTextArray = (value) => Array.isArray(value) && value.every(isText);

function matchesExpectedScope(scope, expectedScope) {
    return expectedScope && typeof expectedScope === "object"
        && scope?.accountId === expectedScope.accountId
        && scope?.executionMode === expectedScope.executionMode
        && scope?.executionVenue === expectedScope.executionVenue
        && (expectedScope.phase === undefined || scope?.phase === expectedScope.phase);
}

export function normalizeOutcomeScenario(value, expectedScope) {
    if (!value || typeof value !== "object") return invalid("OUTCOME_SCENARIO_MISSING");
    if (value.rejection) {
        if (value.rejection.outcome !== null || !value.rejection.errorCode) return invalid("INVALID_PRE_EVALUATION_REJECTION");
        return Object.freeze({ status: "PRE_EVALUATION_REJECTED", id: value.id, label: value.label, rejection: Object.freeze({ ...value.rejection }) });
    }
    const outcome = value.outcome;
    if (outcome?.schemaVersion !== PROP_OUTCOME_CONTEXT_SCHEMA) return invalid("UNSUPPORTED_OUTCOME_SCHEMA");
    if (outcome.synthetic !== true || !PURPOSES.has(outcome.purpose)) return invalid("INVALID_OUTCOME_PURPOSE");
    if (!matchesExpectedScope(outcome.accountScope, expectedScope)) return invalid("OUTCOME_ACCOUNT_SCOPE_MISMATCH");
    if (!Number.isInteger(outcome.accountScope.identityRevision) || outcome.accountScope.identityRevision < 1
        || ![outcome.accountScope.program, outcome.accountScope.planId, outcome.accountScope.phase, outcome.accountScope.currency].every(isText)) return invalid("INVALID_OUTCOME_ACCOUNT_SCOPE");
    if (!UTC_TIMESTAMP.test(outcome.evaluatedAt) || !UTC_TIMESTAMP.test(outcome.knowledgeCutoffAt)) return invalid("INVALID_OUTCOME_TIMESTAMPS");
    if (outcome.authority?.executionAuthorityGranted !== false || outcome.authority?.runtimeReady !== false || outcome.authority?.tradeReady !== false) return invalid("OUTCOME_AUTHORITY_NOT_DISABLED");
    if (outcome.provenanceValidation?.status !== "STRICTLY_VALIDATED"
        || outcome.provenanceValidation?.authenticityGuaranteed !== false
        || outcome.provenanceValidation?.realAccountEligibilityGuaranteed !== false) return invalid("OUTCOME_NOT_STRICTLY_VALIDATED");
    if (!COMPLETENESS_STATES.has(outcome.coverage?.completeness)
        || typeof outcome.coverage?.operationallyComplete !== "boolean"
        || !isTextArray(outcome.coverage?.unknownReasonCodes)) return invalid("INVALID_OUTCOME_COVERAGE");
    if (!FRESHNESS_STATES.has(outcome.calculation?.freshnessState)
        || !STATES.has(outcome.calculation?.overallState)
        || !isTextArray(outcome.calculation?.blockingRuleCodes)
        || !isTextArray(outcome.calculation?.unknownRuleCodes)) return invalid("INVALID_OUTCOME_CALCULATION");
    const results = outcome.calculation?.ruleResults;
    if (!Array.isArray(results) || !results.every((result) => (
        typeof result.ruleCode === "string" && STATES.has(result.state)
        && [result.actual, result.threshold, result.headroom].every((amount) => amount === null || DECIMAL.test(amount))
        && typeof result.unit === "string"
    ))) return invalid("INVALID_RULE_RESULTS");
    return Object.freeze({ status: "READY", id: value.id, label: value.label, outcome });
}

export const PROP_OUTCOME_SCENARIOS = Object.freeze(
    generatedFixtures?.schemaVersion === PROP_OUTCOME_FIXTURE_SCHEMA
        && generatedFixtures?.projectionSchemaVersion === PROP_OUTCOME_CONTEXT_SCHEMA
        ? generatedFixtures.scenarios.map((scenario) => Object.freeze(scenario))
        : [],
);

export function getOutcomeScenario(scenarioId, expectedScope) {
    return normalizeOutcomeScenario(PROP_OUTCOME_SCENARIOS.find(({ id }) => id === scenarioId), expectedScope);
}
