import { buildDecisionRailwayModel } from "./decisionRailwayModel.js";

const DASH = "—";
const NONE = "NONE";
const PAYLOAD_FIELDS = [
    "direction", "confidence", "price", "entryPrice", "exitPrice", "markPrice",
    "quantity", "side", "status", "result", "outcome", "reason", "mode", "spread",
    "volatility", "momentum", "liquidity", "executionAllowed", "execution_enabled",
    "blockReason", "clientOrderId", "orderId",
];

export function normalizeInspectorValue(value) {
    if (typeof value === "string") {
        return { displayValue: value === "" ? DASH : value, valueType: "string", isMissing: value === "" };
    }
    if (typeof value === "number") {
        return {
            displayValue: Number.isFinite(value) ? String(value) : DASH,
            valueType: "number",
            isMissing: !Number.isFinite(value),
        };
    }
    if (typeof value === "boolean") {
        return { displayValue: value ? "TRUE" : "FALSE", valueType: "boolean", isMissing: false };
    }
    if (value === null || value === undefined) {
        return { displayValue: DASH, valueType: "missing", isMissing: true };
    }
    if (Array.isArray(value)) {
        const scalar = value.filter((item) => ["string", "number", "boolean"].includes(typeof item))
            .slice(0, 3).map((item) => normalizeInspectorValue(item).displayValue);
        return {
            displayValue: scalar.length > 0 ? `${value.length} items: ${scalar.join(", ")}` : `${value.length} items`,
            valueType: "array",
            isMissing: false,
        };
    }
    if (typeof value === "object") {
        return {
            displayValue: `${Object.keys(value).length} fields`,
            valueType: "object",
            isMissing: false,
        };
    }
    return { displayValue: DASH, valueType: typeof value, isMissing: true };
}

export const normalizeInspectorTimestamp = (value) => {
    if (value === null || value === undefined || value === "") return DASH;
    const epoch = typeof value === "number" ? value : Date.parse(value);
    if (!Number.isFinite(epoch)) return DASH;
    const date = new Date(epoch);
    return Number.isFinite(date.getTime()) ? date.toISOString() : DASH;
};

const field = (id, label, value, options = {}) => {
    const normalized = options.timestamp
        ? normalizeInspectorValue(normalizeInspectorTimestamp(value))
        : normalizeInspectorValue(value);
    return { id, label, value, quality: options.quality ?? null, ...normalized };
};

const fields = (entries) => entries.map(([id, label, value, options]) => (
    field(id, label, value, options)
));

const payloadOf = (event) => {
    const payload = event?.payload ?? event?.data;
    return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
};

const errorValue = (error) => {
    if (error === null || error === undefined || error === "") return NONE;
    if (typeof error === "object" && !Array.isArray(error)) {
        return error.message ?? error.code ?? normalizeInspectorValue(error).displayValue;
    }
    return error;
};

const validationItem = (item, index) => field(
    `validation-${index}`,
    `Item ${index + 1}`,
    typeof item === "object" && item !== null
        ? item.message ?? item.code ?? item.path ?? item
        : item,
);

const eventModel = (event) => {
    if (!event || typeof event !== "object") return null;
    return {
        id: normalizeInspectorValue(event.id).displayValue,
        type: normalizeInspectorValue(event.eventType).displayValue,
        timestamp: normalizeInspectorTimestamp(event.timestamp),
        sequence: Number.isFinite(event.sequence) ? `#${event.sequence}` : DASH,
        stationId: normalizeInspectorValue(event.stationId).displayValue,
        source: normalizeInspectorValue(event.source).displayValue,
        dataQuality: normalizeInspectorValue(event.dataQuality).displayValue,
    };
};

const layer = (name, event, entries) => ({
    id: name.toLowerCase().replaceAll(" ", "-"),
    title: name,
    reached: Boolean(event),
    status: event ? "REACHED" : "NOT REACHED",
    fields: fields(entries),
});

export function buildReplayInspectorModel(replayEngine) {
    const engine = replayEngine && typeof replayEngine === "object" ? replayEngine : {};
    const projection = engine.projection && typeof engine.projection === "object"
        ? engine.projection
        : {};
    const current = projection.currentEvent ?? null;
    const currentPayload = payloadOf(current);
    const decision = projection.decisionContext ?? {};
    const strategy = decision.strategyDecision ?? null;
    const ai = decision.aiDecision ?? null;
    const governance = decision.governanceDecision ?? null;
    const execution = decision.executionEvent ?? null;
    const strategyPayload = payloadOf(strategy);
    const aiPayload = payloadOf(ai);
    const governancePayload = payloadOf(governance);
    const executionPayload = payloadOf(execution);
    const position = projection.positionContext ?? {};
    const openedPayload = payloadOf(position.openedEvent);
    const updatePayload = payloadOf(position.latestUpdateEvent);
    const closedPayload = payloadOf(position.closedEvent);
    const markerContracts = Array.isArray(projection.markerContext?.markers)
        ? projection.markerContext.markers
        : [];
    const markers = markerContracts.slice(0, 5).map((marker, index) => {
        return {
            id: normalizeInspectorValue(marker?.id).displayValue === DASH
                ? `marker-${index + 1}` : marker.id,
            fields: fields([
                ["marker-id", "Marker ID", marker?.markerId],
                ["type", "Marker Type", marker?.type],
                ["side", "Side", marker?.side], ["price", "Price", marker?.price],
                ["quantity", "Quantity", marker?.quantity],
                ["timestamp", "Timestamp", marker?.timestamp, { timestamp: true }],
                ["reason", "Reason", marker?.reason], ["order-id", "Order ID", marker?.orderId],
                ["reduce-only", "Reduce Only", marker?.reduceOnly], ["flatten", "Flatten", marker?.flatten],
            ]),
        };
    });
    // Keep the reused station presentation logic inside the Inspector's source contract.
    // In particular, do not expose dataset or projection.visibleEvents to that model.
    const railway = buildDecisionRailwayModel({
        replayCursor: engine.replayCursor,
        projection: {
            currentEvent: current,
            // Decision Railway recognizes ungrouped market-data from its event list.
            // Supply only the authoritative current event, never Projection's full list.
            visibleEvents: current ? [current] : [],
            positionContext: projection.positionContext ?? null,
            decisionContext: projection.decisionContext ?? null,
            stationContext: projection.stationContext ?? null,
            dataQuality: projection.dataQuality ?? null,
        },
    });
    const allValidationErrors = Array.isArray(engine.validation?.errors) ? engine.validation.errors : [];
    const allValidationWarnings = Array.isArray(engine.validation?.warnings) ? engine.validation.warnings : [];
    const validationErrors = allValidationErrors.slice(0, 10).map(validationItem);
    const validationWarnings = allValidationWarnings.slice(0, 10).map(validationItem);
    const governanceBlocked = railway.finalDecision.governance === "BLOCKED";

    return {
        replay: fields([
            ["machine", "Machine State", engine.machine?.state ?? "IDLE"],
            ["cursor", "Replay Cursor", engine.replayCursor, { timestamp: true }],
            ["range-start", "Range Start", projection.range?.startedAt, { timestamp: true }],
            ["range-end", "Range End", projection.range?.endedAt, { timestamp: true }],
            ["progress", "Progress", Number.isFinite(projection.progress) ? `${Math.round(projection.progress * 100)}%` : "0%"],
            ["current-index", "Current Index", projection.currentIndex],
            ["visible-count", "Visible Event Count", projection.visibleEventCount],
            ["at-start", "At Start", projection.isAtStart], ["at-end", "At End", projection.isAtEnd],
            ["last-command", "Last Command", engine.lastCommand], ["accepted", "Command Accepted", engine.accepted],
            ["rejection", "Rejection Reason", engine.rejectionReason ?? NONE],
            ["engine-error", "Engine Error", errorValue(engine.engineError)],
        ]),
        currentEvent: {
            event: eventModel(current),
            fields: fields([
                ["event-id", "Event ID", current?.id], ["event-type", "Event Type", current?.eventType],
                ["timestamp", "Timestamp", current?.timestamp, { timestamp: true }],
                ["sequence", "Sequence", current?.sequence], ["station", "Station ID", current?.stationId],
                ["symbol", "Symbol", current?.symbol ?? currentPayload.symbol],
                ["exchange", "Exchange", current?.exchange ?? currentPayload.exchange],
                ["source", "Source", current?.source], ["quality", "Data Quality", current?.dataQuality],
                ["summary", "Summary", current?.summary ?? currentPayload.summary
                    ?? currentPayload.result ?? currentPayload.status],
            ]),
            payloadPreview: PAYLOAD_FIELDS.filter((name) => Object.hasOwn(currentPayload, name))
                .slice(0, 8).map((name) => field(name, name, currentPayload[name])),
        },
        adjacentEvents: {
            previous: eventModel(projection.previousEvent),
            current: eventModel(current),
            next: eventModel(projection.nextEvent),
        },
        decision: {
            layers: [
                layer("Strategy", strategy, [["direction", "Direction", strategyPayload.direction],
                    ["confidence", "Confidence", strategyPayload.confidence],
                    ["execution", "Execution Allowed", strategyPayload.executionAllowed],
                    ["suppression", "Suppression Reason", strategyPayload.suppressionReason]]),
                layer("AI Review", ai, [["direction", "Final Direction", aiPayload.direction],
                    ["bias", "Bias", aiPayload.bias], ["momentum", "Momentum", aiPayload.momentum],
                    ["imbalance", "Imbalance", aiPayload.imbalance], ["confidence", "Confidence", aiPayload.confidence],
                    ["reason", "Review Reason", aiPayload.reason],
                    ["relation", "Strategy Relation", railway.finalDecision.aiRelation]]),
                layer("Governance", governance, [["enabled", "Execution Enabled", governancePayload.execution_enabled ?? governancePayload.executionEnabled],
                    ["outcome", "Outcome", governancePayload.outcome], ["reason", "Block Reason", governancePayload.blockReason],
                    ["mode", "Safety Mode", governancePayload.safetyMode]]),
                layer("Execution", governanceBlocked ? null : execution,
                    [["status", "Status", governanceBlocked ? "NOT SENT" : executionPayload.status ?? execution?.eventType],
                    ["mode", "Mode", executionPayload.mode], ["side", "Side", executionPayload.side],
                    ["quantity", "Quantity", executionPayload.quantity], ["price", "Price", executionPayload.price],
                    ["order", "Order ID", executionPayload.orderId ?? executionPayload.clientOrderId],
                    ["reason", "Reason", executionPayload.reason], ["position", "Position Result", position.status]]),
            ],
        },
        position: {
            available: Boolean(position.positionId),
            status: position.positionId ? position.status ?? "AVAILABLE" : "NOT AVAILABLE",
            fields: fields([
                ["status", "Position Status", position.status],
                ["symbol", "Symbol", position.symbol ?? openedPayload.symbol],
                ["side", "Side", openedPayload.side], ["quantity", "Quantity", openedPayload.quantity],
                ["entry", "Entry Price", openedPayload.entryPrice], ["mark", "Mark Price", updatePayload.markPrice],
                ["unrealized", "Unrealized PnL", updatePayload.unrealizedPnl],
                ["realized", "Realized PnL", closedPayload.realizedPnl], ["leverage", "Leverage", openedPayload.leverage],
                ["margin", "Margin", openedPayload.margin], ["opened", "Open Timestamp", position.openedEvent?.timestamp, { timestamp: true }],
                ["closed", "Close Timestamp", position.closedEvent?.timestamp, { timestamp: true }],
                ["reason", "Close Reason", closedPayload.reason],
                ["mode", "Trade Mode", position.tradeMode ?? openedPayload.tradeMode ?? openedPayload.mode],
            ]),
        },
        markers: {
            count: markerContracts.length,
            latestMarkerId: projection.markerContext?.latestMarker?.markerId ?? DASH,
            items: markers,
        },
        stations: railway.stations.map((station) => ({
            id: station.id, title: station.title, status: station.statusLabel,
            timestamp: station.timestampLabel, primaryValue: station.primaryValue,
            reason: station.reason, dataQuality: station.dataQuality, eventId: station.eventId,
            details: station.secondaryValues.slice(0, 4),
        })),
        dataQuality: {
            projection: projection.dataQuality ?? "UNKNOWN",
            datasetValidation: engine.validation?.valid === true ? "VALID"
                : engine.validation?.valid === false ? "INVALID" : "UNKNOWN",
            validationErrors,
            validationWarnings,
            validationErrorCount: allValidationErrors.length,
            validationWarningCount: allValidationWarnings.length,
            event: current?.dataQuality ?? "UNKNOWN",
            position: position.openedEvent?.dataQuality ?? "UNKNOWN",
            decision: execution?.dataQuality ?? governance?.dataQuality ?? ai?.dataQuality ?? strategy?.dataQuality ?? "UNKNOWN",
            marker: markerContracts.at(-1)?.dataQuality ?? "UNKNOWN",
            station: railway.stations.find(({ active }) => active)?.dataQuality ?? "UNKNOWN",
        },
        diagnostics: fields([
            ["error", "Engine Error", errorValue(engine.engineError)],
            ["rejection", "Rejection Reason", engine.rejectionReason ?? NONE],
            ["command", "Last Command", engine.lastCommand], ["accepted", "Accepted", engine.accepted],
            ["machine", "Machine State", engine.machine?.state ?? "IDLE"],
        ]),
        hasData: Boolean(current),
        isEmpty: !current,
    };
}
