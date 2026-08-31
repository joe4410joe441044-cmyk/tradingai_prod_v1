import { REPLAY_DATA_QUALITY, REPLAY_MARKER_TYPES } from "./replayConstants.js";
import { marketDisplayValue, marketTimestamp } from "./replayMarketViewModel.js";
import { validateReplayMarker } from "./replayValidation.js";

const DASH = "—";
const MAX_PRICE = 20;
const MAX_TIME = 20;
const MAX_UNMATCHED = 10;
const MAX_DETAILS = 20;
const MAX_INLINE = 3;

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
const markerPresentation = (marker) => {
    const reason = typeof marker.reason === "string" ? marker.reason.toUpperCase().replaceAll(" ", "_") : "";
    if (marker.failed || marker.type === "ORDER_FAILED") return { label: "FAILED", shortLabel: "F" };
    if (marker.type === "GOVERNANCE_BLOCK") return { label: "GOVERNANCE BLOCK", shortLabel: "G" };
    if (marker.blocked) return { label: "BLOCKED", shortLabel: "BLK" };
    if (reason.includes("STOP_LOSS")) return { label: "STOP LOSS", shortLabel: "SL" };
    if (reason.includes("TAKE_PROFIT")) return { label: "TAKE PROFIT", shortLabel: "TP" };
    if (reason.includes("AI_HOLD")) return { label: "AI HOLD", shortLabel: "H" };
    if (marker.flatten || marker.type === "FLATTEN") return { label: "EMERGENCY FLATTEN", shortLabel: "EF" };
    if (reason.includes("ADD_POSITION")) return { label: "ADD POSITION", shortLabel: "ADD" };
    if (marker.reduceOnly || marker.type === "REDUCE_ONLY") return { label: "PARTIAL EXIT", shortLabel: "PX" };
    if (marker.type === "EXIT") return { label: "FULL EXIT", shortLabel: "X" };
    if (marker.type === "ENTRY") return marker.side === "SELL"
        ? { label: "SELL ENTRY", shortLabel: "S" } : marker.side === "BUY"
            ? { label: "BUY ENTRY", shortLabel: "B" } : { label: "ENTRY", shortLabel: "E" };
    if (marker.type === "BUY") return { label: "BUY", shortLabel: "B" };
    if (marker.type === "SELL") return { label: "SELL", shortLabel: "S" };
    return { label: "UNKNOWN", shortLabel: "?" };
};
const normalizedScalar = (value) => marketDisplayValue(value);

const markerFromContract = (marker, index) => {
    if (!validateReplayMarker(marker).valid || finite(marker.price) && marker.price <= 0) return null;
    const id = marker.id;
    const presentation = markerPresentation(marker);
    return {
        id, markerId: marker.markerId, displayKey: `${id}-${index}`, inputIndex: index, type: marker.type,
        category: categoryFor(marker.type), side: normalizedScalar(marker.side), ...presentation,
        eventId: normalizedScalar(marker.eventId), timestamp: marketTimestamp(marker.timestamp),
        numericPrice: marker.price, price: normalizedScalar(marker.price), numericQuantity: marker.quantity,
        quantity: normalizedScalar(marker.quantity),
        orderId: normalizedScalar(marker.orderId), positionId: normalizedScalar(marker.positionId),
        decisionId: normalizedScalar(marker.decisionId), stationId: normalizedScalar(marker.stationId),
        reason: normalizedScalar(marker.reason), sequence: marker.sequence,
        reduceOnly: marker.reduceOnly, flatten: marker.flatten, blocked: marker.blocked, failed: marker.failed,
        source: marker.source, eventType: marker.eventType, dataQuality: marker.dataQuality,
        symbol: marker.symbol, contextKey: marker.contextKey, runtimeInstanceId: marker.runtimeInstanceId,
        sourceSequence: marker.sequence,
        tradeId: normalizedScalar(marker.tradeId), invalid: false,
    };
};

const markerOrder = (left, right) => {
    const time = Date.parse(right.timestamp) - Date.parse(left.timestamp);
    if (Number.isFinite(time) && time !== 0) return time;
    if (finite(left.sequence) && finite(right.sequence) && left.sequence !== right.sequence)
        return right.sequence - left.sequence;
    return left.inputIndex - right.inputIndex;
};
const normalizedPrice = (price, tickSize) => {
    if (!finite(price)) return null;
    if (!finite(tickSize) || tickSize <= 0) return price;
    const precision = String(tickSize).toLowerCase().includes("e-")
        ? Number(String(tickSize).toLowerCase().split("e-")[1])
        : String(tickSize).includes(".") ? String(tickSize).split(".")[1].length : 0;
    return Number((Math.round(price / tickSize) * tickSize).toFixed(Math.min(20, precision)));
};
const formalTradeMatch = (marker, trade) => (
    marker.eventId !== DASH && trade.eventId !== DASH && marker.eventId === trade.eventId
) || (
    marker.tradeId !== DASH && trade.tradeId !== DASH && marker.tradeId === trade.tradeId
) || (
    marker.orderId !== DASH && trade.orderId !== DASH && marker.orderId === trade.orderId
) || (
    finite(marker.sourceSequence) && finite(trade.sourceSequence) && marker.sourceSequence === trade.sourceSequence
);

export const resolveSelectedMarker = (markerModel, selectedMarkerId) => selectedMarkerId
    ? markerModel.markers.find(({ id }) => id === selectedMarkerId) ?? null : null;

export const reconcileMarkerUiSelection = ({ currentContextKey, expandedMarkerGroupKey,
    markerModel, previousContextKey, selectedMarkerId }) => {
    if (previousContextKey !== currentContextKey) {
        return { expandedMarkerGroupKey: null, selectedMarkerId: null };
    }
    const selectedExists = selectedMarkerId === null
        || markerModel.markers.some(({ id }) => id === selectedMarkerId);
    const groupExists = expandedMarkerGroupKey === null || markerModel.domMarkerGroups
        .some(({ price }) => expandedMarkerGroupKey === `dom:${price}`)
        || markerModel.markers.some(({ matchedTradeId }) => expandedMarkerGroupKey === `trade:${matchedTradeId}`);
    return {
        expandedMarkerGroupKey: groupExists ? expandedMarkerGroupKey : null,
        selectedMarkerId: selectedExists ? selectedMarkerId : null,
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

const scopedSummary = (markers) => {
    const byType = Object.fromEntries(REPLAY_MARKER_TYPES.map((type) => [
        type, markers.filter((marker) => marker.type === type).length,
    ]));
    return {
        total: markers.length,
        byType,
        buy: byType.BUY, sell: byType.SELL, entry: byType.ENTRY, exit: byType.EXIT,
        reduceOnly: markers.filter(({ reduceOnly }) => reduceOnly).length,
        flatten: markers.filter(({ flatten }) => flatten).length,
        failed: markers.filter(({ failed }) => failed).length,
        blocked: markers.filter(({ blocked }) => blocked).length,
        unknown: markers.filter(({ type }) => !REPLAY_MARKER_TYPES.includes(type)).length,
    };
};

export function buildReplayMarkerOverlayModel(replayEngine, marketViewModel = {}) {
    const markerContext = replayEngine?.projection?.markerContext;
    const liveMarkers = marketViewModel?.normalizedMarketModel?.source?.mode === "LIVE"
        && Array.isArray(marketViewModel.normalizedMarketModel.markers)
        ? marketViewModel.normalizedMarketModel.markers : null;
    const unscopedSource = liveMarkers ?? (Array.isArray(markerContext?.markers) ? markerContext.markers : []);
    const contextEventIds = Array.isArray(marketViewModel?.contextEventIds)
        ? new Set(marketViewModel.contextEventIds) : null;
    const contextScopeActive = liveMarkers === null
        && Boolean(marketViewModel?.marketContext?.key && contextEventIds);
    const source = contextScopeActive ? unscopedSource.filter((marker) => contextEventIds.has(marker?.eventId)) : unscopedSource;
    const normalized = source.map(markerFromContract).filter(Boolean).sort(markerOrder);
    const summary = liveMarkers !== null || contextScopeActive
        ? scopedSummary(normalized) : formalSummary(markerContext);
    const bookRows = [...(Array.isArray(marketViewModel?.orderBook?.asks) ? marketViewModel.orderBook.asks : []),
        ...(Array.isArray(marketViewModel?.orderBook?.bids) ? marketViewModel.orderBook.bids : [])];
    const tickSize = marketViewModel?.marketContext?.tickSize;
    const bookPrices = new Map(bookRows.map(({ numericPrice, price }) => {
        const value = finite(numericPrice) ? numericPrice : Number(price);
        return [normalizedPrice(value, tickSize), value];
    }).filter(([price]) => finite(price)));
    const trades = Array.isArray(marketViewModel?.recentTrades?.rows) ? marketViewModel.recentTrades.rows : [];

    const markers = normalized.map((marker) => {
        const normalizedMarkerPrice = normalizedPrice(marker.numericPrice, tickSize);
        const priceMatch = finite(normalizedMarkerPrice) && bookPrices.has(normalizedMarkerPrice);
        const matchedTrade = trades.find((trade) => formalTradeMatch(marker, trade));
        return { ...marker, normalizedPrice: normalizedMarkerPrice,
            domPrice: priceMatch ? bookPrices.get(normalizedMarkerPrice) : null,
            priceMatch, timeMatch: Boolean(matchedTrade), tradeMatch: Boolean(matchedTrade),
            matchedTradeId: matchedTrade?.id ?? DASH,
            accessibilityLabel: `${marker.label}${finite(marker.numericPrice) ? ` at ${marker.price}` : ""}` };
    });
    const domMarkers = markers.filter(({ priceMatch }) => priceMatch);
    const domMarkerGroups = [...new Set(domMarkers.map(({ domPrice }) => domPrice))].map((price) => {
        const group = domMarkers.filter(({ domPrice }) => domPrice === price);
        return { price, markers: group, visibleMarkers: group.slice(0, MAX_INLINE),
            remainingCount: Math.max(0, group.length - MAX_INLINE) };
    });
    const allPriceMarkers = markers.filter(({ numericPrice }) => finite(numericPrice));
    const allTimeMarkers = markers.filter(({ timestamp }) => timestamp !== DASH);
    const allUnmatched = markers.filter(({ priceMatch, timeMatch }) => !priceMatch && !timeMatch);
    const formalLatestId = markerContext?.latestMarker?.id;
    const latestMarker = liveMarkers !== null ? markers[0] ?? null
        : markers.find(({ id }) => id === formalLatestId) ?? null;
    const byQuality = Object.fromEntries(REPLAY_DATA_QUALITY.map((quality) => [
        quality, markers.filter((marker) => marker.dataQuality === quality).length,
    ]));
    const displayedIds = new Set([
        ...allPriceMarkers.slice(0, MAX_PRICE), ...allTimeMarkers.slice(0, MAX_TIME), ...allUnmatched.slice(0, MAX_UNMATCHED),
    ].map(({ id }) => id));

    return {
        markers,
        domMarkers,
        domMarkerGroups,
        maxInlineMarkers: MAX_INLINE,
        priceMarkers: allPriceMarkers.slice(0, MAX_PRICE),
        timeMarkers: allTimeMarkers.slice(0, MAX_TIME),
        unmatchedMarkers: allUnmatched.slice(0, MAX_UNMATCHED),
        detailMarkers: markers.slice(0, MAX_DETAILS),
        latestMarker,
        summary,
        counts: {
            visible: liveMarkers !== null || contextScopeActive ? markers.length
                : Number.isInteger(markerContext?.count) && markerContext.count >= 0 ? markerContext.count : 0,
            priceMatched: markers.filter(({ priceMatch }) => priceMatch).length,
            timeMatched: markers.filter(({ timeMatch }) => timeMatch).length,
            unmatched: allUnmatched.length,
            byType: summary.byType,
        },
        legend: LEGEND,
        quality: replayEngine?.projection?.dataQuality ?? "UNKNOWN",
        diagnostics: {
            sourceMarkerCount: unscopedSource.length,
            contextExcludedMarkerCount: unscopedSource.length - source.length,
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
