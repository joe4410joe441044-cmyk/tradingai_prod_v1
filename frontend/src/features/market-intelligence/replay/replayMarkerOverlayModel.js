import { REPLAY_DATA_QUALITY, REPLAY_MARKER_TYPES } from "./replayConstants.js";
import { marketDisplayValue, marketTimestamp } from "./replayMarketViewModel.js";
import { validateReplayMarker } from "./replayValidation.js";

const DASH = "—";
const MAX_PRICE = 20;
const MAX_TIME = 20;
const MAX_UNMATCHED = 10;
const MAX_DETAILS = 20;

const finite = (value) => typeof value === "number" && Number.isFinite(value);

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

const markerFromContract = (marker, index) => {
    if (!validateReplayMarker(marker).valid) return null;
    const id = marker.id;
    return {
        id, markerId: marker.markerId, displayKey: `${id}-${index}`, type: marker.type,
        category: categoryFor(marker.type), side: normalizedScalar(marker.side), label: labelFor(marker.type),
        eventId: normalizedScalar(marker.eventId), timestamp: marketTimestamp(marker.timestamp),
        numericPrice: marker.price, price: normalizedScalar(marker.price), quantity: normalizedScalar(marker.quantity),
        orderId: normalizedScalar(marker.orderId), positionId: normalizedScalar(marker.positionId),
        decisionId: normalizedScalar(marker.decisionId), stationId: normalizedScalar(marker.stationId),
        reason: normalizedScalar(marker.reason), sequence: marker.sequence,
        reduceOnly: marker.reduceOnly, flatten: marker.flatten, blocked: marker.blocked, failed: marker.failed,
        source: marker.source, eventType: marker.eventType, dataQuality: marker.dataQuality,
        sourceSequence: marker.sequence,
        tradeId: normalizedScalar(marker.tradeId), invalid: false,
    };
};

const LEGEND = Object.freeze([
    ["BUY", "Buy direction or order"], ["SELL", "Sell direction or order"],
    ["ENTRY", "Position opened"], ["EXIT", "Position closed"],
    ["REDUCE_ONLY", "Position-reducing order"], ["FLATTEN", "Explicit full close"],
    ["ORDER_FAILED", "Order failed or rejected"],
    ["GOVERNANCE_BLOCK", "Execution prevented by governance"],
    ["UNKNOWN", "Unknown marker type; no direction inferred"],
].map(([type, description]) => ({ type, label: labelFor(type), description })));

const formalSummary = (markerContext) => {
    const source = markerContext?.summary && typeof markerContext.summary === "object"
        && !Array.isArray(markerContext.summary) ? markerContext.summary : {};
    const sourceByType = source.byType && typeof source.byType === "object" && !Array.isArray(source.byType)
        ? source.byType : {};
    const byType = Object.fromEntries(REPLAY_MARKER_TYPES.map((type) => [
        type, Number.isInteger(sourceByType[type]) && sourceByType[type] >= 0 ? sourceByType[type] : 0,
    ]));
    return {
        total: Number.isInteger(source.total) && source.total >= 0 ? source.total : 0,
        byType,
        buy: source.buy ?? 0, sell: source.sell ?? 0, entry: source.entry ?? 0, exit: source.exit ?? 0,
        reduceOnly: source.reduceOnly ?? 0, flatten: source.flatten ?? 0,
        failed: source.failed ?? 0, blocked: source.blocked ?? 0, unknown: source.unknown ?? 0,
    };
};

export function buildReplayMarkerOverlayModel(replayEngine, marketViewModel = {}) {
    const markerContext = replayEngine?.projection?.markerContext;
    const source = Array.isArray(markerContext?.markers) ? markerContext.markers : [];
    const normalized = source.map(markerFromContract).filter(Boolean);
    const summary = formalSummary(markerContext);
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
    const formalLatestId = markerContext?.latestMarker?.id;
    const latestMarker = markers.find(({ id }) => id === formalLatestId) ?? null;
    const byQuality = Object.fromEntries(REPLAY_DATA_QUALITY.map((quality) => [
        quality, markers.filter((marker) => marker.dataQuality === quality).length,
    ]));
    const displayedIds = new Set([
        ...allPriceMarkers.slice(0, MAX_PRICE), ...allTimeMarkers.slice(0, MAX_TIME), ...allUnmatched.slice(0, MAX_UNMATCHED),
    ].map(({ id }) => id));

    return {
        markers,
        priceMarkers: allPriceMarkers.slice(0, MAX_PRICE),
        timeMarkers: allTimeMarkers.slice(0, MAX_TIME),
        unmatchedMarkers: allUnmatched.slice(0, MAX_UNMATCHED),
        detailMarkers: markers.slice(0, MAX_DETAILS),
        latestMarker,
        summary,
        counts: {
            visible: Number.isInteger(markerContext?.count) && markerContext.count >= 0 ? markerContext.count : 0,
            priceMatched: markers.filter(({ priceMatch }) => priceMatch).length,
            timeMatched: markers.filter(({ timeMatch }) => timeMatch).length,
            unmatched: allUnmatched.length,
            byType: summary.byType,
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
                + Math.max(0, allUnmatched.length - MAX_UNMATCHED)
                + Math.max(0, markers.length - MAX_DETAILS),
            unknownTypeCount: summary.unknown,
            byQuality,
        },
        hasMarkers: markers.length > 0,
        isEmpty: markers.length === 0,
    };
}
