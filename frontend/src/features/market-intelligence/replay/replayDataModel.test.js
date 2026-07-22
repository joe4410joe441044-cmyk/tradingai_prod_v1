import assert from "node:assert/strict";
import test from "node:test";

import {
    REPLAY_DATA_QUALITY,
    REPLAY_EVENT_SOURCES,
    REPLAY_EVENT_TYPES,
    REPLAY_MARKER_SIDES,
    REPLAY_MARKER_TYPES,
} from "./replayConstants.js";
import { XRP_REPLAY_FIXTURE } from "./replayFixtures.js";
import {
    findReplayEventAtOrAfter,
    findReplayEventAtOrBefore,
    findReplayEventById,
    getReplayRange,
    sortReplayEvents,
} from "./replayUtils.js";
import {
    validateReplayDataset,
    validateReplayEvent,
    validateReplayMarker,
} from "./replayValidation.js";

const clone = (value) => structuredClone(value);
const validEvent = () => clone(XRP_REPLAY_FIXTURE.events[0]);
const validDataset = () => clone(XRP_REPLAY_FIXTURE);
const hasError = (result, code) => result.errors.some((item) => item.code === code);

test("replay constants contain every required contract value", () => {
    assert.deepEqual(REPLAY_EVENT_TYPES, [
        "MARKET_SNAPSHOT", "DETECTOR_SIGNAL", "STRATEGY_DECISION", "AI_DECISION",
        "GOVERNANCE_DECISION", "ORDER_SUBMITTED", "ORDER_ACKNOWLEDGED",
        "POSITION_OPENED", "POSITION_UPDATED", "POSITION_CLOSED", "EXECUTION_REJECTED",
    ]);
    assert.deepEqual(REPLAY_EVENT_SOURCES, [
        "MARKET", "DETECTOR", "STRATEGY", "AI", "GOVERNANCE",
        "EXECUTION", "POSITION", "SYSTEM",
    ]);
    assert.deepEqual(REPLAY_DATA_QUALITY, [
        "UNKNOWN", "VALID", "PARTIAL", "STALE", "INVALID",
    ]);
    assert.ok(Object.isFrozen(REPLAY_EVENT_TYPES));
    assert.deepEqual(REPLAY_MARKER_TYPES, [
        "BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN",
        "ORDER_FAILED", "GOVERNANCE_BLOCK", "UNKNOWN",
    ]);
    assert.deepEqual(REPLAY_MARKER_SIDES, ["BUY", "SELL"]);
});

const validMarker = () => ({
    id: "marker-1", markerId: "marker-1", type: "UNKNOWN",
    timestamp: "2026-07-20T12:00:00.000Z", sequence: 1,
    price: null, quantity: null, side: null, reason: null, orderId: null,
    reduceOnly: false, flatten: false, blocked: false, failed: false,
    source: "SYSTEM", eventType: "MARKET_SNAPSHOT", dataQuality: "VALID",
});

test("marker validation accepts the formal contract and nullable fields", () => {
    assert.deepEqual(validateReplayMarker(validMarker()), { valid: true, errors: [] });
});

test("marker validation reports missing fields and invalid scalar types", () => {
    const cases = [
        ["id", ""], ["markerId", null], ["type", "LONG"], ["timestamp", "bad"],
        ["sequence", -1], ["price", "100"], ["quantity", []], ["side", "LONG"],
        ["reduceOnly", null], ["flatten", 1], ["blocked", "false"], ["failed", undefined],
        ["source", "VENUE"], ["eventType", "MARKER_EVENT"], ["dataQuality", "GOOD"],
    ];
    for (const [field, value] of cases) {
        const marker = validMarker();
        marker[field] = value;
        assert.equal(validateReplayMarker(marker).valid, false, field);
    }
    const missing = validMarker();
    delete missing.id;
    assert.equal(hasError(validateReplayMarker(missing), "REQUIRED"), true);
});

test("event validation accepts a valid event", () => {
    assert.deepEqual(validateReplayEvent(validEvent()), { valid: true, errors: [] });
});

test("event validation reports missing and invalid fields", () => {
    const missing = validEvent();
    delete missing.id;
    assert.equal(hasError(validateReplayEvent(missing), "REQUIRED"), true);

    const unknownType = validEvent();
    unknownType.eventType = "UNKNOWN_EVENT";
    assert.equal(hasError(validateReplayEvent(unknownType), "UNKNOWN_VALUE"), true);

    const unknownSource = validEvent();
    unknownSource.source = "UNKNOWN_SOURCE";
    assert.equal(hasError(validateReplayEvent(unknownSource), "UNKNOWN_VALUE"), true);

    const invalidTimestamp = validEvent();
    invalidTimestamp.timestamp = "not-a-date";
    assert.equal(hasError(validateReplayEvent(invalidTimestamp), "INVALID_TIMESTAMP"), true);

    const invalidPayload = validEvent();
    invalidPayload.payload = [];
    assert.equal(hasError(validateReplayEvent(invalidPayload), "INVALID_TYPE"), true);
});

test("dataset validation rejects invalid event collections and duplicates", () => {
    assert.deepEqual(validateReplayDataset(validDataset()), { valid: true, errors: [] });

    const nonArray = validDataset();
    nonArray.events = null;
    assert.equal(hasError(validateReplayDataset(nonArray), "INVALID_TYPE"), true);

    const duplicateId = validDataset();
    duplicateId.events[1].id = duplicateId.events[0].id;
    assert.equal(hasError(validateReplayDataset(duplicateId), "DUPLICATE_ID"), true);

    const duplicateSequence = validDataset();
    duplicateSequence.events[1].sequence = duplicateSequence.events[0].sequence;
    assert.equal(hasError(validateReplayDataset(duplicateSequence), "DUPLICATE_SEQUENCE"), true);

    const invalidEvent = validDataset();
    invalidEvent.events[2].source = "UNKNOWN_SOURCE";
    assert.equal(validateReplayDataset(invalidEvent).valid, false);
});

test("event sorting uses timestamp then sequence without mutating input", () => {
    const events = [
        { id: "later", timestamp: "2026-07-20T12:00:02.000Z", sequence: 3 },
        { id: "same-second-later-sequence", timestamp: "2026-07-20T12:00:01.000Z", sequence: 2 },
        { id: "same-second-first-sequence", timestamp: "2026-07-20T12:00:01.000Z", sequence: 1 },
    ];
    const original = clone(events);

    assert.deepEqual(sortReplayEvents(events).map(({ id }) => id), [
        "same-second-first-sequence",
        "same-second-later-sequence",
        "later",
    ]);
    assert.deepEqual(events, original);
});

test("replay lookup utilities handle IDs, cursor boundaries, and range", () => {
    const events = XRP_REPLAY_FIXTURE.events;

    assert.equal(findReplayEventById(events, "replay-event-004")?.eventType, "AI_DECISION");
    assert.equal(
        findReplayEventAtOrBefore(events, "2026-07-20T12:00:16.000Z")?.eventType,
        "AI_DECISION",
    );
    assert.equal(
        findReplayEventAtOrAfter(events, "2026-07-20T12:00:16.000Z")?.eventType,
        "GOVERNANCE_DECISION",
    );
    assert.deepEqual(getReplayRange(events), {
        startedAt: XRP_REPLAY_FIXTURE.startedAt,
        endedAt: XRP_REPLAY_FIXTURE.endedAt,
    });
});

test("replay utilities safely handle empty and absent inputs", () => {
    assert.deepEqual(sortReplayEvents(null), []);
    assert.equal(findReplayEventById(undefined, "missing"), null);
    assert.equal(findReplayEventAtOrBefore([], Date.now()), null);
    assert.equal(findReplayEventAtOrAfter(null, Date.now()), null);
    assert.equal(getReplayRange(undefined), null);
});

test("the static fixture validates and preserves the required event flow", () => {
    assert.deepEqual(validateReplayDataset(XRP_REPLAY_FIXTURE), { valid: true, errors: [] });
    assert.deepEqual(XRP_REPLAY_FIXTURE.events.map(({ eventType }) => eventType), [
        "MARKET_SNAPSHOT",
        "DETECTOR_SIGNAL",
        "STRATEGY_DECISION",
        "AI_DECISION",
        "GOVERNANCE_DECISION",
        "ORDER_SUBMITTED",
        "ORDER_ACKNOWLEDGED",
        "POSITION_OPENED",
        "POSITION_UPDATED",
        "POSITION_CLOSED",
    ]);
});
