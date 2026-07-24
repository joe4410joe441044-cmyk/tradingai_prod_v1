import { buildReplayMarketViewModel } from "../replay/replayMarketViewModel.js";
import { createNormalizedMarketModel, NORMALIZED_MARKET_ISSUES } from "./normalizedMarketModel.js";

const finite = (value) => typeof value === "number" && Number.isFinite(value);
const payloadOf = (event) => event?.payload && typeof event.payload === "object"
    && !Array.isArray(event.payload) ? event.payload : {};

export function normalizeReplayMarketModel({ projection, replayEngine, cursor } = {}) {
    const engine = replayEngine ?? { projection };
    const presentation = buildReplayMarketViewModel(engine);
    const activeProjection = engine?.projection ?? projection ?? {};
    const currentEvent = activeProjection?.currentEvent;
    const currentPayload = payloadOf(currentEvent);
    const contextEventIds = new Set(presentation.contextEventIds);
    const projectionMarkers = Array.isArray(activeProjection?.markerContext?.markers)
        ? activeProjection.markerContext.markers : [];
    const markers = projectionMarkers.filter((marker) => !presentation.diagnostics.contextChanged
        || !marker?.eventId || contextEventIds.has(marker.eventId));
    const issues = [];
    if (markers.length !== projectionMarkers.length) issues.push(NORMALIZED_MARKET_ISSUES.CONTEXT_MISMATCH);
    const machineState = engine?.machine?.state;
    const loading = ["REPLAY_LOADING", "LOADING"].includes(machineState);
    const unavailable = machineState === "REPLAY_ERROR";
    const quality = activeProjection?.dataQuality;
    const stale = quality === "STALE";
    return createNormalizedMarketModel({
        context: presentation.marketContext.key ? {
            exchange: presentation.marketContext.exchange,
            marketType: presentation.marketContext.marketType,
            exchangeSymbol: presentation.marketContext.exchangeSymbol,
            normalizedSymbol: presentation.marketContext.normalizedSymbol,
            displaySymbol: presentation.marketContext.displaySymbol,
            tickSize: presentation.marketContext.tickSize,
            pricePrecision: presentation.marketContext.pricePrecision,
            lotSize: presentation.marketContext.lotSize,
            quantityPrecision: presentation.marketContext.quantityPrecision,
        } : null,
        source: {
            mode: "REPLAY",
            provider: "REPLAY_PROJECTION",
            datasetId: engine?.dataset?.id ?? engine?.dataset?.datasetId,
            connectionId: null,
        },
        timestamps: {
            observedAt: currentEvent?.timestamp,
            receivedAt: null,
            sourceUpdatedAt: currentEvent?.timestamp,
            cursorTimestamp: cursor ?? engine?.replayCursor
                ?? activeProjection?.replayCursor ?? currentEvent?.timestamp,
        },
        currentPrice: finite(Number(presentation.header.currentPrice))
            ? Number(presentation.header.currentPrice) : finite(currentPayload?.lastTradePrice)
                ? currentPayload.lastTradePrice : null,
        orderBook: {
            asks: presentation.orderBook.asks.map((row) => ({
                price: row.numericPrice, quantity: row.numericSize,
                cumulativeQuantity: row.numericCumulativeQuantity,
            })),
            bids: presentation.orderBook.bids.map((row) => ({
                price: row.numericPrice, quantity: row.numericSize,
                cumulativeQuantity: row.numericCumulativeQuantity,
            })),
        },
        recentTrades: presentation.recentTrades.rows.map((trade) => ({
            id: trade.id,
            timestamp: trade.timestamp,
            sequence: trade.sourceSequence,
            price: trade.numericPrice,
            quantity: trade.numericSize,
            side: trade.side,
            eventId: trade.eventId === "—" ? null : trade.eventId,
            tradeId: trade.tradeId === "—" ? null : trade.tradeId,
            orderId: trade.orderId === "—" ? null : trade.orderId,
        })),
        markers,
        issues,
        loading,
        unavailable,
        stale,
    });
}
