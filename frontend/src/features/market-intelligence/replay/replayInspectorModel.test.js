import assert from "node:assert/strict";
import test from "node:test";

import { applyReplayCommand, createInitialReplayEngineState, REPLAY_ENGINE_COMMANDS as C } from "./replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import {
    buildReplayInspectorModel,
    normalizeInspectorTimestamp,
    normalizeInspectorValue,
} from "./replayInspectorModel.js";

const load = () => applyReplayCommand(createInitialReplayEngineState(), {
    type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE },
});
const value = (input) => normalizeInspectorValue(input).displayValue;

test("value normalization produces render-safe scalars", () => {
    assert.equal(value("text"), "text");
    assert.equal(value(""), "—");
    assert.equal(value(0), "0");
    assert.equal(value(-2.5), "-2.5");
    assert.equal(value(Number.NaN), "—");
    assert.equal(value(Number.POSITIVE_INFINITY), "—");
    assert.equal(value(true), "TRUE");
    assert.equal(value(false), "FALSE");
    assert.equal(value(null), "—");
    assert.equal(value(undefined), "—");
    assert.match(value(["BUY", "HOLD", "SELL", "BUY"]), /^4 items:/);
    assert.equal(value({ one: 1, two: 2 }), "2 fields");
    assert.equal(normalizeInspectorTimestamp("2026-07-01T10:00:00Z"), "2026-07-01T10:00:00.000Z");
    assert.equal(normalizeInspectorTimestamp("not-a-date"), "—");
    assert.equal(normalizeInspectorTimestamp(1e100), "—");
});

test("station rendering is isolated from non-contract dataset and visible events", () => {
    const model = buildReplayInspectorModel({
        dataset: { symbol: "FORBIDDEN" },
        projection: {
            currentEvent: null,
            visibleEvents: [{
                id: "forbidden-event",
                eventType: "MARKET_SNAPSHOT",
                timestamp: "2026-07-01T10:00:00Z",
                payload: { symbol: "FORBIDDEN" },
            }],
            stationContext: { stations: [] },
        },
    });
    assert.equal(model.stations.every(({ status }) => status === "NOT REACHED"), true);
    assert.equal(model.stations.some(({ eventId }) => eventId === "forbidden-event"), false);
});

test("null engines and projections create a safe empty inspector", () => {
    for (const engine of [null, {}, { projection: null }]) {
        const model = buildReplayInspectorModel(engine);
        assert.equal(model.isEmpty, true);
        assert.equal(model.currentEvent.event, null);
        assert.equal(model.position.status, "NOT AVAILABLE");
        assert.equal(model.markers.count, 0);
        assert.equal(model.stations.length, 7);
        assert.equal(model.diagnostics[0].displayValue, "NONE");
    }
});

test("loaded replay context and current event expose required safe fields", () => {
    const model = buildReplayInspectorModel(load());
    const replay = Object.fromEntries(model.replay.map((item) => [item.label, item.displayValue]));
    assert.equal(replay["Machine State"], "REPLAY_READY");
    assert.equal(replay["Replay Cursor"], XRP_REPLAY_FIXTURE.startedAt);
    assert.equal(replay.Progress, "0%");
    assert.equal(replay["Current Index"], "—");
    assert.equal(replay["Visible Event Count"], "—");
    assert.equal(model.currentEvent.event.type, "MARKET_SNAPSHOT");
    assert.equal(model.currentEvent.payloadPreview.length <= 8, true);
    assert.equal(model.adjacentEvents.previous, null);
    assert.equal(model.adjacentEvents.next.type, "DETECTOR_SIGNAL");
});

test("decision and position contexts advance without mixing responsibilities", () => {
    let engine = applyReplayCommand(load(), { type: C.SEEK,
        payload: { timestamp: "2026-07-20T12:00:27.000Z" } });
    let model = buildReplayInspectorModel(engine);
    assert.equal(model.decision.layers[0].status, "REACHED");
    assert.equal(model.decision.layers[1].status, "REACHED");
    assert.equal(model.decision.layers[2].status, "REACHED");
    assert.equal(model.decision.layers[3].status, "REACHED");
    assert.equal(model.position.status, "NOT AVAILABLE");
    engine = applyReplayCommand(engine, { type: C.SEEK,
        payload: { timestamp: "2026-07-20T12:01:30.000Z" } });
    model = buildReplayInspectorModel(engine);
    assert.equal(model.position.status, "CLOSED");
    assert.equal(model.position.fields.find(({ label }) => label === "Realized PnL").displayValue, "0.3");
});

test("markers are projection ordered and capped at five", () => {
    const engine = load();
    engine.projection.markerContext = {
        markers: Array.from({ length: 7 }, (_, index) => ({
            id: `marker-${index}`, markerId: `marker-${index}`, type: "BUY",
            timestamp: XRP_REPLAY_FIXTURE.startedAt, sequence: index, price: null,
            quantity: null, side: index % 2 ? "SELL" : "BUY", reason: null,
            orderId: null, reduceOnly: false, flatten: false, blocked: false,
            failed: false, source: "SYSTEM", eventType: "MARKET_SNAPSHOT", dataQuality: "VALID",
        })),
        latestMarker: { id: "marker-6", markerId: "marker-6" },
    };
    const model = buildReplayInspectorModel(engine);
    assert.equal(model.markers.count, 7);
    assert.equal(model.markers.items.length, 5);
    assert.deepEqual(model.markers.items.map(({ id }) => id), [
        "marker-0", "marker-1", "marker-2", "marker-3", "marker-4",
    ]);
});

test("station context reuses the fixed Decision Railway model", () => {
    const model = buildReplayInspectorModel(load());
    assert.deepEqual(model.stations.map(({ id }) => id), [
        "market-data", "detectors", "feature-builder", "strategy", "ai-review", "governance", "execution",
    ]);
    assert.equal(model.stations[0].status, "ACTIVE");
    assert.equal(model.stations[1].status, "NOT REACHED");
});

test("quality, validation, error, and rejection values are preserved", () => {
    const engine = load();
    engine.validation = { valid: false, errors: Array.from({ length: 12 }, (_, index) => ({ index })),
        warnings: [{ code: "WARN" }] };
    engine.engineError = { code: "FAIL", message: "Failed." };
    engine.accepted = false;
    engine.rejectionReason = "REJECTED";
    const model = buildReplayInspectorModel(engine);
    assert.equal(model.dataQuality.datasetValidation, "INVALID");
    assert.equal(model.dataQuality.validationErrors.length, 10);
    assert.equal(model.dataQuality.validationErrorCount, 12);
    assert.equal(model.dataQuality.validationWarnings.length, 1);
    assert.equal(model.diagnostics[0].displayValue, "Failed.");
    assert.equal(model.diagnostics[1].displayValue, "REJECTED");
});

test("data payloads are previewed and governance blocks cannot appear executed", () => {
    const model = buildReplayInspectorModel({
        projection: {
            currentEvent: { id: "event-data", eventType: "CUSTOM", timestamp: "bad", data: {
                direction: "SIDEWAYS", price: 12, nested: { unsafe: true },
            } },
            decisionContext: {
                governanceDecision: { eventType: "GOVERNANCE_DECISION", payload: {
                    executionEnabled: false, outcome: "BLOCKED",
                } },
                executionEvent: { eventType: "ORDER_ACKNOWLEDGED", payload: { status: "SUCCESS" } },
            },
        },
    });
    assert.equal(model.currentEvent.payloadPreview.length, 2);
    assert.equal(model.currentEvent.fields.find(({ label }) => label === "Timestamp").displayValue, "—");
    assert.equal(model.decision.layers[3].status, "NOT REACHED");
    assert.equal(model.decision.layers[3].fields[0].displayValue, "NOT SENT");
});

test("cursor commands update current, adjacent, contexts, and reset", () => {
    let engine = load();
    assert.equal(buildReplayInspectorModel(engine).currentEvent.event.id, "replay-event-001");
    engine = applyReplayCommand(engine, { type: C.STEP_FORWARD });
    assert.equal(buildReplayInspectorModel(engine).currentEvent.event.id, "replay-event-002");
    engine = applyReplayCommand(engine, { type: C.STEP_BACKWARD });
    assert.equal(buildReplayInspectorModel(engine).currentEvent.event.id, "replay-event-001");
    engine = applyReplayCommand(engine, { type: C.SEEK,
        payload: { timestamp: "2026-07-20T12:00:30.000Z" } });
    assert.equal(buildReplayInspectorModel(engine).position.status, "OPEN");
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_START });
    assert.equal(buildReplayInspectorModel(engine).currentEvent.event.id, "replay-event-001");
    engine = applyReplayCommand(engine, { type: C.JUMP_TO_END });
    assert.equal(buildReplayInspectorModel(engine).adjacentEvents.next, null);
    engine = applyReplayCommand(engine, { type: C.RESTART });
    assert.equal(buildReplayInspectorModel(engine).currentEvent.event.id, "replay-event-001");
    engine = applyReplayCommand(engine, { type: C.RESET });
    assert.equal(buildReplayInspectorModel(engine).isEmpty, true);
});
