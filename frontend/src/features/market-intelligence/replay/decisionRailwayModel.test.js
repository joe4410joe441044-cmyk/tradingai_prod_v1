import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import { buildDecisionRailwayModel } from "./decisionRailwayModel.js";

const IDS = ["market-data", "detectors", "feature-builder", "strategy", "ai-review", "governance", "execution"];
const loaded = () => applyReplayCommand(createInitialReplayEngineState(), {
    type: C.LOAD_DATASET,
    payload: { dataset: XRP_REPLAY_FIXTURE },
});
const event = (eventType, stationId, payload = {}, extras = {}) => ({
    id: `${stationId}-${eventType}`,
    timestamp: "2026-07-20T12:00:00.000Z",
    eventType,
    stationId,
    payload,
    dataQuality: "VALID",
    ...extras,
});
const customEngine = (events, currentEvent = events.at(-1), contexts = {}) => ({
    dataset: { symbol: "BTCUSDT", exchange: "TEST", tradeMode: "PAPER" },
    replayCursor: currentEvent?.timestamp ?? null,
    projection: {
        stationContext: {
            stations: [...new Set(events.map(({ stationId }) => stationId).filter(Boolean))]
                .map((stationId) => ({ stationId, events: events.filter((item) => item.stationId === stationId) })),
        },
        visibleEvents: events,
        currentEvent,
        decisionContext: {},
        positionContext: {},
        dataQuality: "VALID",
        ...contexts,
    },
});

test("null and empty engines always return seven not-reached stations", () => {
    for (const engine of [null, {}, { projection: null }, { projection: {} }]) {
        const model = buildDecisionRailwayModel(engine);
        assert.deepEqual(model.stations.map(({ id }) => id), IDS);
        assert.equal(model.stations.every(({ status }) => status === "not_reached"), true);
        assert.equal(model.currentStationId, null);
        assert.deepEqual(model.finalDecision, {
            strategy: "—", ai: "—", aiRelation: "—", governance: "—", execution: "—",
        });
    }
});

test("fixture load starts with active market data and safe summary values", () => {
    const model = buildDecisionRailwayModel(loaded());
    assert.equal(model.currentStationId, "market-data");
    assert.equal(model.stations[0].status, "active");
    assert.equal(model.stations[0].secondaryValues.some(
        ({ label, value }) => label === "Symbol" && value === "XRPUSDTM",
    ), true);
    assert.equal(model.stations[1].status, "not_reached");
    assert.equal(model.dataQuality, "VALID");
});

test("detector and feature stations expose only compact recognized values", () => {
    const detector = event("DETECTOR_SIGNAL", "detector", {
        iceberg: true, spoofing: false, absorption: "DETECTED", fakePressure: 0.2,
        momentum: 0.64, liquidity: 0.72, huge: { ignored: true },
    });
    const feature = event("FEATURES_BUILT", "feature-builder", {
        featureCount: 12, normalized: true, featureQuality: "VALID", keyFeature: "momentum",
        vector: Array(100).fill(1),
    });
    const model = buildDecisionRailwayModel(customEngine([detector, feature]));
    assert.equal(model.stations[1].secondaryValues.length <= 6, true);
    assert.equal(model.stations[2].primaryValue, "12");
    assert.equal(model.stations[2].secondaryValues.some(({ label }) => label === "Quality"), true);
});

test("strategy and AI relation handles agreement, downgrade, HOLD, and conflict", () => {
    const relation = (strategy, ai) => {
        const strategyEvent = event("STRATEGY_DECISION", "python-strategy", { direction: strategy });
        const aiEvent = event("AI_DECISION", "ai-final-decision", { direction: ai });
        return buildDecisionRailwayModel(customEngine([strategyEvent, aiEvent], aiEvent, {
            decisionContext: { strategyDecision: strategyEvent, aiDecision: aiEvent },
        })).finalDecision.aiRelation;
    };
    assert.equal(relation("BUY", "BUY"), "ACCEPTED");
    assert.equal(relation("BUY", "HOLD"), "DOWNGRADED_TO_HOLD");
    assert.equal(relation("HOLD", "HOLD"), "AGREED_HOLD");
    assert.equal(relation("HOLD", "BUY"), "CONFLICT");
});

test("strategy suppression and governance rejection are blocked", () => {
    const strategy = event("STRATEGY_DECISION", "python-strategy", {
        direction: "HOLD", executionAllowed: false, suppressionReason: "RISK_LIMIT",
    });
    const governance = event("GOVERNANCE_DECISION", "governance", {
        execution_enabled: false, outcome: "BLOCKED", blockReason: "SAFETY_MODE",
    });
    const model = buildDecisionRailwayModel(customEngine([strategy, governance], governance, {
        decisionContext: { strategyDecision: strategy, governanceDecision: governance },
    }));
    assert.equal(model.stations[3].status, "blocked");
    assert.equal(model.stations[5].status, "blocked");
    assert.equal(model.finalDecision.governance, "BLOCKED");
    assert.equal(model.finalDecision.execution, "NOT SENT");
});

test("successful and failed execution flows are distinguished", () => {
    const governance = event("GOVERNANCE_DECISION", "governance", {
        execution_enabled: true, outcome: "APPROVED",
    });
    const success = event("ORDER_ACKNOWLEDGED", "execution", {
        status: "ACKNOWLEDGED", clientOrderId: "order-1", side: "BUY",
    });
    let model = buildDecisionRailwayModel(customEngine([governance, success], success, {
        decisionContext: { governanceDecision: governance, executionEvent: success },
    }));
    assert.equal(model.stations[6].status, "active");
    assert.equal(model.finalExecution, "ACKNOWLEDGED");
    const failure = event("EXECUTION_REJECTED", "execution", { reason: "ORDER_FAILED" });
    model = buildDecisionRailwayModel(customEngine([governance, failure], failure, {
        decisionContext: { governanceDecision: governance, executionEvent: failure },
    }));
    assert.equal(model.stations[6].status, "error");
    assert.equal(model.stations[6].reason, "ORDER_FAILED");
});

test("cursor commands move current station and reset clears the path", () => {
    let engine = loaded();
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "market-data");
    engine = applyReplayCommand(engine, { type: C.STEP_FORWARD });
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "detectors");
    engine = applyReplayCommand(engine, { type: C.STEP_BACKWARD });
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "market-data");
    engine = applyReplayCommand(engine, { type: C.SEEK,
        payload: { timestamp: "2026-07-20T12:00:20.000Z" } });
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "governance");
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_START });
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "market-data");
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "execution");
    engine = applyReplayCommand(engine, { type: C.RESTART });
    assert.equal(buildDecisionRailwayModel(engine).currentStationId, "market-data");
    engine = applyReplayCommand(engine, { type: C.RESET });
    assert.equal(buildDecisionRailwayModel(engine).hasData, false);
});

test("invalid scalar values and unrelated current events remain safe", () => {
    const bad = event("UNKNOWN", "unknown-station", {
        direction: {}, confidence: Number.NaN, reason: ["bad"], value: Number.POSITIVE_INFINITY,
    }, { timestamp: "invalid", dataQuality: null });
    const model = buildDecisionRailwayModel(customEngine([bad], bad));
    assert.equal(model.currentStationId, null);
    assert.equal(model.stations.every(({ active }) => active === false), true);
    assert.equal(model.stations.every(({ primaryValue }) => typeof primaryValue === "string"), true);

    const unknown = buildDecisionRailwayModel({
        projection: {
            stationContext: { stations: [{ stationId: "detector", events: [null] }] },
            visibleEvents: [],
        },
    });
    assert.equal(unknown.stations[1].status, "unknown");
});
