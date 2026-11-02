import assert from "node:assert/strict";
import test from "node:test";

import {
    PROP_OUTCOME_CONTEXT_SCHEMA,
    PROP_OUTCOME_SCENARIOS,
    getOutcomeScenario,
    normalizeOutcomeScenario,
} from "./propOutcomeFixtures.js";
import { PROP_ACCOUNT_ID } from "./propAccountsFixtures.js";

const EXPECTED_SCOPE = Object.freeze({
    accountId: PROP_ACCOUNT_ID,
    executionMode: "EXTERNAL_SIMULATION",
    executionVenue: "BYBIT_DEMO",
    phase: "CHALLENGE",
});

test("backend-generated scenarios are frontend-readable and authority-free", () => {
    assert.equal(PROP_OUTCOME_SCENARIOS.length, 6);
    for (const source of PROP_OUTCOME_SCENARIOS) {
        const scenario = getOutcomeScenario(source.id, EXPECTED_SCOPE);
        assert.ok(["READY", "PRE_EVALUATION_REJECTED"].includes(scenario.status));
        if (scenario.status === "READY") {
            assert.equal(scenario.outcome.schemaVersion, PROP_OUTCOME_CONTEXT_SCHEMA);
            assert.equal(scenario.outcome.accountScope.accountId, PROP_ACCOUNT_ID);
            assert.equal(scenario.outcome.authority.executionAuthorityGranted, false);
            assert.equal(scenario.outcome.authority.tradeReady, false);
        }
    }
});

test("PASS, BLOCK, UNKNOWN, unsupported, and target progress remain distinct", () => {
    assert.equal(getOutcomeScenario("calculation_pass", EXPECTED_SCOPE).outcome.calculation.overallState, "PASS");
    assert.equal(getOutcomeScenario("maximum_loss_block", EXPECTED_SCOPE).outcome.calculation.overallState, "BLOCK");
    assert.equal(getOutcomeScenario("required_information_unknown", EXPECTED_SCOPE).outcome.calculation.overallState, "UNKNOWN");
    assert.equal(getOutcomeScenario("unsupported_required_rule", EXPECTED_SCOPE).outcome.coverage.completeness, "PARTIAL");
    const target = getOutcomeScenario("profit_target_reached", EXPECTED_SCOPE).outcome.calculation.ruleResults.find(({ ruleCode }) => ruleCode === "PROFIT_TARGET");
    assert.equal(target.state, "PASS");
    assert.equal(target.actual, "11000");
});

test("schema, account, authority, and decimal changes fail closed", () => {
    const source = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    source.outcome.schemaVersion = "unsupported/v9";
    assert.equal(normalizeOutcomeScenario(source, EXPECTED_SCOPE).status, "INVALID");
    const account = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    assert.equal(normalizeOutcomeScenario(account, { ...EXPECTED_SCOPE, accountId: "acc_ffffffffffffffffffffffffffffffff" }).errorCode, "OUTCOME_ACCOUNT_SCOPE_MISMATCH");
    const venue = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    venue.outcome.accountScope.executionVenue = "HYRO_MCP";
    assert.equal(normalizeOutcomeScenario(venue, EXPECTED_SCOPE).errorCode, "OUTCOME_ACCOUNT_SCOPE_MISMATCH");
    const authority = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    authority.outcome.authority.tradeReady = true;
    assert.equal(normalizeOutcomeScenario(authority, EXPECTED_SCOPE).errorCode, "OUTCOME_AUTHORITY_NOT_DISABLED");
    const decimal = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    decimal.outcome.calculation.ruleResults[0].actual = "NaN";
    assert.equal(normalizeOutcomeScenario(decimal, EXPECTED_SCOPE).errorCode, "INVALID_RULE_RESULTS");
});

test("missing timestamps, freshness, or coverage never become a normal current outcome", () => {
    const missing = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    delete missing.outcome.evaluatedAt;
    assert.equal(normalizeOutcomeScenario(missing, EXPECTED_SCOPE).errorCode, "INVALID_OUTCOME_TIMESTAMPS");
    const freshness = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    delete freshness.outcome.calculation.freshnessState;
    assert.equal(normalizeOutcomeScenario(freshness, EXPECTED_SCOPE).errorCode, "INVALID_OUTCOME_CALCULATION");
    const coverage = structuredClone(PROP_OUTCOME_SCENARIOS[0]);
    delete coverage.outcome.coverage.unknownReasonCodes;
    assert.equal(normalizeOutcomeScenario(coverage, EXPECTED_SCOPE).errorCode, "INVALID_OUTCOME_COVERAGE");
});
