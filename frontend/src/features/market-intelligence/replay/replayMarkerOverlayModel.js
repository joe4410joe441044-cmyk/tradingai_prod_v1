import { marketDisplayValue, marketTimestamp, normalizeMarketSide } from "./replayMarketViewModel.js";

const DASH = "—";
const TYPES = ["BUY", "SELL", "ENTRY", "EXIT", "REDUCE_ONLY", "FLATTEN", "ORDER_FAILED", "GOVERNANCE_BLOCK", "UNKNOWN"];
const MAX_PRICE = 20;
const MAX_TIME = 20;
const MAX_UNMATCHED = 10;

const finite = (value) => typeof value === "number" && Number.isFinite(value);
const payloadOf = (event) => event?.payload && typeof event.payload === "object"
    && !Array.isArray(event.payload) ? event.payload : {};

export function normalizeMarkerType(type) {
    const value = typeof type === "string" ? type.trim().toUpperCase().replaceAll(" ", "_") : "";
    if (["BUY", "LONG"].includes(value)) return "BUY";
    if (["SELL", "SHORT"].includes(value)) return "SELL";
    if (value === "ENTRY") return "ENTRY";
    if (value === "EXIT") return "EXIT";
    if (value === "REDUCE_ONLY") return "REDUCE_ONLY";
    if (value === "FLATTEN") return "FLATTEN";
    if (["ORDER_FAILED", "ORDER_ERROR"].includes(value)) return "ORDER_FAILED";
    if (["GOVERNANCE_BLOCK", "BLOCKED"].includes(value)) return "GOVERNANCE_BLOCK";
    return "UNKNOWN";
}

const categoryFor = (type) => {
    if (["BUY", "SELL"].includes(type)) return "DECISION";
    if (["ENTRY", "EXIT"].includes(type)) return "POSITION";
    if (["REDUCE_ONLY", "FLATTEN"].includes(type)) return "ORDER";
    if (type === "GOVERNANCE_BLOCK") return "SAFETY";
    if (type === "ORDER_FAILED") return "ERROR";
    return "UNKNOWN";
};

const labelFor = (type) => type.replaceAll("_", " ");
const normalizedScalar = (value) => marketDisplayValue(value);

const markerFromGroup = (group, index) => {
    if (!group || typeof group !== "object" || Array.isArray(group)) return null;
    const events = Array.isArray(group.events) ? group.events : [];
    const event = events.findLast((candidate) => candidate && typeof candidate === "object") ?? null;
    const payload = payloadOf(event);
    const type = normalizeMarkerType(payload.markerType ?? group.type ?? group.markerType);
    const price = finite(payload.price) ? payload.price
        : finite(payload.entryPrice) ? payload.entryPrice : finite(payload.exitPrice) ? payload.exitPrice : null;
    const quantity = finite(payload.quantity) ? payload.quantity : null;
    const timestamp = marketTimestamp(payload.timestamp ?? event?.timestamp);
    const sourceId = group.markerId ?? group.id ?? event?.markerId ?? event?.id;
    const id = normalizedScalar(sourceId) === DASH ? `marker-${index + 1}` : String(sourceId);
    const side = normalizeMarketSide(payload.side);
    const invalid = normalizedScalar(sourceId) === DASH || type === "UNKNOWN"
        || (payload.price !== undefined && price === null)
        || (payload.quantity !== undefined && quantity === null);
    return {
        id, displayKey: `${id}-${index}`, type, category: categoryFor(type), side, label: labelFor(type),
        eventId: normalizedScalar(payload.eventId ?? event?.id),
        timestamp, numericPrice: price, price: normalizedScalar(price), quantity: normalizedScalar(quantity),
        orderId: normalizedScalar(payload.orderId ?? payload.clientOrderId),
        positionId: normalizedScalar(event?.positionId ?? payload.positionId),
        reason: normalizedScalar(payload.reason ?? payload.blockReason),
        status: normalizedScalar(payload.status ?? payload.outcome),
        reduceOnly: payload.reduceOnly === true, flatten: payload.flatten === true,
        blocked: payload.blocked === true || type === "GOVERNANCE_BLOCK",
        failed: payload.failed === true || type === "ORDER_FAILED",
        dataQuality: normalizedScalar(event?.dataQuality) === DASH ? "UNKNOWN" : event.dataQuality,
        sourceSequence: finite(payload.sequence) ? payload.sequence : finite(event?.sequence) ? event.sequence : null,
        tradeId: normalizedScalar(payload.tradeId),
        invalid,
    };
};

const LEGEND = Object.freeze([
    ["BUY", "Buy direction or order"], ["SELL", "Sell direction or order"],
    ["ENTRY", "Position opened"], ["EXIT", "Position closed"],
    ["REDUCE_ONLY", "Position-reducing order"], ["FLATTEN", "Explicit full close"],
    ["ORDER_FAILED", "Order failed or rejected"],
    ["GOVERNANCE_BLOCK", "Execution prevented by governance"],
].map(([type, description]) => ({ type, label: labelFor(type), description })));

export function buildReplayMarkerOverlayModel(replayEngine, marketViewModel = {}) {
    const markerContext = replayEngine?.projection?.markerContext;
    const source = Array.isArray(markerContext?.markers) ? markerContext.markers : [];
    const normalized = source.map(markerFromGroup).filter(Boolean);
    const bookRows = [...(Array.isArray(marketViewModel?.orderBook?.asks) ? marketViewModel.orderBook.asks : []),
        ...(Array.isArray(marketViewModel?.orderBook?.bids) ? marketViewModel.orderBook.bids : [])];
    const bookPrices = new Set(bookRows.map(({ price }) => price).filter((price) => typeof price === "string"));
    const trades = Array.isArray(marketViewModel?.recentTrades?.rows) ? marketViewModel.recentTrades.rows : [];

    const markers = normalized.map((marker) => {
        const priceMatch = marker.price !== DASH && bookPrices.has(marker.price);
        const matchedTrade = trades.find((trade) => (
            marker.timestamp !== DASH && trade.timestamp === marker.timestamp
        ) || (
            marker.tradeId !== DASH && trade.tradeId === marker.tradeId
        ) || (
            marker.sourceSequence !== null && trade.sourceSequence === marker.sourceSequence
        ));
        return { ...marker, priceMatch, timeMatch: Boolean(matchedTrade), matchedTradeId: matchedTrade?.id ?? DASH };
    });
    const allPriceMarkers = markers.filter(({ numericPrice }) => finite(numericPrice));
    const allTimeMarkers = markers.filter(({ timestamp }) => timestamp !== DASH);
    const allUnmatched = markers.filter(({ priceMatch, timeMatch }) => !priceMatch && !timeMatch);
    const formalLatest = markerContext?.latestMarker;
    const formalLatestId = formalLatest?.markerId ?? formalLatest?.id;
    const latestMarker = markers.findLast(({ id }) => formalLatestId !== undefined && String(formalLatestId) === id)
        ?? (formalLatest && typeof formalLatest === "object" ? markerFromGroup(formalLatest, source.length) : null)
        ?? markers.at(-1) ?? null;
    const byType = Object.fromEntries(TYPES.map((type) => [type, markers.filter((marker) => marker.type === type).length]));
    const displayedIds = new Set([
        ...allPriceMarkers.slice(0, MAX_PRICE), ...allTimeMarkers.slice(0, MAX_TIME), ...allUnmatched.slice(0, MAX_UNMATCHED),
    ].map(({ id }) => id));

    return {
        markers,
        priceMarkers: allPriceMarkers.slice(0, MAX_PRICE),
        timeMarkers: allTimeMarkers.slice(0, MAX_TIME),
        unmatchedMarkers: allUnmatched.slice(0, MAX_UNMATCHED),
        latestMarker,
        counts: {
            visible: markers.length,
            priceMatched: markers.filter(({ priceMatch }) => priceMatch).length,
            timeMatched: markers.filter(({ timeMatch }) => timeMatch).length,
            unmatched: allUnmatched.length,
            byType,
        },
        legend: LEGEND,
        quality: replayEngine?.projection?.dataQuality ?? "UNKNOWN",
        diagnostics: {
            sourceMarkerCount: source.length,
            displayedMarkerCount: displayedIds.size,
            invalidMarkerCount: source.length - normalized.length + markers.filter(({ invalid }) => invalid).length,
            missingPriceCount: markers.filter(({ price }) => price === DASH).length,
            missingTimestampCount: markers.filter(({ timestamp }) => timestamp === DASH).length,
            unmatchedPriceCount: allPriceMarkers.filter(({ priceMatch }) => !priceMatch).length,
            unmatchedTimeCount: allTimeMarkers.filter(({ timeMatch }) => !timeMatch).length,
            truncatedMarkerCount: Math.max(0, allPriceMarkers.length - MAX_PRICE)
                + Math.max(0, allTimeMarkers.length - MAX_TIME)
                + Math.max(0, allUnmatched.length - MAX_UNMATCHED),
            unknownTypeCount: byType.UNKNOWN,
        },
        hasMarkers: markers.length > 0,
        isEmpty: markers.length === 0,
    };
}
